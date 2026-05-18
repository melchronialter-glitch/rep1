"""Outbound Telegram bot.

Talks to the Bot API over HTTPS directly — no heavy SDK. Handles the four
alert channels (strict / medium / firehose / macro) plus DM, message
splitting at 4096 chars, and exponential backoff on transient errors.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx

from cryptobot.bus import Event, get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.reporters.formatter import render_alert, to_markdown_v2
from cryptobot.topics import (
    ALERT_TOPIC_TO_CHANNEL,
    SIGNAL_ALERT_DM,
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MACRO,
    SIGNAL_ALERT_MEDIUM,
    SIGNAL_ALERT_STRICT,
)

log = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"
MAX_MSG_LEN = 4000  # leave headroom under the 4096 limit


class TelegramOut:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        self._token = settings.telegram_bot_token
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=f"{TELEGRAM_API}/bot{self._token}",
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def send(
        self,
        channel: str,
        text: str,
        *,
        parse_mode: str = "MarkdownV2",
        disable_web_page_preview: bool = True,
    ) -> bool:
        chat_id = self._settings.telegram_chat_id(channel)
        ok_all = True
        for chunk in _split(text, MAX_MSG_LEN):
            ok = await self._send_chunk(
                chat_id, chunk, parse_mode, disable_web_page_preview
            )
            ok_all = ok_all and ok
        return ok_all

    async def _send_chunk(
        self,
        chat_id: str,
        text: str,
        parse_mode: str,
        disable_preview: bool,
    ) -> bool:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        for attempt in range(4):
            try:
                resp = await self._client.post("/sendMessage", json=payload)
            except httpx.HTTPError as e:
                log.warning("tg.send.network_error", err=str(e), attempt=attempt)
                await asyncio.sleep(2**attempt)
                continue

            if resp.status_code == 200:
                return True

            try:
                data = resp.json()
            except json.JSONDecodeError:
                data = {"raw": resp.text}

            # Parse errors: retry once in plain text (no MarkdownV2)
            if resp.status_code == 400 and parse_mode and "parse" in str(data).lower():
                log.warning("tg.send.parse_fallback", detail=data)
                payload.pop("parse_mode", None)
                continue

            # Flood control
            if resp.status_code == 429:
                retry_after = int(
                    data.get("parameters", {}).get("retry_after", 2**attempt)
                )
                log.warning("tg.send.flood", retry_after=retry_after)
                await asyncio.sleep(retry_after)
                continue

            log.error("tg.send.failed", status=resp.status_code, body=data)
            return False
        return False


def _split(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for paragraph in text.split("\n\n"):
        if not paragraph:
            continue
        block = paragraph + "\n\n"
        if len(buf) + len(block) > limit and buf:
            parts.append(buf.rstrip())
            buf = block
        elif len(block) > limit:
            # very long single paragraph — hard split
            for i in range(0, len(block), limit):
                parts.append(block[i : i + limit])
            buf = ""
        else:
            buf += block
    if buf.strip():
        parts.append(buf.rstrip())
    return parts


# ---- bus subscriber ------------------------------------------------------

ALERT_TOPICS = [
    SIGNAL_ALERT_STRICT,
    SIGNAL_ALERT_MEDIUM,
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MACRO,
    SIGNAL_ALERT_DM,
]


async def run_alert_sender(stop_event: asyncio.Event | None = None) -> None:
    """Subscribe to signal.alert.* and post to the right Telegram channel."""
    bus = get_bus()
    sender = TelegramOut()
    log.info("tg_out.started", topics=ALERT_TOPICS)

    try:
        async for msg_id, topic, event in bus.subscribe(
            ALERT_TOPICS, group="telegram_out", consumer="tg-sender-1"
        ):
            channel = ALERT_TOPIC_TO_CHANNEL.get(topic)
            if not channel:
                log.warning("tg_out.unknown_topic", topic=topic)
                await bus.ack(topic, "telegram_out", msg_id)
                continue
            try:
                rendered = render_alert(event)
                md = to_markdown_v2(rendered["title"], rendered["body"])
                ok = await sender.send(channel, md)
                await _record_alert(
                    event=event,
                    channel=channel,
                    title=rendered["title"],
                    body=rendered["body"],
                    delivered=ok,
                    error=None if ok else "telegram_send_failed",
                )
            except ValueError as e:
                log.warning("tg_out.channel_not_configured", channel=channel, err=str(e))
            except Exception as e:
                log.exception("tg_out.send_error", topic=topic)
                await _record_alert(
                    event=event,
                    channel=channel,
                    title=event.topic,
                    body=str(event.payload),
                    delivered=False,
                    error=str(e),
                )
            finally:
                await bus.ack(topic, "telegram_out", msg_id)
            if stop_event and stop_event.is_set():
                break
    finally:
        await sender.close()


async def _record_alert(
    *,
    event: Event,
    channel: str,
    title: str,
    body: str,
    delivered: bool,
    error: str | None,
) -> None:
    try:
        await execute(
            """
            INSERT INTO alerts (id, event_id, channel, tier, title, body, delivered, error)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8)
            """,
            str(uuid.uuid4()),
            event.id,
            channel,
            channel,
            title,
            body,
            delivered,
            error,
        )
    except Exception:
        log.exception("tg_out.archive_failed", event_id=event.id)
