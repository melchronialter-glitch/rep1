"""Environment-driven configuration. Single source of truth."""

from __future__ import annotations

from functools import lru_cache

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

    # ---- Phase B: market data ----
    price_symbols: str = "btcusdt,ethusdt,solusdt,bnbusdt,xrpusdt,dogeusdt"
    price_move_threshold_pct: float = 3.0
    price_move_window_min: int = 60

    # ---- Phase B: news ----
    cryptopanic_api_key: str = ""
    news_api_key: str = ""

    # ---- Phase C: chain watchers ----
    helius_api_key: str = ""
    alchemy_api_key: str = ""
    bsc_ws_url: str = ""  # websocket RPC, e.g. QuickNode free tier
    pumpfun_min_initial_buy_sol: float = 1.0  # below → tier_hint "ignore"

    # ---- Phase B: email digests ----
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_user: str = ""
    email_smtp_pass: str = ""
    email_from: str = ""
    email_to: str = ""

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

    @property
    def price_symbol_list(self) -> list[str]:
        """``price_symbols`` parsed into a lowercase list (comma-separated env value)."""
        return [s.strip().lower() for s in self.price_symbols.split(",") if s.strip()]

    @property
    def email_configured(self) -> bool:
        return bool(self.email_smtp_host and self.email_from and self.email_to)

    @property
    def telegram_known_chat_ids(self) -> set[str]:
        """All configured chat IDs — inbound commands are accepted only from these."""
        return {
            cid
            for cid in (
                self.telegram_chat_strict,
                self.telegram_chat_medium,
                self.telegram_chat_firehose,
                self.telegram_chat_macro,
                self.telegram_chat_dm,
            )
            if cid
        }

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
