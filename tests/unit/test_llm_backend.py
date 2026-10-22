import pytest

from app.config import Settings
from app.pipeline.llm_qwen import QwenLLM
from app.pipeline.runner import build_llm
from app.pipeline.stubs import TemplateLLM


def test_default_llm_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_BACKEND", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.llm_backend == "stub"
    assert s.llm_api_key == ""
    assert s.llm_base_url == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    assert s.llm_model == "qwen3.7-flash"
    assert s.llm_timeout_s == 8.0


def test_build_llm_stub() -> None:
    assert isinstance(build_llm(Settings(llm_backend="stub")), TemplateLLM)


def test_build_llm_qwen_without_key_falls_back() -> None:
    assert isinstance(build_llm(Settings(llm_backend="qwen", llm_api_key="")), TemplateLLM)


def test_build_llm_qwen_with_key() -> None:
    assert isinstance(build_llm(Settings(llm_backend="qwen", llm_api_key="x")), QwenLLM)


def test_build_llm_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown LLM_BACKEND: nope"):
        build_llm(Settings(llm_backend="nope"))
