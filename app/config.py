from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    pipeline_mode: str = "stub"
    tts_backend: str = "stub"
    tts_voice: str = "F1"
    stt_backend: str = "stub"
    stt_model: str = "small"
    stt_beam_size: int = 1
    retriever_backend: str = "keyword"
    faq_path: Path = Path("data/faq/sample_faq.json")
    port: int = 8765
    llm_backend: str = "stub"
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen3.7-flash"
    llm_timeout_s: float = 8.0
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
