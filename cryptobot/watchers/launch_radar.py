"""Launch radar — scrapes upcoming token launches and vesting unlocks from
Messari's free public events API.

Endpoint: https://data.messari.io/api/v1/events?sort=-date&fields=title,date,type,coin

Polls every ``launch_radar_poll_interval_s`` seconds (default 3600 = 1 hour).

Filtering:
  - type == "unlock"  → chain.vesting_unlock   (medium alert)
  - type == "launch"  → chain.upcoming_launch   (firehose alert)
  - "IDO" anywhere in title → chain.upcoming_launch  (firehose alert)

Deduplication: persists seen event IDs to the ``vesting_events`` Postgres table
(natural dedup) and checks before publishing.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import httpx

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute, fetchrow
from cryptobot.logging import get_logger
from cryptobot.topics import CHAIN_UPCOMING_LAUNCH, CHAIN_VESTING_UNLOCK

log = get_logger(__name__)

_MESSARI_EVENTS_URL = (
    "https://data.messari.io/api/v1/events?sort=-date&fields=title,date,type,coin"
)
_HTTP_TIMEOUT = 20.0


def _make_event_id(title: str, date: str) -> str:
    """Deterministic ID for deduplication."""
    raw = f"{title}::{date}"
    return hashlib.sha1(raw.encode()).hexdigest()[:32]


def _classify_event(event_type: str, title: str) -> str | None:
    """Return 'unlock', 'launch', or None (skip)."""
    et = (event_type or "").lower()
    ttl = (title or "").upper()
    if et == "unlock":
        return "unlock"
    if et == "launch" or "IDO" in ttl or "TGE" in ttl or "LAUNCH" in ttl:
        return "launch"
    return None


async def _already_seen(event_id: str) -> bool:
    row = await fetchrow("SELECT id FROM vesting_events WHERE id = $1", event_id)
    return row is not None


async def _persist_event(
    event_id: str,
    title: str,
    date: str,
    event_type: str,
    coin: str,
    source: str,
) -> None:
    try:
        await execute(
            "INSERT INTO vesting_events (id, title, event_date, event_type, coin, source) "
            "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO NOTHING",
            event_id,
            title,
            date,
            event_type,
            coin,
            source,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("launch_radar.persist_failed", event_id=event_id)


async def _poll_once(client: httpx.AsyncClient) -> None:
    bus = get_bus()
    try:
        resp = await client.get(_MESSARI_EVENTS_URL, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("launch_radar.fetch_failed")
        return

    events_raw: list[dict[str, Any]] = (data.get("data") or [])
    if not events_raw:
        log.debug("launch_radar.no_events_returned")
        return

    for raw in events_raw:
        title: str = str(raw.get("title") or "")
        date: str = str(raw.get("date") or "")
        event_type: str = str(raw.get("type") or "")
        coin_info = raw.get("coin") or {}
        coin: str = (
            coin_info.get("symbol") or coin_info.get("name") or ""
            if isinstance(coin_info, dict)
            else str(coin_info)
        )

        if not title or not date:
            continue

        classification = _classify_event(event_type, title)
        if classification is None:
            continue

        event_id = _make_event_id(title, date)
        try:
            if await _already_seen(event_id):
                log.debug("launch_radar.duplicate_skipped", event_id=event_id)
                continue
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("launch_radar.seen_check_failed", event_id=event_id)
            continue

        topic = CHAIN_VESTING_UNLOCK if classification == "unlock" else CHAIN_UPCOMING_LAUNCH

        payload: dict[str, Any] = {
            "title": title,
            "date": date,
            "type": classification,
            "coin": coin,
            "source": "messari",
        }

        try:
            await bus.publish(topic, payload, source="launch_radar")
            log.info(
                "launch_radar.published",
                topic=topic,
                title=title[:80],
                date=date,
                coin=coin,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("launch_radar.publish_failed", event_id=event_id)
            continue

        await _persist_event(event_id, title, date, classification, coin, "messari")


async def run_launch_radar(stop_event: asyncio.Event | None = None) -> None:
    """Main poll loop. No API key required."""
    settings = get_settings()
    poll_interval = settings.launch_radar_poll_interval_s
    log.info("launch_radar.started", poll_interval_s=poll_interval)

    async with httpx.AsyncClient() as client:
        while not (stop_event and stop_event.is_set()):
            try:
                await _poll_once(client)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("launch_radar.poll_error")

            try:
                await asyncio.wait_for(asyncio.sleep(poll_interval), timeout=poll_interval + 5)
            except (TimeoutError, asyncio.TimeoutError):
                pass
            except asyncio.CancelledError:
                raise

            if stop_event and stop_event.is_set():
                break
