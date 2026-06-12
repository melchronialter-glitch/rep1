"""Sentiment index watcher — polls free public macro/sentiment APIs.

Sources:
  - Fear & Greed Index: https://api.alternative.me/fng/?limit=2
  - DXY (Dollar Index): Yahoo Finance chart  DX-Y.NYB  interval=1d range=2d
  - SPX (S&P 500):      Yahoo Finance chart  ^GSPC     interval=1d range=2d
  - Gold:               Yahoo Finance chart  GC=F      interval=1d range=2d

Polls every 30 minutes.  Publishes ``market.sentiment_shift`` when:
  - Fear & Greed crosses 25 (extreme fear) or 75 (extreme greed)
  - DXY moves >1 % in a day (dollar strength = crypto headwind)
  - SPX drops >2 % in a day

Routing:
  - Extreme readings (F&G ≤ 25 or ≥ 75, SPX ≤ -2 %) → signal.alert.macro
  - Others → signal.alert.medium
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.topics import MARKET_SENTIMENT_SHIFT

log = get_logger(__name__)

_POLL_INTERVAL_S = 1800  # 30 minutes
_HTTP_TIMEOUT = 20.0

_FNG_URL = "https://api.alternative.me/fng/?limit=2"
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"

_DXY_TICKER = "DX-Y.NYB"
_SPX_TICKER = "^GSPC"
_GOLD_TICKER = "GC=F"

_DXY_THRESHOLD_PCT = 1.0
_SPX_DROP_THRESHOLD_PCT = -2.0
_FNG_EXTREME_LOW = 25
_FNG_EXTREME_HIGH = 75


async def _fetch_fng(client: httpx.AsyncClient) -> dict[str, Any] | None:
    try:
        resp = await client.get(_FNG_URL, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("sentiment_index.fng_fetch_failed")
        return None


async def _fetch_yahoo(client: httpx.AsyncClient, ticker: str) -> dict[str, Any] | None:
    url = _YAHOO_CHART_URL.format(ticker=ticker)
    try:
        resp = await client.get(
            url,
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        return resp.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("sentiment_index.yahoo_fetch_failed", ticker=ticker)
        return None


def _parse_fng(data: dict[str, Any]) -> tuple[int, str, int] | None:
    """Return (today_value, today_label, yesterday_value) or None."""
    try:
        items = data.get("data") or []
        if len(items) < 2:
            return None
        today = items[0]
        yesterday = items[1]
        return (
            int(today.get("value") or 0),
            str(today.get("value_classification") or "Unknown"),
            int(yesterday.get("value") or 0),
        )
    except Exception:
        log.exception("sentiment_index.fng_parse_failed")
        return None


def _parse_yahoo_change_pct(data: dict[str, Any]) -> float | None:
    """Extract 1-day percentage change from a Yahoo Finance chart response."""
    try:
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            return None
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close") or []
        # Filter None values.
        valid_closes = [c for c in closes if c is not None]
        if len(valid_closes) < 2:
            return None
        prev = valid_closes[-2]
        curr = valid_closes[-1]
        if prev == 0:
            return None
        return ((curr - prev) / prev) * 100.0
    except Exception:
        log.exception("sentiment_index.yahoo_parse_failed")
        return None


async def _poll_once(client: httpx.AsyncClient) -> None:
    bus = get_bus()

    # Fetch all sources concurrently.
    fng_task = asyncio.create_task(_fetch_fng(client))
    dxy_task = asyncio.create_task(_fetch_yahoo(client, _DXY_TICKER))
    spx_task = asyncio.create_task(_fetch_yahoo(client, _SPX_TICKER))
    gold_task = asyncio.create_task(_fetch_yahoo(client, _GOLD_TICKER))

    fng_data, dxy_data, spx_data, gold_data = await asyncio.gather(
        fng_task, dxy_task, spx_task, gold_task, return_exceptions=False
    )

    fng_today = 50
    fng_label = "Neutral"
    fng_yesterday = 50
    dxy_change = 0.0
    spx_change = 0.0
    gold_change = 0.0

    if fng_data:
        parsed = _parse_fng(fng_data)
        if parsed:
            fng_today, fng_label, fng_yesterday = parsed

    if dxy_data:
        val = _parse_yahoo_change_pct(dxy_data)
        if val is not None:
            dxy_change = val

    if spx_data:
        val = _parse_yahoo_change_pct(spx_data)
        if val is not None:
            spx_change = val

    if gold_data:
        val = _parse_yahoo_change_pct(gold_data)
        if val is not None:
            gold_change = val

    # Determine whether to publish.
    fng_extreme = fng_today <= _FNG_EXTREME_LOW or fng_today >= _FNG_EXTREME_HIGH
    dxy_move = abs(dxy_change) >= _DXY_THRESHOLD_PCT
    spx_drop = spx_change <= _SPX_DROP_THRESHOLD_PCT
    fng_cross = (fng_yesterday > _FNG_EXTREME_LOW >= fng_today) or \
                (fng_yesterday < _FNG_EXTREME_HIGH <= fng_today)

    should_publish = fng_extreme or fng_cross or dxy_move or spx_drop
    if not should_publish:
        log.debug(
            "sentiment_index.no_signal",
            fng=fng_today,
            dxy_pct=round(dxy_change, 2),
            spx_pct=round(spx_change, 2),
        )
        return

    payload: dict[str, Any] = {
        "fear_greed_index": fng_today,
        "fear_greed_label": fng_label,
        "fear_greed_yesterday": fng_yesterday,
        "dxy_change_1d_pct": round(dxy_change, 3),
        "spx_change_1d_pct": round(spx_change, 3),
        "gold_change_1d_pct": round(gold_change, 3),
    }

    try:
        await bus.publish(MARKET_SENTIMENT_SHIFT, payload, source="sentiment_index")
        log.info(
            "sentiment_index.published",
            fng=fng_today,
            fng_label=fng_label,
            dxy_pct=round(dxy_change, 2),
            spx_pct=round(spx_change, 2),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("sentiment_index.publish_failed")


async def run_sentiment_index(stop_event: asyncio.Event | None = None) -> None:
    """Main poll loop. No API key required."""
    log.info("sentiment_index.started", poll_interval_s=_POLL_INTERVAL_S)

    async with httpx.AsyncClient() as client:
        while not (stop_event and stop_event.is_set()):
            try:
                await _poll_once(client)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sentiment_index.poll_error")

            try:
                await asyncio.wait_for(asyncio.sleep(_POLL_INTERVAL_S), timeout=_POLL_INTERVAL_S + 5)
            except (TimeoutError, asyncio.TimeoutError):
                pass
            except asyncio.CancelledError:
                raise

            if stop_event and stop_event.is_set():
                break
