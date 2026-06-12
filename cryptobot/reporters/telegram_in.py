"""Inbound Telegram command listener.

Long-polls the Bot API ``getUpdates`` endpoint (offset tracking, 30s timeout)
over plain HTTPS — same no-SDK approach as :mod:`telegram_out`. Only messages
from configured chat IDs are accepted; strangers are silently ignored.

Commands:

- ``/analyze <symbol|address>`` → publish ``intel.user_query`` (type analyze)
- ``/rugcheck <address>``       → publish ``intel.user_query`` (type rugcheck)
- ``/status``                   → reply with 24h event/alert counts
- ``/help``                     → static usage text

Analyze/rugcheck get an immediate "working on it…" ack; the coin analyst
agent replies asynchronously via ``signal.alert.dm`` with ``reply_to_chat_id``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import fetch, fetchrow
from cryptobot.logging import get_logger
from cryptobot.topics import INTEL_USER_QUERY

log = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"
POLL_TIMEOUT_S = 30
MAX_BACKOFF_S = 60

HELP_TEXT = (
    "CryptoBot commands:\n"
    "/analyze <symbol|address> — full coin deep-dive\n"
    "/rugcheck <address> — token safety report\n"
    "/status — 24h event and alert counts\n"
    "/help — this text"
)


async def _reply(client: httpx.AsyncClient, chat_id: str | int, text: str) -> None:
    """Best-effort plain-text reply (no MarkdownV2 — keep inbound acks simple)."""
    try:
        resp = await client.post(
            "/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        if resp.status_code != 200:
            log.warning("tg_in.reply.failed", status=resp.status_code, body=resp.text[:200])
    except httpx.HTTPError as e:
        log.warning("tg_in.reply.network_error", err=str(e))


async def _status_text() -> str:
    """24h counts from the events and alerts tables."""
    try:
        ev = await fetchrow(
            "SELECT COUNT(*) AS n FROM events WHERE ts > NOW() - INTERVAL '24 hours'"
        )
        rows = await fetch(
            "SELECT channel, COUNT(*) AS n FROM alerts "
            "WHERE sent_at > NOW() - INTERVAL '24 hours' "
            "GROUP BY channel ORDER BY n DESC"
        )
    except Exception as e:
        log.exception("tg_in.status.query_failed")
        return f"status query failed: {e}"
    lines = [f"Last 24h: {ev['n'] if ev else 0} events"]
    if rows:
        lines.append("Alerts by channel:")
        lines.extend(f"  {r['channel']}: {r['n']}" for r in rows)
    else:
        lines.append("Alerts by channel: none")
    return "\n".join(lines)


async def _handle_command(
    client: httpx.AsyncClient, chat_id: str, text: str
) -> None:
    bus = get_bus()
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower().split("@", 1)[0]  # strip @botname suffix
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/help" or cmd == "/start":
        await _reply(client, chat_id, HELP_TEXT)
    elif cmd == "/status":
        await _reply(client, chat_id, await _status_text())
    elif cmd in ("/analyze", "/rugcheck"):
        if not arg:
            await _reply(client, chat_id, f"usage: {cmd} <symbol|address>")
            return
        query_type = cmd.lstrip("/")
        await _reply(client, chat_id, f"working on it… ({query_type} {arg})")
        await bus.publish(
            INTEL_USER_QUERY,
            {"type": query_type, "query": arg, "reply_to_chat_id": chat_id},
            source="telegram_in",
        )
        log.info("tg_in.query_published", type=query_type, query=arg, chat_id=chat_id)
    else:
        log.debug("tg_in.unknown_command", cmd=cmd)


def _extract_message(update: dict[str, Any]) -> tuple[str, str] | None:
    """Return (chat_id, text) from an update, or None if not a text message."""
    msg = update.get("message") or update.get("channel_post")
    if not msg:
        return None
    text = msg.get("text")
    chat_id = (msg.get("chat") or {}).get("id")
    if not text or chat_id is None:
        return None
    return str(chat_id), text


async def run_telegram_in(stop_event: asyncio.Event | None = None) -> None:
    """Long-poll getUpdates forever. Never crashes; backs off on errors."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.info("tg_in.disabled", reason="no bot token")
        return
    allowed = settings.telegram_known_chat_ids
    if not allowed:
        log.info("tg_in.disabled", reason="no chat ids configured")
        return

    offset = 0
    backoff = 1.0
    log.info("tg_in.started", allowed_chats=len(allowed))

    async with httpx.AsyncClient(
        base_url=f"{TELEGRAM_API}/bot{settings.telegram_bot_token}",
        timeout=httpx.Timeout(POLL_TIMEOUT_S + 10, connect=5.0),
    ) as client:
        while not (stop_event and stop_event.is_set()):
            try:
                resp = await client.get(
                    "/getUpdates",
                    params={
                        "offset": offset,
                        "timeout": POLL_TIMEOUT_S,
                        "allowed_updates": '["message"]',
                    },
                )
                resp.raise_for_status()
                updates = resp.json().get("result") or []
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("tg_in.poll.error", err=str(e), retry_in_s=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue

            for update in updates:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                extracted = _extract_message(update)
                if extracted is None:
                    continue
                chat_id, text = extracted
                if chat_id not in allowed:
                    log.debug("tg_in.ignored_stranger", chat_id=chat_id)
                    continue
                if not text.startswith("/"):
                    continue
                try:
                    await _handle_command(client, chat_id, text)
                except Exception:
                    log.exception("tg_in.command_error", text=text[:100])
