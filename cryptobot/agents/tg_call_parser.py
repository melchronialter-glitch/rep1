"""TG call parser — detects coin shills in Telegram group messages.

Subscribes to ``social.tg.message``. A message is a **call** when it contains
a contract address (EVM ``0x…`` or Solana base58) combined with either
buy-language ("ape", "100x", "send it", …) or a ``$TICKER`` mention.

For every detected call the agent:

- upserts the caller into ``tg_callers`` (raw shill volume; performance
  scoring lands in a later phase)
- persists the call to ``tg_calls``
- publishes ``social.tg.call`` with the caller's historical call count
- routes a copy to ``signal.alert.medium`` when the chat is on the curated
  ``TG_WATCH_CHATS`` list (a watched group calling something *is* signal),
  otherwise to the firehose

The detection itself is the pure function :func:`extract_call` — unit-tested,
no I/O.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute, fetchrow
from cryptobot.intel.coin_intel import looks_like_evm_address, looks_like_solana_address
from cryptobot.logging import get_logger
from cryptobot.topics import (
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MEDIUM,
    SOCIAL_TG_CALL,
    SOCIAL_TG_MESSAGE,
)

log = get_logger(__name__)

# $TICKER mentions: $PEPE, $wif — 2-10 chars, must start with a letter.
TICKER_RE = re.compile(r"\$[A-Za-z][A-Za-z0-9]{1,9}\b")

# Buy-language: classic degen call vocabulary, case-insensitive.
BUY_LANGUAGE_RE = re.compile(
    r"\b(?:buy|ape|gem|moon(?:ing|shot)?|100x|10x|lfg|send\s+it|pump|call|entry|accumulate)\b",
    re.IGNORECASE,
)

_PUNCT_STRIP = ".,;:!?()[]{}<>\"'`“”‘’…"


def find_addresses(text: str) -> list[tuple[str, str]]:
    """Find contract addresses in free text.

    Splits on whitespace, strips edge punctuation, and checks each token
    against the EVM / Solana regexes from :mod:`cryptobot.intel.coin_intel`.
    Returns de-duplicated ``(address, chain_guess)`` tuples in text order,
    where ``chain_guess`` is ``"evm"`` or ``"solana"``.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in text.split():
        token = raw.strip(_PUNCT_STRIP)
        if not token or token in seen:
            continue
        if looks_like_evm_address(token):
            found.append((token, "evm"))
            seen.add(token)
        elif looks_like_solana_address(token):
            found.append((token, "solana"))
            seen.add(token)
    return found


def extract_call(text: str) -> dict[str, Any] | None:
    """Detect a coin call in a message. Pure — no I/O.

    A call is a contract address plus either buy-language or a ``$TICKER``
    mention. Returns ``{address, chain_guess, tickers, buy_language}`` for the
    first address found, or ``None`` when the message is not a call.
    """
    if not text:
        return None
    addresses = find_addresses(text)
    if not addresses:
        return None
    tickers = TICKER_RE.findall(text)
    buy_language = bool(BUY_LANGUAGE_RE.search(text))
    if not buy_language and not tickers:
        return None
    address, chain_guess = addresses[0]
    return {
        "address": address,
        "chain_guess": chain_guess,
        "tickers": tickers,
        "buy_language": buy_language,
    }


async def _bump_caller(sender_id: str, sender_name: str) -> int:
    """Upsert the caller row; return their total call count (best-effort)."""
    try:
        row = await fetchrow(
            "INSERT INTO tg_callers (sender_id, sender_name) VALUES ($1, $2) "
            "ON CONFLICT (sender_id) DO UPDATE SET "
            "calls_count = tg_callers.calls_count + 1, "
            "sender_name = EXCLUDED.sender_name, last_seen = NOW() "
            "RETURNING calls_count",
            sender_id,
            sender_name,
        )
        return int(row["calls_count"]) if row else 1
    except Exception:
        log.exception("tg_call_parser.caller_upsert.failed", sender_id=sender_id)
        return 1


async def _persist_call(call: dict[str, Any], payload: dict[str, Any]) -> None:
    try:
        await execute(
            "INSERT INTO tg_calls (id, address, chain_guess, tickers, chat_title, "
            "sender_id, sender_name, buy_language) "
            "VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6, $7, $8)",
            str(uuid.uuid4()),
            call["address"],
            call["chain_guess"],
            call["tickers"],
            payload.get("chat_title"),
            str(payload.get("sender_id") or ""),
            payload.get("sender_name"),
            call["buy_language"],
        )
    except Exception:
        log.exception("tg_call_parser.persist.failed", address=call["address"])


async def _handle_message(payload: dict[str, Any]) -> None:
    call = extract_call(payload.get("text") or "")
    if call is None:
        return

    settings = get_settings()
    bus = get_bus()
    sender_id = str(payload.get("sender_id") or "")
    sender_name = str(payload.get("sender_name") or "")
    calls_count = await _bump_caller(sender_id, sender_name) if sender_id else 0

    call_payload: dict[str, Any] = {
        **call,
        "chat_title": payload.get("chat_title"),
        "sender_name": sender_name,
        "sender_id": sender_id,
        "caller_calls_count": calls_count,
    }
    await _persist_call(call, payload)
    await bus.publish(SOCIAL_TG_CALL, call_payload, source="tg_call_parser")

    # A curated (watched) group calling something is signal; random groups
    # go to the firehose.
    watch = settings.tg_watch_chat_set
    chat_keys = {
        str(payload.get("chat_id") or "").lower(),
        str(payload.get("chat_title") or "").lower(),
    }
    target = SIGNAL_ALERT_MEDIUM if watch & chat_keys else SIGNAL_ALERT_FIREHOSE
    await bus.publish(
        target,
        {
            "title": f"TG call: {call['address'][:12]}… in {payload.get('chat_title')}",
            **call_payload,
        },
        source="tg_call_parser",
    )
    log.info(
        "tg_call_parser.call_detected",
        address=call["address"],
        chain=call["chain_guess"],
        chat=payload.get("chat_title"),
        caller_calls_count=calls_count,
        routed_to=target,
    )


async def run_tg_call_parser(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: consume social.tg.message, detect calls, score callers."""
    bus = get_bus()
    log.info("tg_call_parser.started")
    async for msg_id, topic, event in bus.subscribe(
        [SOCIAL_TG_MESSAGE], group="tg_call_parser", consumer="tg-call-parser-1"
    ):
        try:
            await _handle_message(event.payload or {})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("tg_call_parser.error", id=event.id)
        finally:
            await bus.ack(topic, "tg_call_parser", msg_id)
        if stop_event and stop_event.is_set():
            return
