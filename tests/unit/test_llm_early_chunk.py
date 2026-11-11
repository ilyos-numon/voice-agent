import pytest

from app.config import Settings
from app.pipeline.llm_qwen import QwenLLM
from tests.unit.test_llm_qwen import CTX, FakeOpener, _sse

ANSWER = ["네, 주민등록등본은 ", "본인 신분증만 ", "있으면 발급받을 ", "수 있습니다."]


def _llm(op: FakeOpener, **kw: bool) -> QwenLLM:
    return QwenLLM(api_key="k", base_url="http://fake/v1", model="m", timeout_s=3.0, opener=op, **kw)


def test_early_chunk_off_yields_one_sentence() -> None:
    out = list(_llm(FakeOpener(_sse(ANSWER)), early_chunk=False).stream_sentences("q", CTX))
    assert out == ["네, 주민등록등본은 본인 신분증만 있으면 발급받을 수 있습니다."]


def test_early_chunk_off_still_splits_at_sentence_end() -> None:
    op = FakeOpener(_sse(["여권 재발급은 민원실에서, ", "하십시오. 수수료는 ", "5만원입니다."]))
    out = list(_llm(op, early_chunk=False).stream_sentences("q", CTX))
    assert out == ["여권 재발급은 민원실에서, 하십시오.", "수수료는 5만원입니다."]


def test_early_chunk_default_on_splits_first_chunk() -> None:
    out = list(_llm(FakeOpener(_sse(ANSWER))).stream_sentences("q", CTX))
    assert len(out) == 2


def test_setting_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_EARLY_CHUNK", raising=False)
    assert Settings(_env_file=None).llm_early_chunk is True  # type: ignore[call-arg]
    monkeypatch.setenv("LLM_EARLY_CHUNK", "false")
    assert Settings(_env_file=None).llm_early_chunk is False  # type: ignore[call-arg]
