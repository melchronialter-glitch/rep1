"""Tests for the indicator engine's pure math functions."""

from __future__ import annotations

import math

from cryptobot.agents.indicator_engine import (
    _bollinger,
    _compute_bias,
    _detect_signals,
    _ema,
    _macd,
    _rsi,
)

# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


def test_ema_constant_series():
    vals = [100.0] * 30
    ema = _ema(vals, 12)
    assert math.isnan(ema[10])  # before seed
    assert ema[-1] == 100.0  # constant in → constant out


def test_ema_length_matches_input():
    vals = [float(i) for i in range(50)]
    assert len(_ema(vals, 12)) == 50


def test_ema_too_short():
    assert all(math.isnan(v) for v in _ema([1.0, 2.0], 12))


def test_ema_follows_trend():
    rising = [float(i) for i in range(1, 60)]
    ema = _ema(rising, 12)
    # EMA lags a rising series: below price, but rising.
    assert ema[-1] < rising[-1]
    assert ema[-1] > ema[-10]


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 40)]
    rsi = _rsi(closes, 14)
    assert rsi[-1] == 100.0


def test_rsi_all_losses_is_0():
    closes = [float(i) for i in range(40, 1, -1)]
    rsi = _rsi(closes, 14)
    assert rsi[-1] < 1.0


def test_rsi_flat_after_alternating_is_mid():
    closes = [100.0 + (1 if i % 2 == 0 else -1) for i in range(60)]
    rsi = _rsi(closes, 14)
    # Equal gains and losses → RSI near 50.
    assert 40.0 < rsi[-1] < 60.0


def test_rsi_bounds():
    closes = [100.0, 102.0, 99.0, 105.0, 103.0, 108.0, 104.0, 110.0,
              107.0, 112.0, 109.0, 115.0, 111.0, 118.0, 114.0, 120.0]
    rsi = _rsi(closes, 14)
    valid = [v for v in rsi if not math.isnan(v)]
    assert valid, "expected at least one valid RSI value"
    assert all(0.0 <= v <= 100.0 for v in valid)


def test_rsi_too_short_is_all_nan():
    assert all(math.isnan(v) for v in _rsi([1.0, 2.0, 3.0], 14))


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def test_macd_constant_series_is_zero():
    closes = [100.0] * 60
    macd_line, signal_line, hist = _macd(closes)
    assert abs(macd_line[-1]) < 1e-9
    assert abs(signal_line[-1]) < 1e-9
    assert abs(hist[-1]) < 1e-9
    assert len(macd_line) == len(signal_line) == len(hist) == 60


def test_macd_positive_in_uptrend():
    closes = [100.0 * (1.01 ** i) for i in range(80)]
    macd_line, _, _ = _macd(closes)
    assert macd_line[-1] > 0  # fast EMA above slow EMA in an uptrend


def test_macd_negative_in_downtrend():
    closes = [100.0 * (0.99 ** i) for i in range(80)]
    macd_line, _, _ = _macd(closes)
    assert macd_line[-1] < 0


# ---------------------------------------------------------------------------
# Bollinger
# ---------------------------------------------------------------------------


def test_bollinger_constant_series_bands_collapse():
    closes = [50.0] * 40
    upper, mid, lower = _bollinger(closes)
    assert upper[-1] == mid[-1] == lower[-1] == 50.0


def test_bollinger_band_ordering():
    closes = [100.0 + (5 if i % 3 == 0 else -3) for i in range(40)]
    upper, mid, lower = _bollinger(closes)
    assert upper[-1] > mid[-1] > lower[-1]


def test_bollinger_nan_before_period():
    closes = [float(i) for i in range(40)]
    upper, _, _ = _bollinger(closes, period=20)
    assert math.isnan(upper[10])
    assert not math.isnan(upper[19])


# ---------------------------------------------------------------------------
# Signal detection + bias
# ---------------------------------------------------------------------------


def _flat_setup(n: int = 60) -> tuple[list[float], list[float], list[float], list[float], list[float], list[float]]:
    closes = [100.0] * n
    rsi = _rsi(closes, 14)
    macd_line, _, hist = _macd(closes)
    upper, _, lower = _bollinger(closes)
    return closes, rsi, macd_line, hist, upper, lower


def test_detect_signals_oversold():
    # Steady decline → RSI floor → rsi_oversold present.
    closes = [float(200 - i) for i in range(60)]
    rsi = _rsi(closes, 14)
    macd_line, _, hist = _macd(closes)
    upper, _, lower = _bollinger(closes)
    signals = _detect_signals(closes, rsi, macd_line, hist, upper, lower, 1.0, 14)
    assert "rsi_oversold" in signals


def test_detect_signals_volume_spike():
    closes, rsi, macd_line, hist, upper, lower = _flat_setup()
    signals = _detect_signals(closes, rsi, macd_line, hist, upper, lower, 5.0, 14)
    assert "volume_spike" in signals


def test_compute_bias():
    assert _compute_bias(["rsi_oversold", "bb_lower_touch"]) == "bullish"
    assert _compute_bias(["rsi_overbought"]) == "bearish"
    assert _compute_bias(["volume_spike"]) == "neutral"
    assert _compute_bias([]) == "neutral"
