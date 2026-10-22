"""LLM_BACKEND=qwen + 키 없음 -> 외부 호출 없이 FAQ 원문 폴백. 자체 서버(8767)를 띄운다."""

import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.pipeline.stubs import FALLBACK_ANSWER

PORT = 8767
URL = f"http://localhost:{PORT}"
FAQ001_ANSWER = "주민등록등본은 본인 신분증만 있으면 발급됩니다. 수수료는 1통에 400원입니다."
QUESTION = "주민등록등본 떼려면 뭐 필요해요?"
ROOT = Path(__file__).resolve().parents[2]


def read_events(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name = None
    with httpx.stream("POST", f"{URL}/api/ask-stream", json={"text": text}, timeout=30) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: ") and name is not None:
                events.append((name, json.loads(line[len("data: "):])))
                name = None
    return events


@pytest.fixture(scope="module")
def server_log(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    log_path = tmp_path_factory.mktemp("llmfb") / "server.log"
    env = dict(os.environ)
    env.update(
        {
            "LLM_BACKEND": "qwen",
            "LLM_API_KEY": "",  # 환경변수가 .env보다 우선 -> 빈 키로 덮어씀
            "LLM_BASE_URL": "http://localhost:1/v1",  # 이중 차단: 닫힌 로컬 포트
            "PIPELINE_MODE": "stub",
            "TTS_BACKEND": "stub",
            "STT_BACKEND": "stub",
            "RETRIEVER_BACKEND": "keyword",
            "FAQ_PATH": "data/faq/sample_faq.json",
        }
    )
    with open(log_path, "wb") as f:
        proc = subprocess.Popen(
            ["uv", "run", "--no-sync", "uvicorn", "app.main:app",
             "--host", "localhost", "--port", str(PORT)],
            cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(60):
                if proc.poll() is not None:
                    pytest.fail(f"server exited: {log_path.read_text()[-500:]}")
                try:
                    if httpx.get(f"{URL}/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                pytest.fail("server not ready")
            yield log_path
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_stream_falls_back_to_faq_text(server_log: Path) -> None:
    events = read_events(QUESTION)
    names = [n for n, _ in events]
    audio = [d for n, d in events if n == "audio"]
    assert names == ["meta"] + ["audio"] * len(audio) + ["done"]
    assert len(audio) >= 1
    meta, done = events[0][1], events[-1][1]
    assert meta["source"]["id"] == "faq-001"
    assert meta["answer"] == FAQ001_ANSWER
    assert meta["sentence_count"] == len(audio) == done["sentence_count"]
    assert done["timings"]["llm_ms"] < 50  # 네트워크 호출이 없다는 근거


def test_ask_falls_back_to_faq_text(server_log: Path) -> None:
    r = httpx.post(f"{URL}/api/ask", json={"text": QUESTION}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == FAQ001_ANSWER
    assert body["source"]["id"] == "faq-001"
    assert body["timings"]["llm_ms"] < 50


def test_unknown_question_gets_fallback_phrase(server_log: Path) -> None:
    events = read_events("xyzzy")
    assert events[0][1]["source"] is None
    assert events[0][1]["answer"] == FALLBACK_ANSWER
    assert events[-1][0] == "done"


def test_server_log_has_no_external_access(server_log: Path) -> None:
    httpx.post(f"{URL}/api/ask", json={"text": QUESTION}, timeout=30)
    text = server_log.read_text().lower()
    for needle in ("dashscope", "aliyuncs", "localhost:1/", "urlerror", "connection refused"):
        assert needle not in text, needle
