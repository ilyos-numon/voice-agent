import json
import re
import subprocess
from pathlib import Path

from playwright.sync_api import Page

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IP_RE = re.compile(r"\d+\.\d+\.\d+\.\d+")
STAGE_KEYS = {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms"}


def run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, check=False, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300
    )


def bench_run(config: str, base_url: str, out: Path) -> subprocess.CompletedProcess[str]:
    return run_cmd(
        [
            "./bench/run.sh", "--config", config, "--base-url", base_url,
            "--runs", "1", "--limit", "2", "--out", str(out),
        ]
    )


def load(path: Path) -> tuple[dict, list[dict]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows[0], rows[1:]


def test_bench_run_before_small(base_url: str, tmp_path: Path) -> None:
    out = tmp_path / "before.jsonl"
    r = bench_run("before", base_url, out)
    assert r.returncode == 0, r.stderr
    header, recs = load(out)
    assert header["kind"] == "header"
    assert header["endpoint"] == "/api/ask"
    assert len(recs) == 2
    for x in recs:
        assert x["status"] == "ok"
        assert set(x["stages"]) >= STAGE_KEYS
        assert x["first_audio_ms"] == x["total_ms"]
        assert x["audio_s"] > 0


def test_bench_run_after_small(base_url: str, tmp_path: Path) -> None:
    out = tmp_path / "after.jsonl"
    r = bench_run("after", base_url, out)
    assert r.returncode == 0, r.stderr
    header, recs = load(out)
    assert header["endpoint"] == "/api/ask-stream"
    assert len(recs) == 2
    for x in recs:
        assert x["status"] == "ok"
        assert 0 < x["first_audio_ms"] <= x["total_ms"]
        assert x["sentence_count"] >= 1
        assert x["client_first_audio_ms"] > 0
        assert "first_audio_ms" not in x["stages"]


def test_bench_summarize_and_plot(
    base_url: str, tmp_path: Path, page: Page, shot_dir: Path
) -> None:
    before, after = tmp_path / "before.jsonl", tmp_path / "after.jsonl"
    assert bench_run("before", base_url, before).returncode == 0
    assert bench_run("after", base_url, after).returncode == 0

    r = run_cmd(
        [
            "./bench/summarize.sh", "--before", str(before), "--after", str(after),
            "--out-dir", str(tmp_path),
        ]
    )
    assert r.returncode == 0, r.stderr
    assert "| 첫 음성까지" in r.stdout
    lines = r.stdout.splitlines()
    assert any(ln.lstrip().startswith("before") for ln in lines)
    assert any(ln.lstrip().startswith("after") for ln in lines)

    summary = (tmp_path / "summary.md").read_text()
    assert "미측정" in summary
    svg = (tmp_path / "waterfall.svg").read_text()
    assert svg.startswith("<svg")

    for text in (r.stdout, summary, svg, before.read_text(), after.read_text()):
        assert not IP_RE.search(text)

    page.set_viewport_size({"width": 1000, "height": 400})
    page.set_content(svg)
    shot = shot_dir / "bench-waterfall-e2e.png"
    page.screenshot(path=str(shot))
    assert shot.stat().st_size > 5 * 1024
