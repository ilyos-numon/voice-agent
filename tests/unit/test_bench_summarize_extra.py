import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))
summarize = importlib.import_module("summarize")

EXTRA_LABELS = [
    "첫 음성까지 (p50 / p95)",
    "전체 응답 (p50 / p95)",
    "클라이언트 첫 음성 (p50 / p95)",
    "STT (p50)",
    "LLM (p50)",
    "TTS (p50)",
    "검색 적중 (top1 = 질문 id)",
    "요청 수 (오류)",
]


def _rec(cfg: str, i: int, total: float, first: float, status: str = "ok", hit: bool = True) -> dict:
    return {
        "kind": "record",
        "config": cfg,
        "run": 1,
        "id": f"faq-{i:03d}",
        "query": "q",
        "answer_chars": 100,
        "hit": hit,
        "sentence_count": 2,
        "stages": {"stt_ms": 1.0 + i, "retrieve_ms": 0.5, "llm_ms": 2.0, "tts_ms": 100.0 + i},
        "total_ms": total,
        "first_audio_ms": first,
        "client_first_audio_ms": first + 10,
        "client_total_ms": total + 10,
        "audio_s": 4.0,
        "status": status,
        "error": None if status == "ok" else "boom",
    }


def _recs(cfg: str, n: int = 4) -> list[dict]:
    return [_rec(cfg, i, 1000.0 + i * 10, 200.0 + i * 10) for i in range(n)]


def _header(cfg: str, endpoint: str, concurrency: int) -> dict:
    return {
        "kind": "header", "config": cfg, "endpoint": endpoint, "runs": 1, "questions": 4,
        "input": "audio" if cfg == "audio" else "text", "concurrency": concurrency,
    }


def _write(path: Path, header: dict, recs: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [header, *recs]) + "\n", encoding="utf-8")
    return path


def _three(tmp: Path, c4_concurrency: int = 4) -> tuple[Path, Path, Path]:
    c1 = _write(tmp / "c1.jsonl", _header("after", "/api/ask-stream", 1), _recs("after"))
    c4 = _write(tmp / "c4.jsonl", _header("after", "/api/ask-stream", c4_concurrency), _recs("after"))
    au = _write(tmp / "audio.jsonl", _header("audio", "/api/ask-audio-stream", 1), _recs("audio"))
    return c1, c4, au


def _before_after(tmp: Path) -> tuple[Path, Path]:
    b = _write(tmp / "before.jsonl", _header("before", "/api/ask", 1), _recs("before"))
    a = _write(tmp / "after.jsonl", _header("after", "/api/ask-stream", 1), _recs("after"))
    return b, a


def _labels(table: str) -> list[str]:
    return [ln.split("|")[1].strip() for ln in table.splitlines() if ln.startswith("| ") and "---" not in ln]


def test_render_extra_table_header_and_row_order() -> None:
    s = summarize.summarize(_recs("after"))
    s["questions"], s["runs"] = 4, 1
    table = summarize.render_extra_table(s, s, s)
    lines = table.splitlines()
    assert lines[0] == "| 지표 | 글자 동시 1 | 글자 동시 4 | 음성 입력 동시 1 | 비고 |"
    assert lines[1] == "|---|---|---|---|---|"
    assert _labels(table)[1:] == EXTRA_LABELS
    assert "| 요청 수 (오류) | 4 (0) | 4 (0) | 4 (0) | 4 질문 × 1 회 |" in table
    assert "| 검색 적중 (top1 = 질문 id) | 4/4 | 4/4 | 4/4 |" in table


def test_render_table_extra_false_unchanged() -> None:
    b = summarize.summarize(_recs("before"))
    a = summarize.summarize(_recs("after"))
    default = summarize.render_table(b, a)
    assert summarize.render_table(b, a, extra=False) == default
    assert "| 동시 4 요청 | 미측정 | 미측정 | 이번 범위 밖 |" in default


def test_render_table_extra_true_points_to_extra() -> None:
    b = summarize.summarize(_recs("before"))
    a = summarize.summarize(_recs("after"))
    table = summarize.render_table(b, a, extra=True)
    assert "이번 범위 밖" not in table
    assert "| 동시 4 요청 | 미측정 | 아래 추가 표 (summary-extra.md) | 구성은 표 아래 설명 |" in table
    assert _labels(table) == _labels(summarize.render_table(b, a))


def test_extra_table_excludes_error_records() -> None:
    recs = _recs("audio") + [_rec("audio", 9, 99999.0, 99999.0, status="error", hit=True)]
    s = summarize.summarize(recs)
    s["questions"], s["runs"] = 5, 1
    table = summarize.render_extra_table(s, s, s)
    assert "99999" not in table
    assert "| 요청 수 (오류) | 5 (1) | 5 (1) | 5 (1) |" in table
    assert "| 검색 적중 (top1 = 질문 id) | 4/5 |" in table


def test_partial_extra_inputs_exit_1_no_file(tmp_path: Path, capsys) -> None:
    b, a = _before_after(tmp_path)
    c1, c4, _ = _three(tmp_path)
    out, extra_out = tmp_path / "summary.md", tmp_path / "summary-extra.md"
    rc = summarize.main([
        "--before", str(b), "--after", str(a), "--out", str(out),
        "--c1", str(c1), "--c4", str(c4), "--extra-out", str(extra_out),
    ])
    assert rc == 1
    assert "need --c1 --c4 --audio together" in capsys.readouterr().err
    assert not out.exists() and not extra_out.exists()


def test_c4_with_concurrency_1_exit_1(tmp_path: Path, capsys) -> None:
    b, a = _before_after(tmp_path)
    c1, c4, au = _three(tmp_path, c4_concurrency=1)
    out, extra_out = tmp_path / "summary.md", tmp_path / "summary-extra.md"
    rc = summarize.main([
        "--before", str(b), "--after", str(a), "--out", str(out),
        "--c1", str(c1), "--c4", str(c4), "--audio", str(au), "--extra-out", str(extra_out),
    ])
    assert rc == 1
    assert "--c4" in capsys.readouterr().err
    assert not out.exists() and not extra_out.exists()


def test_audio_wrong_endpoint_exit_1(tmp_path: Path, capsys) -> None:
    b, a = _before_after(tmp_path)
    c1, c4, _ = _three(tmp_path)
    au = _write(tmp_path / "audio.jsonl", _header("after", "/api/ask-stream", 1), _recs("after"))
    rc = summarize.main([
        "--before", str(b), "--after", str(a), "--out", str(tmp_path / "summary.md"),
        "--c1", str(c1), "--c4", str(c4), "--audio", str(au), "--extra-out", str(tmp_path / "x.md"),
    ])
    assert rc == 1
    assert "--audio" in capsys.readouterr().err


def test_main_writes_extra_and_points_main_table(tmp_path: Path) -> None:
    b, a = _before_after(tmp_path)
    c1, c4, au = _three(tmp_path)
    out, extra_out = tmp_path / "summary.md", tmp_path / "summary-extra.md"
    rc = summarize.main([
        "--before", str(b), "--after", str(a), "--out", str(out),
        "--c1", str(c1), "--c4", str(c4), "--audio", str(au), "--extra-out", str(extra_out),
    ])
    assert rc == 0
    assert "아래 추가 표 (summary-extra.md)" in out.read_text(encoding="utf-8")
    assert _labels(extra_out.read_text(encoding="utf-8"))[1:] == EXTRA_LABELS


def test_summarize_sh_extra_and_partial(tmp_path: Path) -> None:
    b, a = _before_after(tmp_path)
    c1, c4, au = _three(tmp_path)
    base = ["./bench/summarize.sh", "--before", str(b), "--after", str(a), "--out-dir", str(tmp_path)]
    r = subprocess.run(
        [*base, "--c1", str(c1), "--c4", str(c4), "--audio", str(au)],
        check=False, cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert _labels((tmp_path / "summary-extra.md").read_text(encoding="utf-8"))[1:] == EXTRA_LABELS
    (tmp_path / "summary-extra.md").unlink()
    r = subprocess.run(
        [*base, "--c1", str(c1)],
        check=False, cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 1
    assert "need --c1 --c4 --audio together" in r.stderr
    assert not (tmp_path / "summary-extra.md").exists()
