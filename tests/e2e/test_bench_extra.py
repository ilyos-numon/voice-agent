import json
import re
import subprocess
from pathlib import Path

from .test_bench import IP_RE, PROJECT_ROOT, load, run_cmd

EXTRA_HEADER = "| 지표 | 글자 동시 1 | 글자 동시 4 | 음성 입력 동시 1 | 비고 |"


def first_ids(n: int) -> list[str]:
    rows = (PROJECT_ROOT / "bench" / "questions.jsonl").read_text().splitlines()
    return [json.loads(r)["id"] for r in rows[:n]]


def bench(args: list[str]) -> subprocess.CompletedProcess[str]:
    return run_cmd(["./bench/run.sh", *args])


def test_bench_concurrency_4(base_url: str, tmp_path: Path) -> None:
    out = tmp_path / "c4.jsonl"
    r = bench(["--config", "after", "--base-url", base_url, "--concurrency", "4",
               "--runs", "1", "--limit", "4", "--out", str(out)])
    assert r.returncode == 0, r.stderr
    header, recs = load(out)
    assert header["concurrency"] == 4
    assert len(recs) == 4
    assert all(x["status"] == "ok" for x in recs)
    keys = [(x["run"], x["id"]) for x in recs]
    assert len(set(keys)) == 4


def test_bench_unreachable_server(tmp_path: Path) -> None:
    out = tmp_path / "down.jsonl"
    r = bench(["--config", "after", "--base-url", "http://localhost:9",
               "--runs", "1", "--limit", "2", "--out", str(out)])
    assert r.returncode == 2
    header, recs = load(out)
    assert header["kind"] == "header"
    assert len(recs) == 2
    assert all(x["status"] == "error" for x in recs)


def test_bench_invalid_concurrency_rejected(base_url: str, tmp_path: Path) -> None:
    r = bench(["--config", "after", "--base-url", base_url, "--concurrency", "0",
               "--runs", "1", "--limit", "1", "--out", str(tmp_path / "x.jsonl")])
    assert r.returncode == 2


def test_bench_audio_malformed_wav(base_url: str, tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / f"{first_ids(1)[0]}.wav").write_bytes(b"not audio")
    out = tmp_path / "bad.jsonl"
    r = bench(["--config", "audio", "--base-url", base_url, "--audio-dir", str(audio_dir),
               "--runs", "1", "--limit", "1", "--out", str(out)])
    assert r.returncode == 2
    _, recs = load(out)
    assert len(recs) == 1
    assert recs[0]["status"] == "error"
    assert "HTTP 415" in recs[0]["error"]


def test_bench_audio_missing_file(base_url: str, tmp_path: Path) -> None:
    audio_dir = tmp_path / "empty"
    audio_dir.mkdir()
    out = tmp_path / "missing.jsonl"
    r = bench(["--config", "audio", "--base-url", base_url, "--audio-dir", str(audio_dir),
               "--runs", "1", "--limit", "1", "--out", str(out)])
    assert r.returncode == 2
    _, recs = load(out)
    assert len(recs) == 1
    assert recs[0]["status"] == "error"
    assert "missing audio file" in recs[0]["error"]


def hand_audio_jsonl(path: Path, ids: list[str]) -> None:
    header = {"kind": "header", "config": "audio", "endpoint": "/api/ask-audio-stream",
              "input": "audio", "concurrency": 1, "runs": 1, "questions": len(ids)}
    lines = [header]
    for i, qid in enumerate(ids):
        lines.append({
            "kind": "record", "run": 0, "id": qid, "status": "ok", "hit": True,
            "transcript": "손으로 만든 전사", "total_ms": 900.0 + i, "first_audio_ms": 400.0 + i,
            "client_first_audio_ms": 420.0 + i, "sentence_count": 1, "audio_s": 2.0,
            "stages": {"stt_ms": 150.0, "retrieve_ms": 5.0, "llm_ms": 10.0, "tts_ms": 200.0},
        })
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")


def test_bench_extra_summary(base_url: str, tmp_path: Path) -> None:
    c1, c4, audio = tmp_path / "c1.jsonl", tmp_path / "c4.jsonl", tmp_path / "audio.jsonl"
    common = ["--config", "after", "--base-url", base_url, "--runs", "1", "--limit", "2"]
    assert bench([*common, "--concurrency", "1", "--out", str(c1)]).returncode == 0
    assert bench([*common, "--concurrency", "4", "--out", str(c4)]).returncode == 0
    hand_audio_jsonl(audio, first_ids(2))
    # before/after inputs for the main table: real runs, tiny
    before, after = tmp_path / "before.jsonl", tmp_path / "after.jsonl"
    assert bench(["--config", "before", "--base-url", base_url, "--runs", "1", "--limit", "2",
                  "--out", str(before)]).returncode == 0
    assert bench([*common, "--out", str(after)]).returncode == 0

    r = run_cmd(["./bench/summarize.sh", "--before", str(before), "--after", str(after),
                 "--c1", str(c1), "--c4", str(c4), "--audio", str(audio),
                 "--out-dir", str(tmp_path)])
    assert r.returncode == 0, r.stderr
    extra = (tmp_path / "summary-extra.md").read_text()
    assert extra.splitlines()[0] == EXTRA_HEADER
    assert not IP_RE.search(extra)
    assert re.search(r"\| 요청 수", extra)


def test_bench_extra_summary_mismatch(base_url: str, tmp_path: Path) -> None:
    c1, audio = tmp_path / "c1.jsonl", tmp_path / "audio.jsonl"
    common = ["--config", "after", "--base-url", base_url, "--runs", "1", "--limit", "2"]
    assert bench([*common, "--out", str(c1)]).returncode == 0
    hand_audio_jsonl(audio, first_ids(2))
    before, after = tmp_path / "before.jsonl", tmp_path / "after.jsonl"
    assert bench(["--config", "before", "--base-url", base_url, "--runs", "1", "--limit", "2",
                  "--out", str(before)]).returncode == 0
    assert bench([*common, "--out", str(after)]).returncode == 0
    base = ["./bench/summarize.sh", "--before", str(before), "--after", str(after),
            "--out-dir", str(tmp_path)]

    r = run_cmd([*base, "--c1", str(c1), "--c4", str(c1), "--audio", str(audio)])
    assert r.returncode == 1
    assert "--c4" in r.stderr
    assert not (tmp_path / "summary-extra.md").exists()

    r = run_cmd([*base, "--c1", str(c1)])
    assert r.returncode == 1
    assert not (tmp_path / "summary-extra.md").exists()
