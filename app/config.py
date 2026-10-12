"""Application settings, loaded from environment variables and the .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/nl_db_agent"
    database_pool_size: int = 5
    database_max_overflow: int = 10
    # Restricted login used to run LLM-written SQL. It connects to the same
    # database as database_url but can only SELECT from the business tables.
    agent_db_user: str = "agent_readonly"
    agent_db_password: str = "agent_readonly"

    # Query execution
    max_query_rows: int = 1000
    query_timeout_seconds: int = 30
    max_retries: int = 3

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
