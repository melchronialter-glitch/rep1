"""
Configuration: loads and validates all environment variables.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class Config:
    # --- Anthropic ---
    anthropic_api_key: str

    # --- Telegram ---
    telegram_bot_token: str
    telegram_chat_id: str

    # --- Email ---
    email_smtp_host: str
    email_smtp_port: int
    email_smtp_user: str
    email_smtp_pass: str
    email_from: str
    email_to: str

    # --- Data sources ---
    cryptopanic_api_key: str
    news_api_key: str
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str

    # --- Optional / defaulted ---
    log_level: str = "INFO"
    db_path: str = "data/crypto_bot.db"
    price_alert_threshold: float = 5.0  # percent

    # Derived (not from env)
    db_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.db_dir = Path(self.db_path).parent
        self.db_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "Config":
        """Load config from environment, optionally from a .env file."""
        if env_file:
            load_dotenv(env_file, override=False)

        missing: list[str] = []

        def req(key: str) -> str:
            val = os.getenv(key, "").strip()
            if not val:
                missing.append(key)
            return val

        def opt(key: str, default: str = "") -> str:
            return os.getenv(key, default).strip()

        cfg = cls(
            anthropic_api_key=req("ANTHROPIC_API_KEY"),
            telegram_bot_token=req("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=req("TELEGRAM_CHAT_ID"),
            email_smtp_host=req("EMAIL_SMTP_HOST"),
            email_smtp_port=int(opt("EMAIL_SMTP_PORT", "587") or "587"),
            email_smtp_user=req("EMAIL_SMTP_USER"),
            email_smtp_pass=req("EMAIL_SMTP_PASS"),
            email_from=req("EMAIL_FROM"),
            email_to=req("EMAIL_TO"),
            cryptopanic_api_key=req("CRYPTOPANIC_API_KEY"),
            news_api_key=req("NEWS_API_KEY"),
            reddit_client_id=req("REDDIT_CLIENT_ID"),
            reddit_client_secret=req("REDDIT_CLIENT_SECRET"),
            reddit_user_agent=opt("REDDIT_USER_AGENT", "CryptoBot/1.0"),
            log_level=opt("LOG_LEVEL", "INFO").upper(),
            db_path=opt("DB_PATH", "data/crypto_bot.db"),
            price_alert_threshold=float(opt("PRICE_ALERT_THRESHOLD", "5.0") or "5.0"),
        )

        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Copy .env.example to .env and fill in the values."
            )

        logging.basicConfig(
            level=getattr(logging, cfg.log_level, logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        logger.info("Config loaded successfully (log_level=%s)", cfg.log_level)
        return cfg
