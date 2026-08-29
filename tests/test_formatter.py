"""Unit tests for the new-pair alert card risk line (Phase D)."""

from __future__ import annotations

from cryptobot.bus import Event
from cryptobot.reporters.formatter import render_alert


def _event(payload: dict) -> Event:
    return Event(topic="signal.alert.firehose", source="test", payload=payload)


def _base_payload() -> dict:
    return {
        "chain": "ethereum",
        "symbol": "TEST",
        "token_address": "0x" + "a" * 40,
        "pair_address": "0x" + "b" * 40,
        "liquidity_usd": 12_345.0,
    }


def test_risk_line_with_top_three_reasons() -> None:
    p = _base_payload()
    p["risk_score"] = 45
    p["risk_reasons"] = ["mintable", "not open source", "liquidity < $1k", "extra"]
    out = render_alert(_event(p))
    assert "risk: 45/100 (mintable, not open source, liquidity < $1k)" in out["body"]
    assert "extra" not in out["body"]
    assert not out["title"].startswith("⚠️")


def test_risk_line_without_reasons() -> None:
    p = _base_payload()
    p["risk_score"] = 0
    p["risk_reasons"] = []
    out = render_alert(_event(p))
    assert "risk: 0/100" in out["body"]
    assert "risk: 0/100 (" not in out["body"]


def test_high_risk_title_prefix() -> None:
    p = _base_payload()
    p["risk_score"] = 85
    p["risk_reasons"] = ["honeypot"]
    out = render_alert(_event(p))
    assert out["title"].startswith("⚠️ HIGH RISK ")
    assert "risk: 85/100 (honeypot)" in out["body"]


def test_no_risk_line_when_score_absent() -> None:
    out = render_alert(_event(_base_payload()))
    assert "risk:" not in out["body"]
    assert not out["title"].startswith("⚠️")
