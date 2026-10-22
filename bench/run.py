"""실행 중인 서버에 질문 세트를 보내 단계별 지연을 jsonl 로 기록한다 (before=/api/ask, after=/api/ask-stream, audio=/api/ask-audio-stream)."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipeline.wav import wav_stats

NUMERIC_FIELDS = ("total_ms", "first_audio_ms", "client_first_audio_ms", "client_total_ms", "audio_s")


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 1)


def _audio_s(b64: str) -> float:
    return wav_stats(base64.b64decode(b64)).duration_s


def _base(cfg: str, run: int, q: dict) -> dict[str, Any]:
    return {
        "kind": "record",
        "config": cfg,
        "run": run,
        "id": q["id"],
        "query": q["query"],
        "answer_chars": q.get("answer_chars"),
    }


def _hit(source: dict | None, qid: str) -> bool:
    return source is not None and source.get("id") == qid


def parse_sse(lines: Iterable[str]) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name: str | None = None
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line.startswith("event:"):
            name = line[len("event:"):].strip()
        elif line.startswith("data:") and name is not None:
            events.append((name, json.loads(line[len("data:"):].strip())))
            name = None
    return events


def record_from_ask(cfg: str, run: int, q: dict, resp: dict, client_ms: float) -> dict:
    timings = dict(resp["timings"])
    total = timings.pop("total_ms")
    rec = _base(cfg, run, q)
    rec.update(
        {
            "hit": _hit(resp.get("source"), q["id"]),
            "sentence_count": None,
            "stages": {k: _r(v) for k, v in timings.items()},
            "total_ms": _r(total),
            "first_audio_ms": _r(total),
            "client_first_audio_ms": _r(client_ms),
            "client_total_ms": _r(client_ms),
            "audio_s": _audio_s(resp["audio_wav_b64"]),
            "status": "ok",
            "error": None,
        }
    )
    return rec


def record_from_stream(
    cfg: str,
    run: int,
    q: dict,
    events: list[tuple[str, dict]],
    client_first_ms: float | None,
    client_total_ms: float,
) -> dict:
    rec = _base(cfg, run, q)
    meta = next((d for n, d in events if n == "meta"), None)
    rec["hit"] = _hit(meta.get("source") if meta else None, q["id"])
    err = next((d for n, d in events if n == "error"), None)
    done = next((d for n, d in events if n == "done"), None)
    if err is not None or done is None:
        rec.update(error_fields("missing done event" if err is None else str(err.get("detail"))))
        rec["sentence_count"] = meta.get("sentence_count") if meta else None
        return rec
    timings = dict(done["timings"])
    total = timings.pop("total_ms")
    first = timings.pop("first_audio_ms")
    rec.update(
        {
            "sentence_count": done["sentence_count"],
            "stages": {k: _r(v) for k, v in timings.items()},
            "total_ms": _r(total),
            "first_audio_ms": _r(first),
            "client_first_audio_ms": _r(client_first_ms),
            "client_total_ms": _r(client_total_ms),
            "audio_s": round(sum(_audio_s(d["audio_wav_b64"]) for n, d in events if n == "audio"), 3),
            "status": "ok",
            "error": None,
        }
    )
    return rec


def error_fields(error: str) -> dict[str, Any]:
    out: dict[str, Any] = {k: None for k in NUMERIC_FIELDS}
    out.update({"stages": None, "status": "error", "error": error})
    return out


def error_record(cfg: str, run: int, q: dict, error: str) -> dict:
    rec = _base(cfg, run, q)
    rec.update({"hit": False, "sentence_count": None})
    rec.update(error_fields(error))
    return rec


def _post(base_url: str, endpoint: str, text: str, timeout: float) -> Any:
    return _post_bytes(base_url, endpoint, json.dumps({"text": text}).encode(), "application/json", timeout)


def _post_bytes(base_url: str, endpoint: str, data: bytes, content_type: str, timeout: float) -> Any:
    req = urllib.request.Request(
        base_url.rstrip("/") + endpoint,
        data=data,
        headers={"Content-Type": content_type},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)


def run_before(cfg: str, run: int, q: dict, base_url: str, timeout: float) -> dict:
    t0 = time.perf_counter()
    with _post(base_url, CONFIGS[cfg]["endpoint"], q["query"], timeout) as r:
        body = r.read()
    client_ms = (time.perf_counter() - t0) * 1000
    return record_from_ask(cfg, run, q, json.loads(body), client_ms)


def run_after(cfg: str, run: int, q: dict, base_url: str, timeout: float) -> dict:
    events, first, total = _read_stream(lambda: _post(base_url, CONFIGS[cfg]["endpoint"], q["query"], timeout))
    return record_from_stream(cfg, run, q, events, first, total)


def run_audio(cfg: str, run: int, q: dict, base_url: str, timeout: float, audio_dir: Path = Path("bench/audio")) -> dict:
    data = (Path(audio_dir) / f"{q['id']}.wav").read_bytes()
    events, first, total = _read_stream(
        lambda: _post_bytes(base_url, CONFIGS[cfg]["endpoint"], data, "audio/wav", timeout)
    )
    rec = record_from_stream(cfg, run, q, events, first, total)
    meta = next((d for n, d in events if n == "meta"), None)
    rec["transcript"] = meta.get("transcript") if meta and rec["status"] == "ok" else None
    return rec


def _read_stream(open_req: Callable[[], Any]) -> tuple[list[tuple[str, dict]], float | None, float]:
    lines: list[str] = []
    first: float | None = None
    t0 = time.perf_counter()
    total = 0.0
    with open_req() as r:
        for raw in r:
            line = raw.decode("utf-8").rstrip("\r\n")
            lines.append(line)
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
                if name == "audio" and first is None:
                    first = (time.perf_counter() - t0) * 1000
                if name in ("done", "error"):
                    total = (time.perf_counter() - t0) * 1000
    if total == 0.0:
        total = (time.perf_counter() - t0) * 1000
    return parse_sse(lines), first, total


CONFIGS: dict[str, dict[str, Any]] = {
    "before": {"endpoint": "/api/ask", "run": run_before},
    "after": {"endpoint": "/api/ask-stream", "run": run_after},
    "audio": {"endpoint": "/api/ask-audio-stream", "run": run_audio},
}


def _health(base_url: str, timeout: float) -> dict | None:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=timeout) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def run_one(
    cfg: str, run: int, q: dict, base_url: str, timeout: float, audio_dir: Path = Path("bench/audio")
) -> dict:
    fn: Callable[..., dict] = CONFIGS[cfg]["run"]
    if cfg == "audio":
        if not (Path(audio_dir) / f"{q['id']}.wav").is_file():
            return _with_transcript(error_record(cfg, run, q, "missing audio file"))
        try:
            return fn(cfg, run, q, base_url, timeout, audio_dir)
        except urllib.error.HTTPError as e:
            return _with_transcript(error_record(cfg, run, q, f"HTTP {e.code}"))
        except (OSError, ValueError, KeyError) as e:
            return _with_transcript(error_record(cfg, run, q, type(e).__name__))
    try:
        return fn(cfg, run, q, base_url, timeout)
    except urllib.error.HTTPError as e:
        return error_record(cfg, run, q, f"HTTP {e.code}")
    except (OSError, ValueError, KeyError) as e:  # 타임아웃·연결 오류 등: 기록하고 다음으로
        return error_record(cfg, run, q, type(e).__name__)


def _with_transcript(rec: dict) -> dict:
    rec["transcript"] = None
    return rec


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, choices=sorted(CONFIGS))
    p.add_argument("--base-url", default="http://localhost:8765")
    p.add_argument("--questions", default="bench/questions.jsonl")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", default=None)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--concurrency", type=_positive_int, default=1)
    p.add_argument("--audio-dir", default="bench/audio")
    a = p.parse_args(argv)

    questions = [json.loads(line) for line in Path(a.questions).read_text(encoding="utf-8").splitlines() if line.strip()]
    if a.limit > 0:
        questions = questions[: a.limit]
    audio_dir = Path(a.audio_dir)
    out = Path(a.out or f"bench/results/{a.config}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    header = {
        "kind": "header",
        "config": a.config,
        "endpoint": CONFIGS[a.config]["endpoint"],
        "base_url": a.base_url,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "runs": a.runs,
        "questions": len(questions),
        "input": "audio" if a.config == "audio" else "text",
        "concurrency": a.concurrency,
        "health": _health(a.base_url, a.timeout),
    }
    errors = 0
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
            futures = {
                ex.submit(run_one, a.config, run, q, a.base_url, a.timeout, audio_dir): (run, i, q)
                for run in range(1, a.runs + 1)
                for i, q in enumerate(questions, 1)
            }
            for fut in as_completed(futures):
                run, i, q = futures[fut]
                rec = fut.result()
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                if rec["status"] != "ok":
                    errors += 1
                    msg = f"error={rec['error']}"
                else:
                    msg = f"ok total_ms={rec['total_ms']}"
                print(f"run {run}/{a.runs} q {i}/{len(questions)} {q['id']} {msg}", file=sys.stderr, flush=True)
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
