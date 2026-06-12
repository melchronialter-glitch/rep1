"""Economic calendar watcher — polls Forex Factory's free JSON calendar.

Source: https://nfs.faireconomy.media/ff_calendar_thisweek.json

Polls every ``econ_calendar_poll_interval_s`` seconds (default 3600 = 30 min
recommended, but configurable).

Logic:
  - Filters: impact == "High" AND currency in {USD, EUR, CNY, JPY, GBP}
  - Publishes ``news.econ_event`` 1 hour before each event's scheduled time
  - Deduplicates on (date + title) via the ``vesting_events`` table
    (reuses the same table — id prefixed with "econ::" to avoid collision)

Routing (handled by triage):
  - High-impact USD events → signal.alert.macro
  - Others → signal.alert.medium
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute, fetchrow
from cryptobot.logging import get_logger
from cryptobot.topics import NEWS_ECON_EVENT

log = get_logger(__name__)

_FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_HTTP_TIMEOUT = 20.0
_WATCH_CURRENCIES = {"USD", "EUR", "CNY", "JPY", "GBP"}
_ALERT_WINDOW_MINUTES = 60   # publish when event is this many minutes away
_ALERT_WINDOW_TOLERANCE = 5  # re-check buffer (seconds)


def _make_econ_id(date: str, title: str) -> str:
    raw = f"econ::{date}::{title}"
    return "econ-" + hashlib.sha1(raw.encode()).hexdigest()[:28]


def _parse_event_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse Forex Factory date + time strings into a UTC-aware datetime.

    FF date format: "06-06-2026"  (MM-DD-YYYY)
    FF time format: "8:30am"  or "All Day" / empty
    """
    if not date_str:
        return None
    try:
        # Forex Factory uses US Eastern time — but they now supply UTC in newer
        # API versions.  We treat the combined string as-is and assume UTC for
        # simplicity.  In production you'd convert from US/Eastern.
        date_part = datetime.strptime(date_str.strip(), "%m-%d-%Y").date()
    except ValueError:
        log.debug("econ_calendar.date_parse_failed", date=date_str)
        return None

    time_str_clean = (time_str or "").strip().lower()
    if not time_str_clean or time_str_clean in {"all day", "tentative", ""}:
        # Use midnight UTC as a stand-in.
        return datetime(date_part.year, date_part.month, date_part.day, 0, 0, tzinfo=timezone.utc)
    try:
        t = datetime.strptime(time_str_clean, "%I:%M%p").time()
        return datetime(date_part.year, date_part.month, date_part.day, t.hour, t.minute, tzinfo=timezone.utc)
    except ValueError:
        try:
            t = datetime.strptime(time_str_clean, "%I%p").time()
            return datetime(date_part.year, date_part.month, date_part.day, t.hour, t.minute, tzinfo=timezone.utc)
        except ValueError:
            pass
    log.debug("econ_calendar.time_parse_failed", time=time_str)
    return None


async def _already_notified(event_id: str) -> bool:
    row = await fetchrow("SELECT id FROM vesting_events WHERE id = $1", event_id)
    return row is not None


async def _mark_notified(event_id: str, title: str, date: str, currency: str) -> None:
    try:
        await execute(
            "INSERT INTO vesting_events (id, title, event_date, event_type, coin, source) "
            "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO NOTHING",
            event_id,
            title,
            date,
            "econ_event",
            currency,
            "forex_factory",
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("econ_calendar.mark_notified_failed", event_id=event_id)


async def _poll_once(client: httpx.AsyncClient) -> None:
    bus = get_bus()

    try:
        resp = await client.get(_FF_URL, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        events: list[dict[str, Any]] = resp.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("econ_calendar.fetch_failed")
        return

    if not isinstance(events, list):
        log.warning("econ_calendar.unexpected_response_shape")
        return

    now = datetime.now(timezone.utc)

    for raw in events:
        impact: str = str(raw.get("impact") or "").strip()
        currency: str = str(raw.get("currency") or "").strip().upper()
        title: str = str(raw.get("title") or "").strip()
        date_str: str = str(raw.get("date") or "").strip()
        time_str: str = str(raw.get("time") or "").strip()
        forecast: str = str(raw.get("forecast") or "")
        previous: str = str(raw.get("previous") or "")

        if impact != "High":
            continue
        if currency not in _WATCH_CURRENCIES:
            continue
        if not title or not date_str:
            continue

        event_dt = _parse_event_datetime(date_str, time_str)
        if event_dt is None:
            continue

        minutes_until = (event_dt - now).total_seconds() / 60.0

        # Publish only when within the alert window and not yet in the past.
        if not (0 < minutes_until <= _ALERT_WINDOW_MINUTES + _ALERT_WINDOW_TOLERANCE / 60):
            continue

        event_id = _make_econ_id(date_str, title)
        try:
            if await _already_notified(event_id):
                log.debug("econ_calendar.already_notified", event_id=event_id)
                continue
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("econ_calendar.seen_check_failed", event_id=event_id)
            continue

        payload: dict[str, Any] = {
            "title": title,
            "currency": currency,
            "impact": impact,
            "datetime": event_dt.isoformat(),
            "forecast": forecast,
            "previous": previous,
            "minutes_until": round(minutes_until, 1),
        }

        try:
            await bus.publish(NEWS_ECON_EVENT, payload, source="econ_calendar")
            log.info(
                "econ_calendar.published",
                title=title[:60],
                currency=currency,
                minutes_until=round(minutes_until, 1),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("econ_calendar.publish_failed", event_id=event_id)
            continue

        await _mark_notified(event_id, title, date_str, currency)


async def run_econ_calendar(stop_event: asyncio.Event | None = None) -> None:
    """Main poll loop. No API key required."""
    settings = get_settings()
    poll_interval = settings.econ_calendar_poll_interval_s
    log.info("econ_calendar.started", poll_interval_s=poll_interval)

    async with httpx.AsyncClient() as client:
        while not (stop_event and stop_event.is_set()):
            try:
                await _poll_once(client)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("econ_calendar.poll_error")

            try:
                await asyncio.wait_for(asyncio.sleep(poll_interval), timeout=poll_interval + 5)
            except (TimeoutError, asyncio.TimeoutError):
                pass
            except asyncio.CancelledError:
                raise

            if stop_event and stop_event.is_set():
                break
