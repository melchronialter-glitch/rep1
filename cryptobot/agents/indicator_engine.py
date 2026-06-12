"""Indicator engine — computes technical indicators from price_snapshots and
publishes buy/sell signal candidates.

Pure Python math only (no TA-Lib, no numpy). Runs every 5 minutes for each
symbol in ``price_symbol_list``, fetches the last 200 price_snapshots rows per
symbol, computes RSI(14), EMA(12/26), MACD, Bollinger Bands(20), and a volume
profile, then applies signal rules to publish ``market.indicator_signal.{sym}``.

The pure math functions (_rsi, _ema, _macd, _bollinger) are module-level so
they can be unit-tested independently.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from typing import Any

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute, fetch
from cryptobot.logging import get_logger
from cryptobot.topics import (
    MARKET_INDICATOR_SIGNAL,
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MEDIUM,
    SIGNAL_ALERT_STRICT,
)

log = get_logger(__name__)

POLL_INTERVAL_S = 300        # 5 minutes
MIN_ROWS = 50                # skip symbol if fewer rows
FETCH_ROWS = 200             # how many rows to pull per symbol
BB_PERIOD = 20               # Bollinger Band period
BB_STDDEV_MULT = 2.0
VOLUME_SPIKE_FACTOR = 3.0    # 1h volume vs 7-day avg


# ---------------------------------------------------------------------------
# Pure math helpers — standalone so they can be unit-tested.
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> list[float]:
    """Compute EMA for ``values`` using a standard multiplier (2/(period+1)).

    Returns a list of the same length; the first ``period-1`` entries are None
    padded as float('nan') until the seed SMA is established.
    """
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1)
    result: list[float] = [float("nan")] * len(values)
    # Seed with SMA of first ``period`` values.
    seed_end = period - 1
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[seed_end] = seed
    for i in range(seed_end + 1, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def _rsi(closes: list[float], period: int = 14) -> list[float]:
    """Compute RSI(period) over a list of close prices.

    Returns a list of the same length; early entries are NaN.
    Uses Wilder's smoothed average (identical to standard RSI).
    """
    if len(closes) < period + 1:
        return [float("nan")] * len(closes)

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    result: list[float] = [float("nan")] * len(closes)

    # Initial Wilder averages over first ``period`` deltas.
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rs_to_rsi(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    result[period] = _rs_to_rsi(avg_gain, avg_loss)

    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        result[i] = _rs_to_rsi(avg_gain, avg_loss)

    return result


def _macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float], list[float], list[float]]:
    """Compute MACD line, signal line, and histogram.

    Returns three lists of the same length as ``closes``, NaN-padded at the
    start.
    """
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    macd_line: list[float] = []
    for f, s in zip(ema_fast, ema_slow):
        if math.isnan(f) or math.isnan(s):
            macd_line.append(float("nan"))
        else:
            macd_line.append(f - s)

    # Signal = EMA(signal) of MACD, computed only over valid MACD values.
    # We need at least ``signal`` consecutive valid MACD values.
    signal_line = [float("nan")] * len(macd_line)
    valid_macd = [(i, v) for i, v in enumerate(macd_line) if not math.isnan(v)]
    if len(valid_macd) >= signal:
        indices = [iv[0] for iv in valid_macd]
        vals = [iv[1] for iv in valid_macd]
        ema_sig = _ema(vals, signal)
        for j, idx in enumerate(indices):
            if not math.isnan(ema_sig[j]):
                signal_line[idx] = ema_sig[j]

    histogram: list[float] = []
    for m, s in zip(macd_line, signal_line):
        if math.isnan(m) or math.isnan(s):
            histogram.append(float("nan"))
        else:
            histogram.append(m - s)

    return macd_line, signal_line, histogram


def _bollinger(
    closes: list[float],
    period: int = 20,
    mult: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Compute Bollinger Bands (upper, mid, lower).

    Returns three lists of the same length as ``closes``, NaN-padded.
    """
    n = len(closes)
    upper = [float("nan")] * n
    mid = [float("nan")] * n
    lower = [float("nan")] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = math.sqrt(variance)
        mid[i] = sma
        upper[i] = sma + mult * std
        lower[i] = sma - mult * std
    return upper, mid, lower


# ---------------------------------------------------------------------------
# Volume helpers
# ---------------------------------------------------------------------------

def _volume_ratio(
    rows: list[dict[str, Any]],
    current_1h_volume: float,
) -> float:
    """Return current_1h_volume / 7-day avg hourly volume, or 1.0 if not enough data."""
    # rows ordered oldest-first; use volume_24h as a proxy for cumulative vol
    # We want the average of 1h-window volume deltas over the last 7 days.
    seven_days_ago_cutoff = 7 * 24 * 3600
    if len(rows) < 2:
        return 1.0

    # Estimate hourly deltas from the 1-minute snapshots
    hourly_deltas: list[float] = []
    bucket_start_ts: float | None = None
    bucket_start_vol: float | None = None

    for row in rows:
        ts: float = row["ts"].timestamp() if hasattr(row["ts"], "timestamp") else float(row["ts"])
        vol: float = float(row.get("volume_24h") or 0.0)
        if bucket_start_ts is None:
            bucket_start_ts = ts
            bucket_start_vol = vol
            continue
        elapsed = ts - bucket_start_ts
        if elapsed >= 3600:
            delta = abs(vol - (bucket_start_vol or 0.0))
            hourly_deltas.append(delta)
            bucket_start_ts = ts
            bucket_start_vol = vol

    if not hourly_deltas:
        return 1.0

    avg_hourly = sum(hourly_deltas) / len(hourly_deltas)
    if avg_hourly <= 0:
        return 1.0
    return current_1h_volume / avg_hourly


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def _detect_signals(
    closes: list[float],
    rsi_vals: list[float],
    macd_line: list[float],
    histogram: list[float],
    bb_upper: list[float],
    bb_lower: list[float],
    volume_ratio: float,
    rsi_period: int,
) -> list[str]:
    """Apply signal rules and return a list of signal name strings."""
    signals: list[str] = []
    if not closes:
        return signals

    current_price = closes[-1]
    current_rsi = rsi_vals[-1] if not math.isnan(rsi_vals[-1]) else 50.0
    prev_hist = histogram[-2] if len(histogram) >= 2 and not math.isnan(histogram[-2]) else float("nan")
    curr_hist = histogram[-1] if not math.isnan(histogram[-1]) else float("nan")
    curr_bb_upper = bb_upper[-1] if not math.isnan(bb_upper[-1]) else float("nan")
    curr_bb_lower = bb_lower[-1] if not math.isnan(bb_lower[-1]) else float("nan")

    # RSI signals
    if current_rsi < 30:
        signals.append("rsi_oversold")
    if current_rsi > 70:
        signals.append("rsi_overbought")

    # MACD crossover
    if not math.isnan(prev_hist) and not math.isnan(curr_hist):
        if prev_hist < 0 and curr_hist >= 0:
            signals.append("macd_bullish_cross")
        elif prev_hist > 0 and curr_hist <= 0:
            signals.append("macd_bearish_cross")

    # Bollinger Band touches
    if not math.isnan(curr_bb_lower) and current_price <= curr_bb_lower:
        signals.append("bb_lower_touch")
    if not math.isnan(curr_bb_upper) and current_price >= curr_bb_upper:
        signals.append("bb_upper_touch")

    # Volume spike
    if volume_ratio >= VOLUME_SPIKE_FACTOR:
        signals.append("volume_spike")

    return signals


def _compute_bias(signals: list[str]) -> str:
    bullish_signals = {"rsi_oversold", "macd_bullish_cross", "bb_lower_touch"}
    bearish_signals = {"rsi_overbought", "macd_bearish_cross", "bb_upper_touch"}
    bull = sum(1 for s in signals if s in bullish_signals)
    bear = sum(1 for s in signals if s in bearish_signals)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------

async def _process_symbol(symbol: str, settings: Any) -> None:
    """Fetch rows, compute indicators, and publish signal for one symbol."""
    rows = await fetch(
        "SELECT price, volume_24h, ts FROM price_snapshots "
        "WHERE symbol = $1 ORDER BY ts DESC LIMIT $2",
        symbol.upper(),
        FETCH_ROWS,
    )
    if len(rows) < MIN_ROWS:
        log.debug("indicator_engine.skip.insufficient_data", symbol=symbol, rows=len(rows))
        return

    # Reverse so oldest-first for indicator math.
    rows = list(reversed(rows))
    closes = [float(r["price"]) for r in rows]
    current_price = closes[-1]

    rsi_period = settings.indicator_rsi_period
    ema_short = settings.indicator_ema_short
    ema_long = settings.indicator_ema_long
    macd_sig_period = settings.indicator_macd_signal

    rsi_vals = _rsi(closes, rsi_period)
    ema12 = _ema(closes, ema_short)
    ema26 = _ema(closes, ema_long)
    macd_line, signal_line, histogram = _macd(closes, ema_short, ema_long, macd_sig_period)
    bb_upper, bb_mid, bb_lower = _bollinger(closes, BB_PERIOD, BB_STDDEV_MULT)

    # Volume: estimate 1h volume from the most recent 60 rows (~60 minutes of 1-min snapshots).
    recent_vols = [float(r.get("volume_24h") or 0.0) for r in rows[-61:]]
    if len(recent_vols) >= 2:
        current_1h_volume = abs(recent_vols[-1] - recent_vols[0])
    else:
        current_1h_volume = 0.0
    vol_ratio = _volume_ratio(rows, current_1h_volume)

    current_rsi = rsi_vals[-1] if not math.isnan(rsi_vals[-1]) else 50.0
    current_macd = macd_line[-1] if not math.isnan(macd_line[-1]) else 0.0
    current_macd_sig = signal_line[-1] if not math.isnan(signal_line[-1]) else 0.0
    current_hist = histogram[-1] if not math.isnan(histogram[-1]) else 0.0
    current_ema12 = ema12[-1] if not math.isnan(ema12[-1]) else current_price
    current_ema26 = ema26[-1] if not math.isnan(ema26[-1]) else current_price
    current_bb_upper = bb_upper[-1] if not math.isnan(bb_upper[-1]) else current_price
    current_bb_lower = bb_lower[-1] if not math.isnan(bb_lower[-1]) else current_price
    current_bb_mid = bb_mid[-1] if not math.isnan(bb_mid[-1]) else current_price

    signals = _detect_signals(
        closes, rsi_vals, macd_line, histogram, bb_upper, bb_lower, vol_ratio, rsi_period
    )
    bias = _compute_bias(signals)

    payload: dict[str, Any] = {
        "symbol": symbol.lower(),
        "price": round(current_price, 6),
        "rsi": round(current_rsi, 2),
        "macd": round(current_macd, 6),
        "macd_signal": round(current_macd_sig, 6),
        "macd_histogram": round(current_hist, 6),
        "ema12": round(current_ema12, 6),
        "ema26": round(current_ema26, 6),
        "bb_upper": round(current_bb_upper, 6),
        "bb_lower": round(current_bb_lower, 6),
        "bb_mid": round(current_bb_mid, 6),
        "volume_ratio": round(vol_ratio, 3),
        "signals": signals,
        "bias": bias,
    }

    bus = get_bus()
    sym_upper = symbol.upper()
    specific_topic = f"{MARKET_INDICATOR_SIGNAL}.{sym_upper}"

    # Dual publish: specific (high-frequency, no persist) + base aggregate (no persist).
    await bus.publish(specific_topic, payload, source="indicator_engine", persist=False)
    await bus.publish(MARKET_INDICATOR_SIGNAL, payload, source="indicator_engine", persist=False)

    log.debug(
        "indicator_engine.published",
        symbol=symbol,
        rsi=round(current_rsi, 1),
        bias=bias,
        signals=signals,
    )

    # Persist to indicator_signals table for ML training.
    if signals:
        bb_range = current_bb_upper - current_bb_lower
        bb_position = (
            (current_price - current_bb_lower) / bb_range
            if bb_range > 0
            else 0.5
        )
        try:
            await execute(
                "INSERT INTO indicator_signals "
                "(id, symbol, rsi, macd, macd_histogram, bb_position, volume_ratio, signals, bias, price) "
                "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)",
                str(uuid.uuid4()),
                sym_upper,
                round(current_rsi, 4),
                round(current_macd, 6),
                round(current_hist, 6),
                round(bb_position, 4),
                round(vol_ratio, 4),
                str(signals).replace("'", '"'),
                bias,
                round(current_price, 6),
            )
        except Exception:
            log.exception("indicator_engine.persist_failed", symbol=symbol)


async def run_indicator_engine(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: every 5 minutes, compute indicators for all configured symbols."""
    settings = get_settings()
    symbols = settings.price_symbol_list
    if not symbols:
        log.info("indicator_engine.disabled", reason="no symbols configured")
        return

    log.info("indicator_engine.started", symbols=symbols, poll_interval_s=POLL_INTERVAL_S)

    while not (stop_event and stop_event.is_set()):
        for symbol in symbols:
            try:
                await _process_symbol(symbol, settings)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("indicator_engine.symbol_error", symbol=symbol)
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.sleep(POLL_INTERVAL_S)),
                timeout=POLL_INTERVAL_S + 5,
            )
        except (TimeoutError, asyncio.TimeoutError):
            pass
        except asyncio.CancelledError:
            raise
        if stop_event and stop_event.is_set():
            break
