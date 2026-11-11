import importlib
import io
import json
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Self

import pytest

BENCH = Path(__file__).resolve().parents[2] / "bench"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))
run = importlib.import_module("run")

Q = {"id": "faq-001", "query": "질문", "answer_chars": 46}


def _wav_bytes(seconds: float = 0.25, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


class _FakeResp:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [(line + "\n").encode("utf-8") for line in lines]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._lines)


def _sse(transcript: str) -> list[str]:
    import base64

    b64 = base64.b64encode(_wav_bytes()).decode("ascii")
    meta = {"transcript": transcript, "answer": "a", "source": {"id": "faq-001"}, "sentence_count": 1, "timings": {}}
    audio = {"index": 0, "text": "a", "audio_wav_b64": b64, "tts_ms": 10, "elapsed_ms": 20}
    done = {
        "sentence_count": 1,
        "timings": {"stt_ms": 5.0, "retrieve_ms": 1.0, "llm_ms": 0.0, "tts_ms": 10.0,
                    "total_ms": 30.0, "first_audio_ms": 20.0},
    }
    out: list[str] = []
    for name, data in (("meta", meta), ("audio", audio), ("done", done)):
        out += [f"event: {name}", "data: " + json.dumps(data, ensure_ascii=False), ""]
    return out


def _questions(tmp_path: Path, n: int) -> Path:
    p = tmp_path / "q.jsonl"
    p.write_text("".join(json.dumps({"id": f"q-{i}", "query": "x"}) + "\n" for i in range(n)), encoding="utf-8")
    return p


def _read(out: Path) -> tuple[dict, list[dict]]:
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    return rows[0], rows[1:]


def test_concurrency_bounds_in_flight_and_no_duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def fake_run_one(cfg, r, q, base_url, timeout, audio_dir=None):  # type: ignore[no-untyped-def]
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.02)
        with lock:
            state["now"] -= 1
        rec = run.error_record(cfg, r, q, "x")
        rec.update({"status": "ok", "error": None, "total_ms": 1.0})
        return rec

    monkeypatch.setattr(run, "run_one", fake_run_one)
    monkeypatch.setattr(run, "_health", lambda *a: None)
    out = tmp_path / "out.jsonl"
    code = run.main(["--config", "after", "--questions", str(_questions(tmp_path, 6)), "--runs", "2",
                     "--concurrency", "4", "--out", str(out)])
    assert code == 0
    _, recs = _read(out)
    pairs = [(r["run"], r["id"]) for r in recs]
    assert len(pairs) == 12 and len(set(pairs)) == 12
    assert 1 < state["max"] <= 4


def test_header_concurrency_and_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "_health", lambda *a: None)
    monkeypatch.setattr(run, "run_one", lambda cfg, r, q, *a, **k: run.error_record(cfg, r, q, "x"))
    qs = str(_questions(tmp_path, 1))
    out = tmp_path / "a.jsonl"
    assert run.main(["--config", "audio", "--questions", qs, "--runs", "1", "--concurrency", "3",
                     "--out", str(out)]) == 2
    header, _ = _read(out)
    assert header["concurrency"] == 3 and header["input"] == "audio"
    assert header["endpoint"] == "/api/ask-audio-stream"
    out2 = tmp_path / "t.jsonl"
    run.main(["--config", "after", "--questions", qs, "--runs", "1", "--out", str(out2)])
    header2, _ = _read(out2)
    assert header2["concurrency"] == 1 and header2["input"] == "text"


def test_missing_wav_yields_error_without_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(run, "_post_bytes", lambda *a, **k: calls.append(a))
    rec = run.run_one("audio", 1, Q, "http://localhost:1", 2.0, tmp_path)
    assert rec["status"] == "error" and rec["error"] == "missing audio file"
    assert rec["transcript"] is None
    assert calls == []


def test_audio_record_transcript_from_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "faq-001.wav").write_bytes(_wav_bytes())
    seen: dict = {}

    def fake_post_bytes(base_url, endpoint, data, content_type, timeout):  # type: ignore[no-untyped-def]
        seen.update(endpoint=endpoint, data=data, content_type=content_type)
        return _FakeResp(_sse("주민등록등본 떼려면"))

    monkeypatch.setattr(run, "_post_bytes", fake_post_bytes)
    rec = run.run_one("audio", 1, Q, "http://localhost:1", 2.0, tmp_path)
    assert rec["status"] == "ok"
    assert rec["transcript"] == "주민등록등본 떼려면"
    assert rec["total_ms"] == 30.0 and rec["first_audio_ms"] == 20.0 and rec["hit"] is True
    assert seen["endpoint"] == "/api/ask-audio-stream" and seen["content_type"] == "audio/wav"
    assert seen["data"] == (tmp_path / "faq-001.wav").read_bytes()


def test_audio_error_event_transcript_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "faq-001.wav").write_bytes(_wav_bytes())
    lines = ["event: meta", 'data: {"transcript": "t", "source": null}', "",
             "event: error", 'data: {"detail": "boom"}', ""]
    monkeypatch.setattr(run, "_post_bytes", lambda *a, **k: _FakeResp(lines))
    rec = run.run_one("audio", 1, Q, "http://localhost:1", 2.0, tmp_path)
    assert rec["status"] == "error" and rec["error"] == "boom" and rec["transcript"] is None


def test_concurrency_zero_is_argparse_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as e:
        run.main(["--config", "after", "--concurrency", "0", "--out", str(tmp_path / "x.jsonl")])
    assert e.value.code == 2


def test_run_one_four_positional_args_still_work() -> None:
    rec = run.run_one("after", 1, Q, "http://localhost:1", 2.0)
    assert rec["status"] == "error" and "transcript" not in rec
