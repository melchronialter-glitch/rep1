"""Digest agent — daily summary at 07:00 UTC.

A simple asyncio loop (no scheduler dependency) wakes once a minute and fires
when the clock crosses 07:00 UTC. The digest pulls the last 24 hours of
activity from Postgres — alert counts by channel, top event topics, every
strict alert, and macro alerts — feeds it to Sonnet, and delivers the
resulting markdown to ``signal.alert.dm`` plus email (if SMTP is configured).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from cryptobot import llm
from cryptobot.bus import get_bus
from cryptobot.db import fetch
from cryptobot.logging import get_logger
from cryptobot.reporters.email_out import send_email
from cryptobot.topics import SIGNAL_ALERT_DM

log = get_logger(__name__)

DIGEST_HOUR_UTC = 7
CHECK_INTERVAL_S = 60

DIGEST_SYSTEM = """\
You are the daily-digest writer for a crypto intelligence bot. You receive a
JSON summary of the last 24 hours: alert counts per channel, the most active
event topics, every strict (high-priority) alert, and macro alerts.

Write a concise daily digest in clean markdown suitable for Telegram and
email:

*Headline* — one sentence capturing the day's theme.
*Market & alerts* — what moved, what fired, anything unusual in the volumes.
*High-priority items* — bullet recap of strict alerts (skip if none).
*Macro* — bullet recap of macro alerts (skip if none).
*Bottom line* — one or two sentences of takeaway.

Be specific, mention symbols and numbers from the data. If the day was quiet,
say so plainly — never invent activity. Keep it under 400 words. Plain
markdown only (*bold*, bullets), no tables, no code fences."""


async def _collect_last_24h() -> dict[str, Any]:
    """Pull the digest source data from Postgres. Each query is best-effort."""
    data: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat()}
    try:
        rows = await fetch(
            "SELECT channel, COUNT(*) AS n FROM alerts "
            "WHERE sent_at > NOW() - INTERVAL '24 hours' GROUP BY channel"
        )
        data["alert_counts_by_channel"] = {r["channel"]: r["n"] for r in rows}
    except Exception:
        log.exception("digest.query_failed", query="alert_counts")
        data["alert_counts_by_channel"] = {}
    try:
        rows = await fetch(
            "SELECT topic, COUNT(*) AS n FROM events "
            "WHERE ts > NOW() - INTERVAL '24 hours' "
            "GROUP BY topic ORDER BY n DESC LIMIT 15"
        )
        data["top_event_topics"] = [{"topic": r["topic"], "count": r["n"]} for r in rows]
    except Exception:
        log.exception("digest.query_failed", query="top_topics")
        data["top_event_topics"] = []
    try:
        rows = await fetch(
            "SELECT title, body, sent_at FROM alerts "
            "WHERE channel = 'strict' AND sent_at > NOW() - INTERVAL '24 hours' "
            "ORDER BY sent_at DESC LIMIT 50"
        )
        data["strict_alerts"] = [
            {"title": r["title"], "body": r["body"][:300], "sent_at": r["sent_at"].isoformat()}
            for r in rows
        ]
    except Exception:
        log.exception("digest.query_failed", query="strict_alerts")
        data["strict_alerts"] = []
    try:
        rows = await fetch(
            "SELECT title, body, sent_at FROM alerts "
            "WHERE channel = 'macro' AND sent_at > NOW() - INTERVAL '24 hours' "
            "ORDER BY sent_at DESC LIMIT 50"
        )
        data["macro_alerts"] = [
            {"title": r["title"], "body": r["body"][:300], "sent_at": r["sent_at"].isoformat()}
            for r in rows
        ]
    except Exception:
        log.exception("digest.query_failed", query="macro_alerts")
        data["macro_alerts"] = []
    return data


async def build_digest() -> str:
    """Collect the data and run the Sonnet digest. Returns markdown."""
    data = await _collect_last_24h()
    result = await llm.analyze(
        system=DIGEST_SYSTEM,
        user=json.dumps(data, separators=(",", ":"), default=str),
        fast=False,
        max_tokens=2048,
    )
    return result["text"] or "Digest produced no output."


async def send_digest() -> None:
    """Build the daily digest and deliver it to Telegram DM + email."""
    bus = get_bus()
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        md = await build_digest()
    except Exception:
        log.exception("digest.build_failed")
        return
    try:
        await bus.publish(
            SIGNAL_ALERT_DM,
            {"title": f"Daily digest — {date_str}", "summary": md},
            source="digest",
        )
    except Exception:
        log.exception("digest.publish_failed")
    await send_email(f"CryptoBot daily digest — {date_str}", md)
    log.info("digest.sent", date=date_str)


async def run_digest(stop_event: asyncio.Event | None = None) -> None:
    """Fire once a day when the clock crosses 07:00 UTC."""
    log.info("digest.started", hour_utc=DIGEST_HOUR_UTC)
    last_sent_date: str | None = None
    while not (stop_event and stop_event.is_set()):
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        if now.hour == DIGEST_HOUR_UTC and last_sent_date != today:
            last_sent_date = today
            try:
                await send_digest()
            except Exception:
                log.exception("digest.run_failed")
        await asyncio.sleep(CHECK_INTERVAL_S)
