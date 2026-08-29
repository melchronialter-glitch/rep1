"""Translator agent — detects non-English social posts and translates them.

Subscribes to ``social.tg.message``, ``social.x.tweet``, and
``social.reddit.post``. When a payload's ``text`` field contains a
significant proportion of CJK, Hangul, or Cyrillic characters (scripts
common in crypto communities: Chinese, Korean, Russian), it is translated via
Claude Haiku and re-published to the *same* topic with ``_translated: true``
added to the payload.

The ``_translated`` flag acts as a loop guard — the agent ignores payloads
that already carry it, preventing infinite translation cycles.

Translation is best-effort: any LLM error drops the message silently
(the original non-English payload was already published upstream).

Enabled/disabled via ``TRANSLATION_ENABLED`` (default: true).
"""

from __future__ import annotations

import asyncio
import unicodedata
from typing import Any

from cryptobot import llm
from cryptobot.bus import Event, get_bus
from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.topics import SOCIAL_REDDIT_POST, SOCIAL_TG_MESSAGE, SOCIAL_X_TWEET

log = get_logger(__name__)

WATCHED = [SOCIAL_TG_MESSAGE, SOCIAL_X_TWEET, SOCIAL_REDDIT_POST]

# Minimum fraction of non-ASCII chars that must be CJK/Hangul/Cyrillic
# before we bother translating.
_NON_ENGLISH_THRESHOLD = 0.15
_MIN_TEXT_LEN = 20

_TRANSLATE_SYSTEM = (
    "You are a translation assistant. Translate the following text to English. "
    "Output ONLY the English translation — no preamble, no explanation, no quotes."
)


def _non_english_fraction(text: str) -> float:
    """Return the fraction of characters that are CJK, Hangul, or Cyrillic."""
    if not text:
        return 0.0
    target = 0
    for ch in text:
        cat = unicodedata.category(ch)
        name = unicodedata.name(ch, "")
        if (
            cat.startswith("L")
            and (
                "CJK" in name
                or "HANGUL" in name
                or "CYRILLIC" in name
                or "HIRAGANA" in name
                or "KATAKANA" in name
            )
        ):
            target += 1
    return target / len(text)


def _needs_translation(text: str) -> bool:
    if not text or len(text) < _MIN_TEXT_LEN:
        return False
    return _non_english_fraction(text) >= _NON_ENGLISH_THRESHOLD


async def _translate(text: str) -> str | None:
    try:
        result = await llm.analyze(
            system=_TRANSLATE_SYSTEM,
            user=text[:2000],
            fast=True,
            json_response=False,
            max_tokens=800,
            temperature=0.0,
        )
        return (result.get("text") or "").strip() or None
    except Exception:
        log.exception("translator.llm.failed")
        return None


async def _handle_event(topic: str, event: Event) -> None:
    payload = event.payload or {}
    if payload.get("_translated"):
        return

    text_key = "text" if "text" in payload else ("body" if "body" in payload else None)
    if text_key is None:
        return
    text = payload.get(text_key) or ""
    if not _needs_translation(text):
        return

    translated = await _translate(text)
    if not translated:
        return

    bus = get_bus()
    new_payload: dict[str, Any] = {
        **payload,
        text_key: translated,
        "_original_text": text,
        "_translated": True,
    }
    await bus.publish(topic, new_payload, source="translator", persist=False)
    log.info("translator.translated", topic=topic, chars=len(text))


async def run_translator(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: translate non-English social messages via Claude Haiku."""
    settings = get_settings()
    if not settings.translation_enabled:
        log.info("translator.disabled", reason="TRANSLATION_ENABLED=false")
        return

    bus = get_bus()
    log.info("translator.started", watched=WATCHED)

    async for msg_id, topic, event in bus.subscribe(
        WATCHED, group="translator", consumer="translator-1"
    ):
        try:
            await _handle_event(topic, event)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("translator.error", id=event.id, topic=topic)
        finally:
            await bus.ack(topic, "translator", msg_id)
        if stop_event and stop_event.is_set():
            return

    log.info("translator.stopped")
