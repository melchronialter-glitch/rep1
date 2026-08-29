"""Binance public WebSocket price watcher.

Connects to the combined miniTicker stream for the configured symbol list (no
API key needed), keeps a rolling in-memory price history per symbol, and:

- publishes ``market.price_move.{SYMBOL}`` when price moves more than
  ``price_move_threshold_pct`` within ``price_move_window_min`` minutes
- publishes ``market.volume_spike.{SYMBOL}`` when the 1h quote-volume delta is
  anomalous vs the trailing average
- snapshots every symbol to the ``price_snapshots`` table every 60s

Each detection is published twice: once on the symbol-specific topic
(persisted) and once on the base aggregate topic (not persisted) so that
agents like triage — which can't wildcard Redis Streams — can subscribe to
the base topic.

Reconnects with exponential backoff. Never crashes.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any

import websockets

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.topics import MARKET_PRICE_MOVE, MARKET_VOLUME_SPIKE

log = get_logger(__name__)

BINANCE_WS = "wss://stream.binance.com:9443/stream"
HISTORY_SECONDS = 24 * 3600  # keep ~24h of ticks
SNAPSHOT_INTERVAL_S = 60
COOLDOWN_S = 30 * 60  # per-symbol re-alert cooldown
VOLUME_SPIKE_FACTOR = 3.0  # 1h volume delta > 3x trailing average
MAX_BACKOFF_S = 120


class PriceWatcher:
    """State container for one watcher process."""

    def __init__(self) -> None:
        settings = get_settings()
        self.symbols = settings.price_symbol_list
        self.threshold_pct = settings.price_move_threshold_pct
        self.window_s = settings.price_move_window_min * 60
        self.window_min = settings.price_move_window_min
        # symbol -> deque of (unix_ts, price)
        self.history: dict[str, deque[tuple[float, float]]] = {
            s: deque() for s in self.symbols
        }
        # symbol -> latest (price, quote_volume_24h)
        self.latest: dict[str, tuple[float, float]] = {}
        # symbol -> (last_alert_ts, last_alert_change_pct)
        self.cooldown: dict[str, tuple[float, float]] = {}
        # symbol -> deque of (unix_ts, quote_volume_24h) snapshots for volume deltas
        self.volume_track: dict[str, deque[tuple[float, float]]] = {
            s: deque() for s in self.symbols
        }
        self.last_snapshot_ts = 0.0

    # ---- detection ---------------------------------------------------------

    def _trim(self, dq: deque[tuple[float, float]], now: float) -> None:
        while dq and now - dq[0][0] > HISTORY_SECONDS:
            dq.popleft()

    def check_price_move(self, symbol: str, price: float, now: float) -> dict[str, Any] | None:
        """Return a price-move payload if the threshold is crossed, else None."""
        dq = self.history[symbol]
        dq.append((now, price))
        self._trim(dq, now)

        # Find the reference price at the start of the window
        ref_price: float | None = None
        for ts, p in dq:
            if now - ts <= self.window_s:
                ref_price = p
                break
        if ref_price is None or ref_price <= 0:
            return None

        change_pct = (price - ref_price) / ref_price * 100.0
        if abs(change_pct) < self.threshold_pct:
            return None

        # Cooldown: skip re-alert within 30 min unless the move doubled
        last = self.cooldown.get(symbol)
        if last is not None:
            last_ts, last_pct = last
            if now - last_ts < COOLDOWN_S and abs(change_pct) < 2 * abs(last_pct):
                return None

        self.cooldown[symbol] = (now, change_pct)
        severity = "high" if abs(change_pct) > 2 * self.threshold_pct else "medium"
        return {
            "symbol": symbol.upper(),
            "price": price,
            "change_pct": round(change_pct, 3),
            "window_min": self.window_min,
            "direction": "up" if change_pct > 0 else "down",
            "severity": severity,
        }

    def check_volume_spike(
        self, symbol: str, quote_volume: float, now: float
    ) -> dict[str, Any] | None:
        """Detect anomalous 1h quote-volume deltas vs the trailing average.

        Binance miniTicker carries rolling 24h quote volume; we sample it once
        per snapshot interval and compare hourly deltas.
        """
        dq = self.volume_track[symbol]
        if dq and now - dq[-1][0] < SNAPSHOT_INTERVAL_S:
            return None
        dq.append((now, quote_volume))
        self._trim(dq, now)
        if len(dq) < 120:  # need ~2h of samples before judging
            return None

        # delta over the last hour vs average hourly delta over history
        hour_ago = now - 3600
        base: float | None = None
        for ts, v in dq:
            if ts >= hour_ago:
                base = v
                break
        if base is None:
            return None
        recent_delta = abs(quote_volume - base)

        span_s = dq[-1][0] - dq[0][0]
        if span_s < 2 * 3600:
            return None
        total_delta = abs(dq[-1][1] - dq[0][1])
        avg_hourly_delta = total_delta / (span_s / 3600)
        if avg_hourly_delta <= 0 or recent_delta < VOLUME_SPIKE_FACTOR * avg_hourly_delta:
            return None

        return {
            "symbol": symbol.upper(),
            "quote_volume_24h": quote_volume,
            "volume_delta_1h": round(recent_delta, 2),
            "avg_hourly_delta": round(avg_hourly_delta, 2),
            "ratio": round(recent_delta / avg_hourly_delta, 2),
            "severity": "medium",
        }


async def _publish_pair(topic_base: str, symbol: str, payload: dict[str, Any]) -> None:
    """Publish to the specific topic (persisted) and the base aggregate (not)."""
    bus = get_bus()
    await bus.publish(f"{topic_base}.{symbol.upper()}", payload, source="price_watcher")
    await bus.publish(topic_base, payload, source="price_watcher", persist=False)


async def _snapshot_to_db(watcher: PriceWatcher) -> None:
    for symbol, (price, volume) in list(watcher.latest.items()):
        try:
            await execute(
                "INSERT INTO price_snapshots (symbol, price, volume_24h, ts) "
                "VALUES ($1, $2, $3, NOW())",
                symbol.upper(),
                price,
                volume,
            )
        except Exception:
            log.exception("prices.snapshot.failed", symbol=symbol)


async def _handle_message(watcher: PriceWatcher, raw: str | bytes) -> None:
    msg = json.loads(raw)
    data = msg.get("data") or {}
    if data.get("e") != "24hrMiniTicker":
        return
    symbol = str(data.get("s", "")).lower()
    if symbol not in watcher.history:
        return
    price = float(data["c"])
    quote_volume = float(data.get("q", 0.0))
    now = time.time()
    watcher.latest[symbol] = (price, quote_volume)

    move = watcher.check_price_move(symbol, price, now)
    if move is not None:
        log.info("prices.move_detected", **move)
        await _publish_pair(MARKET_PRICE_MOVE, symbol, move)

    spike = watcher.check_volume_spike(symbol, quote_volume, now)
    if spike is not None:
        log.info("prices.volume_spike_detected", **spike)
        await _publish_pair(MARKET_VOLUME_SPIKE, symbol, spike)

    if now - watcher.last_snapshot_ts >= SNAPSHOT_INTERVAL_S:
        watcher.last_snapshot_ts = now
        await _snapshot_to_db(watcher)


async def run_price_watcher(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: connect, consume, detect, reconnect with backoff. Never raises."""
    watcher = PriceWatcher()
    if not watcher.symbols:
        log.info("prices.disabled", reason="no symbols configured")
        return

    streams = "/".join(f"{s}@miniTicker" for s in watcher.symbols)
    url = f"{BINANCE_WS}?streams={streams}"
    backoff = 1.0
    log.info("prices.started", symbols=watcher.symbols, threshold_pct=watcher.threshold_pct)

    while not (stop_event and stop_event.is_set()):
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                log.info("prices.ws.connected")
                backoff = 1.0
                async for raw in ws:
                    try:
                        await _handle_message(watcher, raw)
                    except Exception:
                        log.exception("prices.message.error")
                    if stop_event and stop_event.is_set():
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("prices.ws.disconnect", err=str(e), retry_in_s=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
