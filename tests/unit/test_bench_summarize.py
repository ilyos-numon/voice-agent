import importlib
import json
import subprocess
import sys
from pathlib import Path
from xml.dom import minidom

import pytest

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))
summarize = importlib.import_module("summarize")
plot = importlib.import_module("plot")


def _rec(cfg: str, i: int, total: float, first: float, stages: dict, status: str = "ok") -> dict:
    return {
        "kind": "record",
        "config": cfg,
        "run": 1,
        "id": f"faq-{i:03d}",
        "query": "q",
        "answer_chars": 100,
        "hit": True,
        "sentence_count": None,
        "stages": stages,
        "total_ms": total,
        "first_audio_ms": first,
        "client_first_audio_ms": first + 10,
        "client_total_ms": total + 10,
        "audio_s": 4.0,
        "status": status,
        "error": None,
    }


def _synthetic() -> tuple[list[dict], list[dict]]:
    before, after = [], []
    for i in range(10):
        d = (i - 4.5) * 100  # ±450
        b_tts = 5000 + d - 1.0
        before.append(
            _rec("before", i, 5000 + d, 5000 + d, {"stt_ms": 0.1, "retrieve_ms": 0.5, "llm_ms": 0.4, "tts_ms": b_tts})
        )
        fa = 800 + (i - 4.5) * 20
        after.append(
            _rec("after", i, 5000 + d, fa, {"stt_ms": 0.1, "retrieve_ms": 0.5, "llm_ms": 0.4, "tts_ms": b_tts})
        )
    return before, after


def test_percentile_interpolation_and_empty() -> None:
    assert summarize.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert summarize.percentile([10], 95) == 10
    assert summarize.percentile([0, 10], 95) == pytest.approx(9.5)
    with pytest.raises(ValueError):
        summarize.percentile([], 50)


def test_summarize_excludes_errors_and_keeps_unknown_stage() -> None:
    recs = [
        _rec("before", 1, 100, 100, {"tts_ms": 50, "rerank_ms": 5, "stt_ms": 1}),
        _rec("before", 2, 300, 300, {"tts_ms": 150, "rerank_ms": 7, "stt_ms": 1}),
    ]
    err = _rec("before", 3, 0, 0, {}, status="error")
    err.update(total_ms=None, first_audio_ms=None, hit=False, stages=None)
    s = summarize.summarize(recs + [err])
    assert s["n"] == 3 and s["errors"] == 1 and s["hit"] == 2
    assert s["total"]["p50"] == 200.0
    assert list(s["stages"]) == ["stt_ms", "tts_ms", "rerank_ms"]
    assert s["rtf"] == pytest.approx(200 / 8000, abs=0.01)


def test_render_table_rows_and_extra_key() -> None:
    b, a = _synthetic()
    a[0]["stages"]["rerank_ms"] = 3.0
    table = summarize.render_table(summarize.summarize(b), summarize.summarize(a))
    labels = [ln.split("|")[1].strip() for ln in table.splitlines() if ln.startswith("| ") and "---" not in ln]
    assert labels == [
        "지표",
        "첫 음성까지 (p50 / p95)",
        "전체 응답 (p50 / p95)",
        "STT (p50)",
        "검색 (p50)",
        "LLM (p50)",
        "TTS (p50)",
        "rerank_ms (p50)",
        "TTS RTF (동시 1)",
        "동시 4 요청",
        "검색 적중 (top1 = 질문 id)",
        "요청 수 (오류)",
    ]
    assert "| 동시 4 요청 | 미측정 | 미측정 |" in table
    assert "클라이언트 측 첫 음성 p50: before" in table


def test_render_ascii_two_bars() -> None:
    b, a = _synthetic()
    text = summarize.render_ascii(summarize.summarize(b), summarize.summarize(a))
    lines = text.splitlines()
    assert sum(1 for ln in lines if ln.strip().startswith("before")) == 1
    assert sum(1 for ln in lines if ln.strip().startswith("after")) == 1
    assert "TTS 첫 문장" in text and "첫 음성까지 0.8s" in text and "(s)" in text


def test_svg_contents_and_parses() -> None:
    b, a = _synthetic()
    svg = plot.render_svg(summarize.summarize(b), summarize.summarize(a))
    assert svg.startswith("<svg")
    for needle in ("before", "after", "TTS 첫 문장", "(s)", "나머지 스트리밍"):
        assert needle in svg
    minidom.parseString(svg.encode("utf-8"))


def _write(path: Path, cfg: str, recs: list[dict]) -> None:
    header = {"kind": "header", "config": cfg, "runs": 1, "questions": 10}
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [header, *recs]) + "\n", encoding="utf-8")


def test_summarize_sh_writes_outputs() -> None:
    out = Path("/tmp/bench-out")
    out.mkdir(parents=True, exist_ok=True)
    b, a = _synthetic()
    _write(out / "before.jsonl", "before", b)
    _write(out / "after.jsonl", "after", a)
    r = subprocess.run(
        ["./bench/summarize.sh", "--before", str(out / "before.jsonl"), "--after", str(out / "after.jsonl"),
         "--out-dir", str(out)],
        check=False, cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "| 첫 음성까지" in r.stdout and "after" in r.stdout
    assert (out / "waterfall.svg").read_bytes()[:5] == b"<svg "
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "| 요청 수 (오류) | 10 (0) | 10 (0) | 10 질문 × 1 회 |" in summary
    minidom.parse(str(out / "waterfall.svg"))


def test_summarize_sh_missing_input() -> None:
    r = subprocess.run(
        ["./bench/summarize.sh", "--before", "/nonexistent/b.jsonl", "--after", "/nonexistent/a.jsonl"],
        check=False, cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 1 and "not found" in r.stderr
