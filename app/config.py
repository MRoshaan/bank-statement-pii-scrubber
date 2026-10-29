from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://pjbank:pjbank_dev_password@localhost:5432/pjbank"
    test_database_url: str = "postgresql+psycopg://pjbank:pjbank_dev_password@localhost:5432/pjbank_test"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "openai/gpt-oss-20b"
    max_file_mb: int = 20
    max_total_mb: int = 50
    max_files: int = 50
    llm_timeout_seconds: int = 60
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2400
    chat_history_turns: int = 6

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()
