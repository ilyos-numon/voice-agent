from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.bm25 import BM25Retriever
from app.pipeline.runner import build_pipeline, build_retriever
from app.pipeline.stubs import KeywordRetriever

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "faq" / "sample_faq.json"


def test_default_retriever_backend_is_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RETRIEVER_BACKEND", raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.retriever_backend == "keyword"


def test_build_retriever_keyword() -> None:
    r = build_retriever(Settings(retriever_backend="keyword", faq_path=SAMPLE))
    assert isinstance(r, KeywordRetriever)


def test_build_retriever_bm25_from_sample_json() -> None:
    r = build_retriever(Settings(retriever_backend="bm25", faq_path=SAMPLE))
    assert isinstance(r, BM25Retriever)
    assert len(r.items) == 5
    hits = r.search("주민등록등본 떼려면 뭐 필요해요?")
    assert hits and hits[0].id == "faq-001"


def test_build_retriever_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown RETRIEVER_BACKEND: nope"):
        build_retriever(Settings(retriever_backend="nope", faq_path=SAMPLE))


def test_pipeline_bm25_sample_faq001() -> None:
    p = build_pipeline(
        Settings(retriever_backend="bm25", stt_backend="stub", tts_backend="stub", faq_path=SAMPLE)
    )
    r = p.run("주민등록등본 떼려면 뭐 필요해요?")
    assert r.source is not None
    assert r.source.id == "faq-001"
    assert set(r.timings) == {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "total_ms"}
