"""Derivatives watcher — polls Coinglass for funding rates and open interest.

Funding rate API: https://open-api.coinglass.com/public/v2/fundingRate?symbol=BTC
OI API:          https://open-api.coinglass.com/public/v2/openInterest?symbol=BTC

Requires ``CG-{coinglass_api_key}`` header.  Self-disables when no key is
configured.  Polls every 15 minutes.

Publishes ``market.funding_anomaly`` when:
  - funding_rate >  0.1% (very bullish leverage)
  - funding_rate < -0.1% (very bearish leverage)
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.topics import MARKET_FUNDING_ANOMALY

log = get_logger(__name__)

_POLL_INTERVAL_S = 900  # 15 minutes
_FUNDING_THRESHOLD = 0.001  # 0.1 %
_BASE_URL = "https://open-api.coinglass.com/public/v2"
_SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]
_HTTP_TIMEOUT = 20.0


def _make_headers(api_key: str) -> dict[str, str]:
    return {"CG-API-KEY": f"CG-{api_key}"}


async def _fetch_funding(
    client: httpx.AsyncClient,
    symbol: str,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    url = f"{_BASE_URL}/fundingRate?symbol={symbol}"
    try:
        resp = await client.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("derivatives.funding_fetch_failed", symbol=symbol)
        return None


async def _fetch_oi(
    client: httpx.AsyncClient,
    symbol: str,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    url = f"{_BASE_URL}/openInterest?symbol={symbol}"
    try:
        resp = await client.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("derivatives.oi_fetch_failed", symbol=symbol)
        return None


def _extract_funding_rate(data: dict[str, Any]) -> tuple[float, str] | None:
    """Extract the top-level funding rate and exchange from a Coinglass response.

    Returns (rate_pct, exchange) or None.
    """
    try:
        items = (data.get("data") or {}).get("list") or data.get("data") or []
        if isinstance(items, list) and items:
            entry = items[0]
            rate = float(entry.get("fundingRate") or 0.0)
            exchange = str(entry.get("exchangeName") or entry.get("exchange") or "unknown")
            return rate, exchange
    except Exception:
        log.exception("derivatives.extract_funding_failed")
    return None


def _extract_oi(data: dict[str, Any]) -> tuple[float, float] | None:
    """Return (oi_usd, oi_change_24h_pct) or None."""
    try:
        items = (data.get("data") or {}).get("list") or data.get("data") or []
        if isinstance(items, list) and items:
            entry = items[0]
            oi_usd = float(entry.get("openInterest") or entry.get("openInterestUsd") or 0.0)
            oi_change = float(
                entry.get("openInterestChangePercent24h")
                or entry.get("change24h")
                or 0.0
            )
            return oi_usd, oi_change
    except Exception:
        log.exception("derivatives.extract_oi_failed")
    return None


async def _poll_once(
    client: httpx.AsyncClient,
    symbols: list[str],
    headers: dict[str, str],
) -> None:
    bus = get_bus()
    for symbol in symbols:
        funding_data = await _fetch_funding(client, symbol, headers)
        oi_data = await _fetch_oi(client, symbol, headers)

        if funding_data is None:
            continue

        extracted = _extract_funding_rate(funding_data)
        if extracted is None:
            continue

        rate, exchange = extracted
        rate_pct = rate * 100.0  # convert to percent

        # Only publish on anomalous funding.
        if abs(rate_pct) < _FUNDING_THRESHOLD * 100.0:
            log.debug("derivatives.normal_funding", symbol=symbol, rate_pct=round(rate_pct, 4))
            continue

        oi_usd = 0.0
        oi_change = 0.0
        if oi_data:
            oi_extracted = _extract_oi(oi_data)
            if oi_extracted:
                oi_usd, oi_change = oi_extracted

        payload: dict[str, Any] = {
            "symbol": symbol,
            "funding_rate_pct": round(rate_pct, 4),
            "exchange": exchange,
            "open_interest_usd": round(oi_usd, 2),
            "oi_change_24h_pct": round(oi_change, 4),
        }

        try:
            await bus.publish(MARKET_FUNDING_ANOMALY, payload, source="derivatives")
            log.info(
                "derivatives.funding_anomaly",
                symbol=symbol,
                rate_pct=round(rate_pct, 4),
                exchange=exchange,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("derivatives.publish_failed", symbol=symbol)


async def run_derivatives(stop_event: asyncio.Event | None = None) -> None:
    """Main poll loop. Self-disables without COINGLASS_API_KEY."""
    settings = get_settings()
    if not settings.coinglass_api_key:
        log.info("derivatives.disabled", reason="coinglass_api_key not configured")
        return

    headers = _make_headers(settings.coinglass_api_key)
    log.info("derivatives.started", poll_interval_s=_POLL_INTERVAL_S, symbols=_SYMBOLS)

    async with httpx.AsyncClient() as client:
        while not (stop_event and stop_event.is_set()):
            try:
                await _poll_once(client, _SYMBOLS, headers)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("derivatives.poll_error")

            try:
                await asyncio.wait_for(asyncio.sleep(_POLL_INTERVAL_S), timeout=_POLL_INTERVAL_S + 5)
            except (TimeoutError, asyncio.TimeoutError):
                pass
            except asyncio.CancelledError:
                raise

            if stop_event and stop_event.is_set():
                break
