"""bench 결과 jsonl 두 개(before/after)에서 summary.md 표와 ASCII 폭포를 만든다."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

STAGE_ORDER = ["stt_ms", "retrieve_ms", "llm_ms", "tts_ms"]
STAGE_LABEL = {"stt_ms": "STT", "retrieve_ms": "검색", "llm_ms": "LLM", "tts_ms": "TTS"}
STAGE_NOTE = {
    "stt_ms": "글자 입력, STT 미포함",
    "retrieve_ms": "BM25",
    "llm_ms": "Qwen qwen3.7-flash (API)",
    "tts_ms": "after 는 문장별 합",
}


def percentile(xs: list[float], p: float) -> float:
    """선형 보간 백분위수 (p: 0~100)."""
    if not xs:
        raise ValueError("percentile of empty list")
    s = sorted(xs)
    k = (len(s) - 1) * p / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(s[lo])
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def stage_label(key: str) -> str:
    return STAGE_LABEL.get(key, key)


def ordered_stage_keys(keys: Any) -> list[str]:
    ks = set(keys)
    return [k for k in STAGE_ORDER if k in ks] + sorted(ks - set(STAGE_ORDER))


def _pp(xs: list[float]) -> dict[str, float | None]:
    if not xs:
        return {"p50": None, "p95": None}
    return {"p50": round(percentile(xs, 50), 1), "p95": round(percentile(xs, 95), 1)}


def summarize(records: list[dict]) -> dict:
    recs = [r for r in records if r.get("kind", "record") == "record"]
    ok = [r for r in recs if r.get("status") == "ok"]
    stage_vals: dict[str, list[float]] = {}
    for r in ok:
        for k, v in (r.get("stages") or {}).items():
            if v is not None:
                stage_vals.setdefault(k, []).append(float(v))

    def col(name: str) -> list[float]:
        return [float(r[name]) for r in ok if r.get(name) is not None]

    audio_ms = sum(float(r.get("audio_s") or 0.0) * 1000 for r in ok)
    tts = sum(float((r.get("stages") or {}).get("tts_ms") or 0.0) for r in ok)
    return {
        "n": len(recs),
        "errors": len(recs) - len(ok),
        "hit": sum(1 for r in ok if r.get("hit")),
        "first_audio": _pp(col("first_audio_ms")),
        "total": _pp(col("total_ms")),
        "stages": {k: _pp(stage_vals[k]) for k in ordered_stage_keys(stage_vals)},
        "rtf": round(tts / audio_ms, 2) if audio_ms > 0 else None,
        "client_first_audio": _pp(col("client_first_audio_ms")),
    }


def _ms(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}"


def _pair(d: dict) -> str:
    return f"{_ms(d['p50'])} / {_ms(d['p95'])} ms"


def _stage_p50(s: dict, key: str) -> str:
    st = s["stages"].get(key)
    return f"{_ms(st['p50'] if st else None)} ms"


def render_table(before: dict, after: dict) -> str:
    rows = [
        "| 지표 | before (/api/ask) | after (/api/ask-stream) | 비고 |",
        "|---|---|---|---|",
        (
            f"| 첫 음성까지 (p50 / p95) | {_pair(before['first_audio'])} | {_pair(after['first_audio'])} "
            "| 서버 측. before 는 응답 완료 = total_ms |"
        ),
        (
            f"| 전체 응답 (p50 / p95) | {_pair(before['total'])} | {_pair(after['total'])} "
            "| total_ms (after 는 마지막 문장 WAV 까지) |"
        ),
    ]
    for k in STAGE_ORDER:
        rows.append(f"| {stage_label(k)} (p50) | {_stage_p50(before, k)} | {_stage_p50(after, k)} | {STAGE_NOTE[k]} |")
    extra = ordered_stage_keys(set(before["stages"]) | set(after["stages"]))
    for k in extra:
        if k not in STAGE_ORDER:
            rows.append(f"| {stage_label(k)} (p50) | {_stage_p50(before, k)} | {_stage_p50(after, k)} | |")

    def rtf(s: dict) -> str:
        return "n/a" if s["rtf"] is None else f"{s['rtf']:.2f}"

    def hit(s: dict) -> str:
        return f"{s['hit']}/{s['n']}"

    rows += [
        f"| TTS RTF (동시 1) | {rtf(before)} | {rtf(after)} | tts_ms / 음성 길이 |",
        "| 동시 4 요청 | 미측정 | 미측정 | 이번 범위 밖 |",
        f"| 검색 적중 (top1 = 질문 id) | {hit(before)} | {hit(after)} | |",
        (
            f"| 요청 수 (오류) | {before['n']} ({before['errors']}) | {after['n']} ({after['errors']}) "
            f"| {_runs_note(before)} |"
        ),
    ]
    rows.append("")
    rows.append(
        f"클라이언트 측 첫 음성 p50: before {_ms(before['client_first_audio']['p50'])} ms"
        f" / after {_ms(after['client_first_audio']['p50'])} ms"
    )
    return "\n".join(rows) + "\n"


def _runs_note(s: dict) -> str:
    q, runs = s.get("questions"), s.get("runs")
    if q and runs:
        return f"{q} 질문 × {runs} 회"
    return ""


CHARS_PER_S = 8


def _sec(ms: float | None) -> float:
    return (ms or 0.0) / 1000.0


def _seg(label: str, ms: float, dashed: bool = False) -> str:
    text = f" {label} {_sec(ms):.1f} "
    width = max(len(text), round(_sec(ms) * CHARS_PER_S))
    fill = width - len(text)
    left = fill // 2
    dash = "┄" if dashed else "─"
    return "├" + dash * left + text + dash * (fill - left) + "┤"


def _p50(s: dict, key: str) -> float:
    st = s["stages"].get(key)
    return float(st["p50"]) if st and st["p50"] is not None else 0.0


def render_ascii(before: dict, after: dict) -> str:
    b_keys = list(before["stages"])
    b_line = "".join(_seg(stage_label(k), _p50(before, k)) for k in b_keys)
    b_total = before["total"]["p50"] or 0.0
    b_line = f" before  {b_line}  = {_sec(b_total):.1f}s"
    head = [k for k in after["stages"] if k != "tts_ms"]
    head_ms = sum(_p50(after, k) for k in head)
    fa = after["first_audio"]["p50"] or 0.0
    tot = after["total"]["p50"] or 0.0
    a_line = "".join(_seg(stage_label(k), _p50(after, k)) for k in head)
    a_line += _seg("TTS 첫 문장", max(fa - head_ms, 0.0))
    a_line += _seg("나머지 스트리밍", max(tot - fa, 0.0), dashed=True)
    a_line = f" after   {a_line}  = 첫 음성까지 {_sec(fa):.1f}s"
    max_s = math.ceil(max(_sec(b_total), _sec(tot), 1.0))
    ticks = "".join(str(i).ljust(CHARS_PER_S) for i in range(max_s + 1)).rstrip()
    axis = "         " + ticks + " (s)"
    title = " 질문 1건 응답 시간 (중앙값, 공개 FAQ 50문항 × 3회)"
    return f"{title}\n\n{b_line}\n{a_line}\n{axis}\n"


def load(path: Path) -> tuple[dict, list[dict]]:
    header: dict = {}
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        else:
            records.append(obj)
    return header, records


def load_summary(path: Path) -> dict:
    header, records = load(path)
    s = summarize(records)
    s["runs"] = header.get("runs")
    s["questions"] = header.get("questions")
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", type=Path, default=Path("bench/results/before.jsonl"))
    ap.add_argument("--after", type=Path, default=Path("bench/results/after.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("bench/results/summary.md"))
    a = ap.parse_args(argv)
    for p in (a.before, a.after):
        if not p.exists():
            print(f"input not found: {p}", file=sys.stderr)
            return 1
    before, after = load_summary(a.before), load_summary(a.after)
    table = render_table(before, after)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(table, encoding="utf-8")
    print(table)
    print(render_ascii(before, after))
    return 0


if __name__ == "__main__":
    sys.exit(main())
