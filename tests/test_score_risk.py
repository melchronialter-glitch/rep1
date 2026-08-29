"""Unit tests for the pure hard-rule risk scorer (Phase D)."""

from __future__ import annotations

from cryptobot.agents.rug_detector import _route, score_risk
from cryptobot.topics import (
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MEDIUM,
    SIGNAL_ALERT_STRICT,
)


def _payload(liquidity_usd: float | None = 100_000.0) -> dict:
    return {"chain": "ethereum", "token_address": "0x" + "1" * 40, "liquidity_usd": liquidity_usd}


def test_honeypot_from_honeypot_is() -> None:
    safety = {"honeypot": {"is_honeypot": True}}
    score, reasons = score_risk(_payload(), safety)
    assert score == 70
    assert "honeypot" in reasons


def test_honeypot_from_goplus_flag() -> None:
    safety = {"goplus": {"is_honeypot": "1", "is_open_source": "1"}}
    score, reasons = score_risk(_payload(), safety)
    assert score == 70
    assert "honeypot" in reasons


def test_tax_over_10_percent() -> None:
    # GoPlus taxes are fractions: 0.15 == 15%
    safety = {"goplus": {"buy_tax": "0.15", "is_open_source": "1"}}
    score, reasons = score_risk(_payload(), safety)
    assert score == 25
    assert any("tax" in r for r in reasons)


def test_tax_over_30_percent_not_double_counted() -> None:
    safety = {"honeypot": {"is_honeypot": False, "sell_tax_pct": 45.0}}
    score, reasons = score_risk(_payload(), safety)
    assert score == 50  # the >30% bracket only, not 25 + 50
    assert any(">30%" in r for r in reasons)


def test_owner_concentration_tiers() -> None:
    base = {"is_open_source": "1"}
    # GoPlus percents are fractions: 0.25 == 25%
    score, reasons = score_risk(_payload(), {"goplus": {**base, "owner_percent": "0.25"}})
    assert score == 25
    assert any(">20%" in r for r in reasons)

    score, reasons = score_risk(_payload(), {"goplus": {**base, "creator_percent": "0.6"}})
    assert score == 50
    assert any(">50%" in r for r in reasons)


def test_goplus_contract_flags_additive() -> None:
    safety = {
        "goplus": {
            "is_mintable": "1",          # +20
            "is_proxy": "1",             # +15
            "hidden_owner": "1",         # +20
            "is_open_source": "0",       # +15
        }
    }
    score, reasons = score_risk(_payload(), safety)
    assert score == 70
    assert {"mintable", "proxy contract", "hidden owner", "not open source"} <= set(reasons)


def test_rugcheck_contribution_capped_at_60() -> None:
    safety = {
        "rugcheck": {
            "score_norm": 90,
            "risks": [
                {"name": "freeze authority", "level": "danger"},
                {"name": "mint authority", "level": "danger"},
                {"name": "low lp", "level": "warn"},
            ],
        }
    }
    score, reasons = score_risk(_payload(), safety)
    assert score == 60  # 50 + 50 + 20 = 120, capped at 60
    assert any(r.startswith("rugcheck danger") for r in reasons)


def test_unscreened_pumpfun_token() -> None:
    """A fresh pump.fun mint: no safety data, no liquidity → unscreened."""
    score, reasons = score_risk(
        {"chain": "solana", "venue": "pump.fun", "token_address": "x"}, {}
    )
    assert score == 30  # +20 liquidity < $1k, +10 unscreened
    assert "unscreened" in reasons
    assert "liquidity < $1k" in reasons
    # ...and it must land in the firehose, not strict/medium.
    assert _route(score, 0.0) == SIGNAL_ALERT_FIREHOSE


def test_score_caps_at_100() -> None:
    safety = {
        "honeypot": {"is_honeypot": True, "sell_tax_pct": 99.0},
        "goplus": {
            "selfdestruct": "1",
            "is_mintable": "1",
            "hidden_owner": "1",
            "owner_percent": "0.9",
            "is_open_source": "0",
        },
    }
    score, _ = score_risk(_payload(liquidity_usd=0.0), safety)
    assert score == 100


def test_clean_token_scores_zero() -> None:
    safety = {
        "goplus": {
            "is_honeypot": "0",
            "buy_tax": "0",
            "sell_tax": "0",
            "is_mintable": "0",
            "is_open_source": "1",
            "owner_percent": "0",
        }
    }
    score, reasons = score_risk(_payload(liquidity_usd=100_000.0), safety)
    assert score == 0
    assert reasons == []


def test_routing_tiers() -> None:
    assert _route(75, 1_000_000.0) == SIGNAL_ALERT_FIREHOSE  # high risk wins
    assert _route(10, 100_000.0) == SIGNAL_ALERT_STRICT
    assert _route(40, 20_000.0) == SIGNAL_ALERT_MEDIUM
    assert _route(40, 5_000.0) == SIGNAL_ALERT_FIREHOSE
    assert _route(60, 1_000_000.0) == SIGNAL_ALERT_FIREHOSE
