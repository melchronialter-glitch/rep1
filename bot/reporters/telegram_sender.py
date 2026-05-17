"""
Telegram report sender using python-telegram-bot.

Handles:
- Message splitting for Telegram's 4096-char limit
- Markdown parse mode
- Retry on transient errors
- Graceful failure without crashing the scheduler
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Telegram's maximum message length
TELEGRAM_MAX_LEN = 4096


class TelegramSender:
    """Async Telegram message sender."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._bot: Any = None  # lazy-initialised

    def _get_bot(self) -> Any:
        """Lazy-initialise the telegram.Bot instance."""
        if self._bot is None:
            try:
                from telegram import Bot  # type: ignore[import]
                self._bot = Bot(token=self._token)
            except ImportError:
                raise RuntimeError(
                    "python-telegram-bot is not installed. Run: pip install python-telegram-bot"
                )
        return self._bot

    async def send_message(
        self,
        text: str,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
    ) -> bool:
        """
        Send a (potentially long) message to Telegram.

        Automatically splits messages that exceed 4096 characters.
        Returns True if all parts were sent successfully.
        """
        from bot.reporters.formatter import split_for_telegram

        chunks = split_for_telegram(text, max_len=TELEGRAM_MAX_LEN)
        bot = self._get_bot()
        all_ok = True

        for i, chunk in enumerate(chunks):
            part_label = f"(part {i+1}/{len(chunks)})" if len(chunks) > 1 else ""
            message_text = f"{chunk}\n{part_label}" if part_label else chunk

            sent = await self._send_with_retry(
                bot=bot,
                text=message_text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
            if not sent:
                all_ok = False
                # Try to send as plain text (strip markdown)
                await self._send_with_retry(
                    bot=bot,
                    text=message_text,
                    parse_mode=None,  # plain text fallback
                    disable_web_page_preview=disable_web_page_preview,
                )

        return all_ok

    async def _send_with_retry(
        self,
        bot: Any,
        text: str,
        parse_mode: str | None,
        disable_web_page_preview: bool,
        max_retries: int = 3,
    ) -> bool:
        """Send a single chunk with exponential backoff retry."""
        for attempt in range(max_retries):
            try:
                kwargs: dict[str, Any] = {
                    "chat_id": self._chat_id,
                    "text": text,
                    "disable_web_page_preview": disable_web_page_preview,
                }
                if parse_mode:
                    kwargs["parse_mode"] = parse_mode

                await bot.send_message(**kwargs)
                logger.debug("Telegram message sent (attempt %d)", attempt + 1)
                return True

            except Exception as exc:
                exc_str = str(exc)

                # Non-retryable errors
                if "Unauthorized" in exc_str or "chat not found" in exc_str.lower():
                    logger.error("Telegram auth/chat error (non-retryable): %s", exc)
                    return False

                # Markdown parse error – caller will retry with plain text
                if "can't parse entities" in exc_str.lower() or "Bad Request" in exc_str:
                    logger.warning("Telegram parse error (will retry without Markdown): %s", exc)
                    return False

                # Rate limit – respect retry_after
                if "Flood control" in exc_str or "Too Many Requests" in exc_str:
                    retry_after = 30
                    try:
                        # python-telegram-bot raises TelegramError with retry_after attribute
                        retry_after = getattr(exc, "retry_after", 30) or 30
                    except Exception:
                        pass
                    logger.warning("Telegram rate limit; sleeping %ds", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                # Generic transient error
                wait = 2 ** attempt
                logger.warning(
                    "Telegram send failed (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1, max_retries, wait, exc,
                )
                await asyncio.sleep(wait)

        logger.error("Telegram send failed after %d attempts", max_retries)
        return False

    async def send_report(self, markdown_text: str) -> bool:
        """High-level: send a pre-formatted report."""
        return await self.send_message(markdown_text, parse_mode="Markdown")

    async def send_alert(self, alert_text: str) -> bool:
        """High-level: send an urgent price alert."""
        return await self.send_message(alert_text, parse_mode="Markdown")

    async def ping(self) -> bool:
        """Test the connection by getting bot info."""
        try:
            bot = self._get_bot()
            me = await bot.get_me()
            logger.info("Telegram bot connected: @%s", me.username)
            return True
        except Exception as exc:
            logger.error("Telegram ping failed: %s", exc)
            return False
