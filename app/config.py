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
    agent_ttl_hours: float = 24.0
    max_agents: int = 200
    max_text_chars: int = 20000
    max_csv_rows: int = 300
    max_csv_chars: int = 100000
    session_max_questions: int = 30
    turn_concurrency: int = 2
    turn_queue_max: int = 8
    scorecard_queue_max: int = 4
    presets_dir: Path = Path("data/presets")
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
