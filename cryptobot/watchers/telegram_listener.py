"""Telegram group listener (Telethon, user account).

Logs in as *you* (not a bot) and listens to every dialog the account is in —
groups, channels, DMs. Each new message is published to ``social.tg.message``
with ``persist=False`` on the bus archive (group chatter is high-volume
noise), **except** messages containing a contract address: those are
archived and additionally stored in the ``tg_messages`` table.

Requires ``TELEGRAM_USER_API_ID`` / ``TELEGRAM_USER_API_HASH`` (from
https://my.telegram.org) — the watcher disables itself with a log line when
unset. The first login is interactive (Telegram sends a code): run
``cryptobot tg-login`` once; after that the file session at
``TELEGRAM_SESSION_PATH`` is reused silently.

``TG_WATCH_CHATS`` (comma-separated chat IDs and/or titles) narrows listening
to those chats; empty means all chats.
"""

from __future__ import annotations

import asyncio
import pathlib
import uuid
from typing import Any

from telethon import TelegramClient, events

from cryptobot.agents.tg_call_parser import find_addresses
from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.topics import SOCIAL_TG_MESSAGE

log = get_logger(__name__)

TEXT_MAX_LEN = 2000


def _sender_display_name(sender: Any) -> str:
    """Best-effort human-readable name for a Telethon sender entity."""
    if sender is None:
        return ""
    parts = [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]
    name = " ".join(p for p in parts if p)
    return name or getattr(sender, "username", None) or getattr(sender, "title", "") or ""


def _chat_matches(watch: set[str], chat_id: str, chat_title: str) -> bool:
    """True when the chat is on the watch list (or the list is empty = all)."""
    if not watch:
        return True
    return chat_id.lower() in watch or chat_title.lower() in watch


async def _persist_message(payload: dict[str, Any], addresses: list[str]) -> None:
    try:
        await execute(
            "INSERT INTO tg_messages (id, chat_id, chat_title, sender_id, "
            "sender_name, text, addresses) VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb)",
            str(uuid.uuid4()),
            str(payload["chat_id"]),
            payload["chat_title"],
            str(payload["sender_id"]),
            payload["sender_name"],
            payload["text"],
            addresses,
        )
    except Exception:
        log.exception("telegram_listener.persist.failed", chat=payload["chat_title"])


async def _handle_new_message(event: events.NewMessage.Event, watch: set[str]) -> None:
    text = (event.raw_text or "")[:TEXT_MAX_LEN]
    if not text:
        return

    chat = await event.get_chat()
    chat_id = str(event.chat_id or "")
    chat_title = getattr(chat, "title", None) or _sender_display_name(chat)
    if not _chat_matches(watch, chat_id, chat_title):
        return

    sender = await event.get_sender()
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "chat_title": chat_title,
        "sender_id": str(event.sender_id or ""),
        "sender_name": _sender_display_name(sender),
        "text": text,
        "ts": event.message.date.isoformat() if event.message.date else None,
        "has_media": event.message.media is not None,
    }

    # Raw group chatter is not archived; messages carrying a contract address
    # are — and also land in tg_messages for caller/coin joins.
    addresses = [a for a, _chain in find_addresses(text)]
    if addresses:
        await _persist_message(payload, addresses)

    await get_bus().publish(
        SOCIAL_TG_MESSAGE,
        payload,
        source="telegram_listener",
        persist=bool(addresses),
    )
    log.debug(
        "telegram_listener.message",
        chat=chat_title,
        sender=payload["sender_name"],
        addresses=len(addresses),
    )


async def run_telegram_listener(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: connect the user session and stream all new messages."""
    settings = get_settings()
    if not settings.telegram_user_configured:
        log.info(
            "telegram_listener.disabled",
            reason="TELEGRAM_USER_API_ID / TELEGRAM_USER_API_HASH not set",
        )
        return

    session_path = pathlib.Path(settings.telegram_session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        str(session_path),
        int(settings.telegram_user_api_id),
        settings.telegram_user_api_hash,
    )

    await client.connect()
    try:
        if not await client.is_user_authorized():
            log.warning(
                "telegram_listener.not_authorized",
                hint="run `cryptobot tg-login` once to authorize this session interactively",
                session=str(session_path),
            )
            return

        watch = settings.tg_watch_chat_set

        @client.on(events.NewMessage())
        async def _on_message(event: events.NewMessage.Event) -> None:
            try:
                await _handle_new_message(event, watch)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("telegram_listener.message.error")

        me = await client.get_me()
        log.info(
            "telegram_listener.started",
            account=getattr(me, "username", None) or getattr(me, "phone", "?"),
            watch_chats=sorted(watch) or "all",
        )

        if stop_event is not None:
            await stop_event.wait()
        else:
            await client.run_until_disconnected()
    finally:
        await client.disconnect()
        log.info("telegram_listener.stopped")
