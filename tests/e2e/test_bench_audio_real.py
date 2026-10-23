from pathlib import Path

from .test_bench import load, run_cmd


def test_bench_audio_real_stt(base_url: str, tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    r = run_cmd(["uv", "run", "--no-sync", "python", "bench/make_audio.py", "--limit", "2",
                 "--out-dir", str(audio_dir)])
    assert r.returncode == 0, r.stderr
    assert "wrote 2 files" in r.stdout.splitlines()[-1]

    out = tmp_path / "audio.jsonl"
    r = run_cmd(["./bench/run.sh", "--config", "audio", "--base-url", base_url,
                 "--audio-dir", str(audio_dir), "--runs", "1", "--limit", "2",
                 "--out", str(out)])
    assert r.returncode == 0, r.stderr
    header, recs = load(out)
    assert header["input"] == "audio"
    assert len(recs) == 2
    for x in recs:
        assert x["status"] == "ok"
        assert x["stages"]["stt_ms"] > 0
        assert x["transcript"]
    faq1 = [x for x in recs if x["id"] == "faq-001"]
    assert faq1 and "등본" in faq1[0]["transcript"]
