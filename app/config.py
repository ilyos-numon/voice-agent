from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    pipeline_mode: str = "stub"
    tts_backend: str = "stub"
    tts_voice: str = "F1"
    faq_path: Path = Path("data/faq/sample_faq.json")
    port: int = 8765
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
