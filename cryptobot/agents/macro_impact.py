"""Macro impact agent — enriches high-impact macro/economic events with Claude
Sonnet analysis.

Subscribes to:
  - news.macro.high_impact  (from macro_news watcher)
  - news.econ_event         (from econ_calendar watcher)

Batches up to 3 events OR waits at most 5 minutes, then calls Claude to assess:
  - Which crypto assets are likely affected and how
  - Historical precedent for this type of event
  - Short-term bias for BTC/ETH/alts (bullish/bearish/neutral)

Publishes result to signal.alert.macro.

System prompt is concise and prompt-cached.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from cryptobot import llm
from cryptobot.bus import Event, get_bus
from cryptobot.logging import get_logger
from cryptobot.topics import (
    NEWS_ECON_EVENT,
    NEWS_MACRO_HIGH_IMPACT,
    SIGNAL_ALERT_MACRO,
)

log = get_logger(__name__)

WATCHED = [NEWS_MACRO_HIGH_IMPACT, NEWS_ECON_EVENT]

_BATCH_MAX = 3
_BATCH_WINDOW_S = 300.0   # 5 minutes

_MACRO_SYSTEM = """\
You are a senior macro analyst for a crypto trading desk. Given one or more
high-impact macro or economic events, provide a concise assessment:

1. AFFECTED ASSETS — which crypto assets (BTC, ETH, alts, DeFi, stables) are
   most exposed and why.
2. HISTORICAL PRECEDENT — brief note on how crypto markets have historically
   reacted to this type of event (1-2 sentences).
3. SHORT-TERM BIAS — for BTC, ETH, and alts separately: bullish / bearish /
   neutral, with a one-line rationale.

Constraints:
- Be specific and concise. Total response under 300 words.
- Do not hedge with generic disclaimers.
- Focus on the next 24–72 hour window.

Respond in JSON:
{
  "affected_assets": ["BTC", "ETH", ...],
  "btc_bias": "bullish|bearish|neutral",
  "eth_bias": "bullish|bearish|neutral",
  "alts_bias": "bullish|bearish|neutral",
  "summary": "<2-3 sentence overall assessment>",
  "precedent": "<1-2 sentence historical note>"
}"""


def _format_events(events: list[Event]) -> str:
    lines: list[str] = []
    for i, ev in enumerate(events, 1):
        p = ev.payload or {}
        entry: dict[str, Any] = {"index": i}
        if p.get("title"):
            entry["title"] = p["title"]
        if p.get("currency"):
            entry["currency"] = p["currency"]
        if p.get("impact"):
            entry["impact"] = p["impact"]
        if p.get("datetime"):
            entry["datetime"] = p["datetime"]
        if p.get("forecast"):
            entry["forecast"] = p["forecast"]
        if p.get("previous"):
            entry["previous"] = p["previous"]
        if p.get("source"):
            entry["source"] = p["source"]
        if p.get("summary"):
            entry["summary"] = str(p["summary"])[:200]
        lines.append(json.dumps(entry, separators=(",", ":")))
    return "\n".join(lines)


async def _assess_batch(events: list[Event]) -> None:
    bus = get_bus()
    user_text = _format_events(events)

    assessment: dict[str, Any] = {}
    try:
        result = await llm.analyze(
            system=_MACRO_SYSTEM,
            user=user_text,
            fast=False,
            json_response=True,
            max_tokens=512,
            temperature=0.3,
        )
        assessment = result.get("json") or {}
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("macro_impact.llm_failed", batch_size=len(events))
        # Fall back: publish raw events without enrichment.
        for ev in events:
            try:
                await bus.publish(SIGNAL_ALERT_MACRO, ev.payload, source="macro_impact:fallback")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("macro_impact.fallback_publish_failed")
        return

    # Build an enriched payload combining all events.
    combined_titles = [str((ev.payload or {}).get("title") or "") for ev in events]
    payload: dict[str, Any] = {
        "event_count": len(events),
        "event_titles": combined_titles,
        "affected_assets": assessment.get("affected_assets") or [],
        "btc_bias": assessment.get("btc_bias") or "neutral",
        "eth_bias": assessment.get("eth_bias") or "neutral",
        "alts_bias": assessment.get("alts_bias") or "neutral",
        "summary": assessment.get("summary") or "",
        "precedent": assessment.get("precedent") or "",
        "source_topics": list({ev.topic for ev in events}),
    }

    try:
        await bus.publish(SIGNAL_ALERT_MACRO, payload, source="macro_impact")
        log.info(
            "macro_impact.published",
            event_count=len(events),
            btc_bias=payload["btc_bias"],
            affected=payload["affected_assets"],
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("macro_impact.publish_failed")


async def _batcher(
    queue: asyncio.Queue[Event],
    stop_event: asyncio.Event | None,
) -> None:
    """Collect events into batches of up to _BATCH_MAX over _BATCH_WINDOW_S."""
    while not (stop_event and stop_event.is_set()):
        batch: list[Event] = []
        try:
            first = await asyncio.wait_for(queue.get(), timeout=5.0)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            raise

        batch.append(first)
        deadline = asyncio.get_running_loop().time() + _BATCH_WINDOW_S

        while len(batch) < _BATCH_MAX:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(queue.get(), timeout=remaining))
            except TimeoutError:
                break
            except asyncio.CancelledError:
                raise

        try:
            await _assess_batch(batch)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("macro_impact.batch_error", batch_size=len(batch))


async def run_macro_impact(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: subscribe to macro/econ events, batch, enrich with Claude."""
    bus = get_bus()
    queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=500)
    batcher_task = asyncio.create_task(
        _batcher(queue, stop_event), name="macro-impact-batcher"
    )
    log.info("macro_impact.started", watched=WATCHED)

    try:
        async for msg_id, topic, event in bus.subscribe(
            WATCHED, group="macro_impact", consumer="macro-impact-1"
        ):
            try:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    log.warning("macro_impact.queue_full", id=event.id)
                    # Degrade: publish directly to macro channel without enrichment.
                    try:
                        await bus.publish(
                            SIGNAL_ALERT_MACRO, event.payload, source="macro_impact:overflow"
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.exception("macro_impact.overflow_publish_failed")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("macro_impact.event_error", topic=topic, id=event.id)
            finally:
                await bus.ack(topic, "macro_impact", msg_id)

            if stop_event and stop_event.is_set():
                break
    finally:
        batcher_task.cancel()
        try:
            await batcher_task
        except (asyncio.CancelledError, Exception):
            log.debug("macro_impact.batcher.stopped")
