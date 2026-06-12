"""Triage agent — first-pass router for incoming market/news events.

Two-stage routing:

- **Stage 1 (free, instant)** — hard rules. ``news.macro.high_impact`` goes
  straight to the macro alert channel; high-severity price moves to strict;
  medium price moves and volume spikes to medium.
- **Stage 2 (Claude Haiku)** — ``news.crypto`` items are batched (up to 10
  items or 60 seconds, whichever first) and scored by a cheap cached prompt:
  ignore / firehose / medium / strict. On any Claude failure, the whole batch
  falls back to firehose — we never lose events.

Redis Streams can't wildcard, so watchers publish both to symbol-specific
topics (``market.price_move.BTCUSDT``) and base aggregate topics
(``market.price_move``). Triage subscribes to the base topics.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from cryptobot import llm
from cryptobot.bus import Event, get_bus
from cryptobot.logging import get_logger
from cryptobot.topics import (
    MARKET_PRICE_MOVE,
    MARKET_VOLUME_SPIKE,
    NEWS_CRYPTO,
    NEWS_MACRO,
    NEWS_MACRO_HIGH_IMPACT,
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MACRO,
    SIGNAL_ALERT_MEDIUM,
    SIGNAL_ALERT_STRICT,
)

log = get_logger(__name__)

WATCHED = [
    NEWS_CRYPTO,
    NEWS_MACRO,
    NEWS_MACRO_HIGH_IMPACT,
    MARKET_PRICE_MOVE,
    MARKET_VOLUME_SPIKE,
]

NEWS_BATCH_MAX = 10
NEWS_BATCH_WINDOW_S = 60.0

IMPORTANCE_TO_TOPIC: dict[str, str | None] = {
    "ignore": None,
    "firehose": SIGNAL_ALERT_FIREHOSE,
    "medium": SIGNAL_ALERT_MEDIUM,
    "strict": SIGNAL_ALERT_STRICT,
}

NEWS_TRIAGE_SYSTEM = """\
You are a concise crypto news triage analyst for an automated alerting system.
You receive a numbered batch of crypto news headlines (with source and summary
when available). For EACH item, score how actionable it is for an active
crypto trader/researcher:

- "ignore": noise, ads, listicles, price recaps, sponsored content
- "firehose": mildly interesting, background signal
- "medium": notable — protocol incidents, big partnerships, exchange/regulatory
  developments, significant funding, whale activity
- "strict": urgent and market-moving — hacks/exploits in progress, exchange
  insolvency, major regulatory action, ETF decisions, critical depegs

Respond with JSON: {"items": [{"index": <int>, "importance":
"ignore|firehose|medium|strict", "reason": "<short>", "affected_assets":
["BTC", ...]}]}. Include every index exactly once. Be conservative with
"strict"."""


def _route_hard_rules(topic: str, event: Event) -> str | None:
    """Stage 1: instant rule-based routing. Returns target topic or None."""
    payload = event.payload or {}
    severity = (payload.get("severity") or "").lower()

    if topic == NEWS_MACRO_HIGH_IMPACT:
        return SIGNAL_ALERT_MACRO
    if topic == NEWS_MACRO:
        return SIGNAL_ALERT_MACRO
    if topic == MARKET_PRICE_MOVE:
        return SIGNAL_ALERT_STRICT if severity == "high" else SIGNAL_ALERT_MEDIUM
    if topic == MARKET_VOLUME_SPIKE:
        return SIGNAL_ALERT_MEDIUM
    return None


def _format_news_batch(batch: list[Event]) -> str:
    lines: list[str] = []
    for i, event in enumerate(batch):
        p = event.payload or {}
        line: dict[str, Any] = {
            "index": i,
            "title": p.get("title"),
            "source": p.get("source"),
        }
        if p.get("summary"):
            line["summary"] = str(p["summary"])[:300]
        if p.get("currencies"):
            line["currencies"] = p["currencies"]
        lines.append(json.dumps(line, separators=(",", ":")))
    return "\n".join(lines)


async def _triage_news_batch(batch: list[Event]) -> None:
    """Stage 2: score a batch of news.crypto events with Claude Haiku."""
    bus = get_bus()
    scores: dict[int, dict[str, Any]] = {}
    try:
        result = await llm.analyze(
            system=NEWS_TRIAGE_SYSTEM,
            user=_format_news_batch(batch),
            fast=True,
            json_response=True,
            max_tokens=1500,
            temperature=0.0,
        )
        for item in (result.get("json") or {}).get("items") or []:
            idx = item.get("index")
            if isinstance(idx, int) and 0 <= idx < len(batch):
                scores[idx] = item
    except Exception:
        log.exception("triage.news.llm_failed", batch_size=len(batch))

    for i, event in enumerate(batch):
        score = scores.get(i)
        if score is None:
            # Claude failed or skipped this item — never lose events.
            target: str | None = SIGNAL_ALERT_FIREHOSE
            reason = "llm_fallback"
            assets: list[str] = []
        else:
            importance = str(score.get("importance") or "firehose").lower()
            target = IMPORTANCE_TO_TOPIC.get(importance, SIGNAL_ALERT_FIREHOSE)
            reason = str(score.get("reason") or "")
            assets = score.get("affected_assets") or []
        if target is None:
            log.debug("triage.news.ignored", id=event.id, reason=reason)
            continue
        payload = {
            **(event.payload or {}),
            "triage_reason": reason,
            "affected_assets": assets,
        }
        await bus.publish(target, payload, source="triage:news.crypto")
        log.info("triage.news.routed", to=target, id=event.id, reason=reason[:80])


async def _news_batcher(
    queue: asyncio.Queue[Event], stop_event: asyncio.Event | None
) -> None:
    """Collect news.crypto events into batches of up to 10 over 60s windows."""
    while not (stop_event and stop_event.is_set()):
        batch: list[Event] = []
        try:
            first = await asyncio.wait_for(queue.get(), timeout=5.0)
        except TimeoutError:
            continue
        batch.append(first)
        deadline = asyncio.get_running_loop().time() + NEWS_BATCH_WINDOW_S
        while len(batch) < NEWS_BATCH_MAX:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(queue.get(), timeout=remaining))
            except TimeoutError:
                break
        try:
            await _triage_news_batch(batch)
        except Exception:
            log.exception("triage.news.batch_error", batch_size=len(batch))


async def run_triage(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: hard rules instantly, news.crypto batched through Claude."""
    bus = get_bus()
    news_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
    batcher = asyncio.create_task(_news_batcher(news_queue, stop_event), name="triage-batcher")
    log.info("triage.started", watched=WATCHED)

    try:
        async for msg_id, topic, event in bus.subscribe(
            WATCHED, group="triage", consumer="triage-1"
        ):
            try:
                if topic == NEWS_CRYPTO:
                    try:
                        news_queue.put_nowait(event)
                    except asyncio.QueueFull:
                        # Backpressure: degrade to firehose rather than block.
                        await bus.publish(
                            SIGNAL_ALERT_FIREHOSE, event.payload, source="triage:overflow"
                        )
                        log.warning("triage.news.queue_full", id=event.id)
                else:
                    target = _route_hard_rules(topic, event)
                    if target:
                        await bus.publish(target, event.payload, source=f"triage:{topic}")
                        log.info("triage.routed", from_topic=topic, to=target, id=event.id)
            except Exception:
                log.exception("triage.error", topic=topic, id=event.id)
            finally:
                await bus.ack(topic, "triage", msg_id)
            if stop_event and stop_event.is_set():
                break
    finally:
        batcher.cancel()
        try:
            await batcher
        except (asyncio.CancelledError, Exception):
            log.debug("triage.batcher.stopped")
