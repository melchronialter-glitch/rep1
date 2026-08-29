"""Orderbook watcher — connects to Binance WebSocket depth stream and publishes
imbalance signals when bid/ask volume skew crosses the configured threshold.

URL pattern:
    wss://stream.binance.com:9443/stream?streams={sym1}@depth20@1000ms/{sym2}@...

Reconnects with exponential back-off (1 → 2 → 4 → … → 60 s) on any disconnect.
Self-disables when ``orderbook_symbol_list`` is empty.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import websockets
import websockets.exceptions

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.topics import MARKET_ORDERBOOK_IMBALANCE

log = get_logger(__name__)

_BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"
_RECONNECT_MIN_S = 1
_RECONNECT_MAX_S = 60
_COOLDOWN_S = 60  # minimum seconds between publishes per symbol


def _build_ws_url(symbols: list[str]) -> str:
    streams = "/".join(f"{sym.lower()}@depth20@1000ms" for sym in symbols)
    return f"{_BINANCE_WS_BASE}?streams={streams}"


def _parse_depth_message(raw: dict[str, Any]) -> tuple[str, float, float, float, float] | None:
    """Parse a combined-stream depth message.

    Returns (symbol_upper, bid_volume, ask_volume, best_bid, best_ask) or None.
    """
    stream_name: str = raw.get("stream") or ""
    data: dict[str, Any] = raw.get("data") or {}
    if not stream_name or not data:
        return None

    # stream = "btcusdt@depth20@1000ms"
    symbol = stream_name.split("@")[0].upper()

    bids: list[list[str]] = data.get("bids") or []
    asks: list[list[str]] = data.get("asks") or []

    if not bids or not asks:
        return None

    bid_volume = sum(float(qty) for _price, qty in bids)
    ask_volume = sum(float(qty) for _price, qty in asks)
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])

    return symbol, bid_volume, ask_volume, best_bid, best_ask


async def _handle_stream(
    symbols: list[str],
    threshold: float,
    last_publish: dict[str, float],
) -> None:
    """Open a single WebSocket connection and process messages until disconnected."""
    url = _build_ws_url(symbols)
    log.info("orderbook.connecting", url=url)

    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
        log.info("orderbook.connected", symbol_count=len(symbols))
        async for raw_msg in ws:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            parsed = _parse_depth_message(msg)
            if parsed is None:
                continue

            symbol, bid_vol, ask_vol, best_bid, best_ask = parsed
            total = bid_vol + ask_vol
            if total <= 0:
                continue

            imbalance = bid_vol / total
            heavy_bids = imbalance > (1.0 - threshold)
            heavy_asks = imbalance < threshold

            if not (heavy_bids or heavy_asks):
                continue

            now = time.monotonic()
            if now - last_publish.get(symbol, 0.0) < _COOLDOWN_S:
                continue

            last_publish[symbol] = now
            direction = "bid_heavy" if heavy_bids else "ask_heavy"

            payload: dict[str, Any] = {
                "symbol": symbol,
                "bid_volume": round(bid_vol, 4),
                "ask_volume": round(ask_vol, 4),
                "imbalance": round(imbalance, 4),
                "direction": direction,
                "best_bid": best_bid,
                "best_ask": best_ask,
            }

            bus = get_bus()
            specific_topic = f"{MARKET_ORDERBOOK_IMBALANCE}.{symbol}"
            try:
                await bus.publish(specific_topic, payload, source="orderbook", persist=False)
                await bus.publish(MARKET_ORDERBOOK_IMBALANCE, payload, source="orderbook", persist=False)
                log.info(
                    "orderbook.imbalance_published",
                    symbol=symbol,
                    imbalance=round(imbalance, 3),
                    direction=direction,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("orderbook.publish_failed", symbol=symbol)


async def run_orderbook(stop_event: asyncio.Event | None = None) -> None:
    """Main run loop: connects, processes, reconnects with exponential back-off."""
    settings = get_settings()
    symbols = settings.orderbook_symbol_list

    if not symbols:
        log.info("orderbook.disabled", reason="orderbook_symbol_list is empty")
        return

    threshold = settings.orderbook_imbalance_threshold
    log.info("orderbook.started", symbols=symbols, threshold=threshold)

    last_publish: dict[str, float] = {}
    backoff = _RECONNECT_MIN_S

    while not (stop_event and stop_event.is_set()):
        try:
            await _handle_stream(symbols, threshold, last_publish)
            # Clean disconnect — reset back-off.
            backoff = _RECONNECT_MIN_S
        except asyncio.CancelledError:
            raise
        except websockets.exceptions.ConnectionClosed as exc:
            log.warning("orderbook.disconnected", code=exc.code, reason=exc.reason)
        except Exception:
            log.exception("orderbook.stream_error")

        if stop_event and stop_event.is_set():
            break

        log.info("orderbook.reconnecting", backoff_s=backoff)
        try:
            await asyncio.wait_for(asyncio.sleep(backoff), timeout=backoff + 1)
        except (TimeoutError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
        backoff = min(backoff * 2, _RECONNECT_MAX_S)
