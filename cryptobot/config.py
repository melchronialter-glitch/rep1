"""Environment-driven configuration. Single source of truth."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Postgres ----
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "cryptobot"
    postgres_password: str = "cryptobot"
    postgres_db: str = "cryptobot"

    # ---- Redis ----
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # ---- Anthropic ----
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_fast_model: str = "claude-haiku-4-5-20251001"

    # ---- Telegram outbound ----
    telegram_bot_token: str = ""
    telegram_chat_strict: str = ""
    telegram_chat_medium: str = ""
    telegram_chat_firehose: str = ""
    telegram_chat_macro: str = ""
    telegram_chat_dm: str = ""

    # ---- Logging ----
    log_level: str = "INFO"
    log_json: bool = False

    # ---- Computed ----
    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def telegram_chat_id(self, channel: str) -> str:
        """Return the chat ID for a logical channel name.

        channel ∈ {"strict", "medium", "firehose", "macro", "dm"}
        """
        mapping = {
            "strict": self.telegram_chat_strict,
            "medium": self.telegram_chat_medium,
            "firehose": self.telegram_chat_firehose,
            "macro": self.telegram_chat_macro,
            "dm": self.telegram_chat_dm,
        }
        chat_id = mapping.get(channel, "")
        if not chat_id:
            raise ValueError(f"No chat ID configured for channel '{channel}'")
        return chat_id


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
