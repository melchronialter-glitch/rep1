from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.topics import (
    SIGNAL_ALERT_MEDIUM,
    SOCIAL_NARRATIVE_SPIKE,
    SOCIAL_REDDIT_POST,
    SOCIAL_TG_CALL,
    SOCIAL_X_TWEET,
)

log = get_logger(__name__)

_GROUP = "narrative_tracker"
_CONSUMER = "narrative_tracker_1"

_TICKER_RE = re.compile(r"\$([A-Z]{2,10})\b")
_ADDRESS_RE = re.compile(r"\b(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})\b")

_WINDOWS = {
    "1h": 3600,
    "4h": 4 * 3600,
    "24h": 24 * 3600,
}

_SNAPSHOT_INTERVAL = 300
_INSERT_SNAPSHOT = """
INSERT INTO narrative_snapshots (id, coin, address, mentions_1h, mentions_4h, mentions_24h, ts)
VALUES ($1, $2, $3, $4, $5, $6, NOW())
"""


def _redis_key(window: str, coin: str) -> str:
    return f"cb:narrative:{window}:{coin}"


async def _record_mention(redis: Any, coin: str) -> dict[str, int]:
    now = time.time()
    counts: dict[str, int] = {}
    for window, seconds in _WINDOWS.items():
        key = _redis_key(window, coin)
        cutoff = now - seconds
        try:
            await redis.zadd(key, {str(now): now})
            await redis.zremrangebyscore(key, "-inf", cutoff)
            count = await redis.zcount(key, cutoff, "+inf")
            await redis.expire(key, seconds * 2)
            counts[window] = int(count)
        except Exception as exc:
            log.warning("narrative_tracker.redis.error", coin=coin, window=window, error=str(exc))
            counts[window] = 0
    return counts


async def _get_prior_1h_count(redis: Any, coin: str) -> int:
    """Return mention count from the hour before the current hour."""
    now = time.time()
    two_hours_ago = now - 7200
    one_hour_ago = now - 3600
    key = _redis_key("4h", coin)
    try:
        count = await redis.zcount(key, two_hours_ago, one_hour_ago)
        return int(count)
    except Exception:
        return 0


def _extract_coins(text: str) -> list[tuple[str, str]]:
    """Returns list of (ticker_or_address, type) tuples."""
    results: list[tuple[str, str]] = []
    for ticker in _TICKER_RE.findall(text.upper()):
        results.append((ticker, "ticker"))
    for addr in _ADDRESS_RE.findall(text):
        results.append((addr, "address"))
    return results


def _get_text(topic: str, payload: dict[str, Any]) -> str:
    if topic == SOCIAL_TG_CALL:
        return payload.get("text", "") or payload.get("message", "")
    if topic == SOCIAL_X_TWEET:
        return payload.get("text", "") or payload.get("full_text", "")
    if topic == SOCIAL_REDDIT_POST:
        title = payload.get("title", "")
        body = payload.get("selftext", "") or payload.get("body", "")
        return f"{title} {body}"
    return ""


async def _maybe_spike(
    redis: Any,
    bus: Any,
    coin: str,
    address: str,
    counts: dict[str, int],
    threshold: int,
) -> None:
    mentions_1h = counts.get("1h", 0)
    if mentions_1h < threshold:
        return

    prior = await _get_prior_1h_count(redis, coin)
    if prior == 0:
        velocity_change_pct = 999999
    else:
        velocity_change_pct = int(((mentions_1h - prior) / prior) * 100)

    if mentions_1h >= threshold and (prior == 0 or velocity_change_pct >= 100):
        spike_payload = {
            "coin": coin,
            "address": address,
            "mentions_1h": mentions_1h,
            "mentions_4h": counts.get("4h", 0),
            "mentions_24h": counts.get("24h", 0),
            "velocity_change_pct": velocity_change_pct,
        }
        log.info(
            "narrative_tracker.spike.detected",
            coin=coin,
            mentions_1h=mentions_1h,
            velocity_change_pct=velocity_change_pct,
        )
        try:
            bus.publish(SOCIAL_NARRATIVE_SPIKE, spike_payload, source="narrative_tracker")
            bus.publish(SIGNAL_ALERT_MEDIUM, spike_payload, source="narrative_tracker")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("narrative_tracker.publish.error", error=str(exc))


async def _snapshot_loop(redis: Any, stop_event: asyncio.Event | None) -> None:
    """Periodically snapshot top coins to the DB."""
    while not (stop_event and stop_event.is_set()):
        try:
            await asyncio.sleep(_SNAPSHOT_INTERVAL)
        except asyncio.CancelledError:
            raise

        try:
            pattern = "cb:narrative:1h:*"
            keys = []
            async for key in redis.scan_iter(pattern):
                keys.append(key)

            now = time.time()
            cutoff_1h = now - _WINDOWS["1h"]

            for key in keys[:50]:
                coin = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                try:
                    count_1h = int(await redis.zcount(_redis_key("1h", coin), cutoff_1h, "+inf"))
                    count_4h = int(await redis.zcount(_redis_key("4h", coin), now - _WINDOWS["4h"], "+inf"))
                    count_24h = int(await redis.zcount(_redis_key("24h", coin), now - _WINDOWS["24h"], "+inf"))
                    if count_1h == 0 and count_4h == 0:
                        continue
                    await execute(
                        _INSERT_SNAPSHOT,
                        uuid.uuid4(),
                        coin,
                        None,
                        count_1h,
                        count_4h,
                        count_24h,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("narrative_tracker.snapshot.error", coin=coin, error=str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("narrative_tracker.snapshot_loop.error", error=str(exc))


async def run_narrative_tracker(stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    log.info("narrative_tracker.started", threshold=settings.narrative_spike_threshold)
    bus = get_bus()
    redis = bus._redis

    topics = [SOCIAL_TG_CALL, SOCIAL_X_TWEET, SOCIAL_REDDIT_POST]
    stream = bus.subscribe(topics, group=_GROUP, consumer=_CONSUMER)

    snapshot_task = asyncio.create_task(_snapshot_loop(redis, stop_event))

    try:
        async for topic, msg_id, event in stream:
            if stop_event and stop_event.is_set():
                break

            payload = event.payload
            text = _get_text(topic, payload)
            if not text:
                try:
                    bus.ack(topic, _GROUP, msg_id)
                except Exception:
                    pass
                continue

            coins = _extract_coins(text)
            seen: set[str] = set()
            for coin_id, kind in coins:
                if coin_id in seen:
                    continue
                seen.add(coin_id)

                ticker = coin_id if kind == "ticker" else ""
                address = coin_id if kind == "address" else ""
                key = ticker or address

                try:
                    counts = await _record_mention(redis, key)
                    await _maybe_spike(
                        redis,
                        bus,
                        ticker or address,
                        address,
                        counts,
                        settings.narrative_spike_threshold,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("narrative_tracker.mention.error", coin=key, error=str(exc))

            try:
                bus.ack(topic, _GROUP, msg_id)
            except Exception:
                pass
    except asyncio.CancelledError:
        raise
    finally:
        snapshot_task.cancel()
        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass
        log.info("narrative_tracker.stopped")
