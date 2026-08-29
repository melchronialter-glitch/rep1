"""Tests for the on-chain outcome classifier (auto rug labeling)."""

from __future__ import annotations

from cryptobot.agents.outcome_tracker import classify_outcome


def test_too_young_is_undecided_without_history():
    # No detection-time liquidity → nothing is judged before 24h.
    assert classify_outcome(12.0, 0.0, None) is None


def test_confirmed_lp_pull_is_judged_fast():
    # Before/after known: $50k at detection, drained at 12h → rug already.
    assert classify_outcome(12.0, 0.0, 50_000.0) == "rug"


def test_lp_pull_under_6h_is_undecided():
    # Could be a pump.fun → Raydium liquidity migration; wait.
    assert classify_outcome(3.0, 0.0, 50_000.0) is None


def test_liquidity_pulled_is_rug():
    # Had $50k at detection, now under $500 → rug.
    assert classify_outcome(30.0, 100.0, 50_000.0) == "rug"


def test_dead_after_48h_is_rug_even_without_history():
    assert classify_outcome(60.0, 50.0, None) == "rug"


def test_dead_at_30h_without_history_is_undecided():
    # No detection-time liquidity to compare and under the 48h dead floor.
    assert classify_outcome(30.0, 50.0, None) is None


def test_never_had_liquidity_is_not_a_rug_label():
    # $300 then, $100 now — nothing was pulled; wait for the 48h dead rule.
    assert classify_outcome(30.0, 100.0, 300.0) is None


def test_survivor_after_72h_is_notrug():
    assert classify_outcome(80.0, 60_000.0, 40_000.0) == "notrug"


def test_healthy_but_young_is_undecided():
    assert classify_outcome(40.0, 60_000.0, 40_000.0) is None


def test_middling_liquidity_is_undecided():
    # $3k after 4 days: neither drained nor clearly alive.
    assert classify_outcome(96.0, 3_000.0, 8_000.0) is None


def test_boundary_survivor_threshold():
    assert classify_outcome(72.0, 10_000.0, None) == "notrug"
    assert classify_outcome(72.0, 9_999.0, None) is None
