"""Triage agent — Phase A stub.

Real triage (Claude-assisted routing of every event) lands in Phase B/D. For
now this agent exists to prove the spine works end-to-end:

  raw event topic in bus  ─▶ triage  ─▶ signal.alert.* in bus  ─▶ telegram

It subscribes to a wildcard-ish set of source topics, classifies them with a
cheap rule (currently: every event becomes a firehose alert), and republishes
to the appropriate signal.alert.* topic.
"""

from __future__ import annotations

import asyncio

from cryptobot.bus import Event, get_bus
from cryptobot.logging import get_logger
from cryptobot.topics import (
    MARKET_PRICE_MOVE,
    NEWS_CRYPTO,
    NEWS_MACRO_HIGH_IMPACT,
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MACRO,
    SIGNAL_ALERT_STRICT,
)

log = get_logger(__name__)

# Topics this stub triage listens to. Real version subscribes to everything.
WATCHED = [
    "demo.ping",
    MARKET_PRICE_MOVE,
    NEWS_CRYPTO,
    NEWS_MACRO_HIGH_IMPACT,
]


def _route(event: Event) -> str:
    """Phase-A routing rule. Replace in Phase B with Claude triage."""
    topic = event.topic
    payload = event.payload or {}
    severity = (payload.get("severity") or "").lower()

    if topic == NEWS_MACRO_HIGH_IMPACT:
        return SIGNAL_ALERT_MACRO
    if severity in ("high", "critical"):
        return SIGNAL_ALERT_STRICT
    return SIGNAL_ALERT_FIREHOSE


async def run_triage(stop_event: asyncio.Event | None = None) -> None:
    bus = get_bus()
    log.info("triage.started", watched=WATCHED)
    async for msg_id, topic, event in bus.subscribe(
        WATCHED, group="triage", consumer="triage-1"
    ):
        try:
            target = _route(event)
            await bus.publish(target, event.payload, source=f"triage:{topic}")
            log.info("triage.routed", from_topic=topic, to=target, id=event.id)
        except Exception:
            log.exception("triage.error", topic=topic, id=event.id)
        finally:
            await bus.ack(topic, "triage", msg_id)
        if stop_event and stop_event.is_set():
            break
