"""Tests for the rug-classifier feature extraction."""

from __future__ import annotations

import math

from cryptobot.ml.features import FEATURE_NAMES, extract_features, to_vector


def test_clean_token_features():
    safety = {
        "goplus": {
            "is_honeypot": "0",
            "buy_tax": "0",
            "sell_tax": "0",
            "is_mintable": "0",
            "is_open_source": "1",
            "owner_percent": "0.02",
            "holder_count": "500",
        }
    }
    f = extract_features(safety, 100_000.0)
    assert f["is_honeypot"] == 0.0
    assert f["max_tax_pct"] == 0.0
    assert f["owner_pct"] == 2.0
    assert f["not_open_source"] == 0.0
    assert f["unscreened"] == 0.0
    assert f["log_liquidity_usd"] == math.log10(100_001.0)


def test_honeypot_token_features():
    safety = {
        "goplus": {"is_honeypot": "1", "buy_tax": "0.5", "sell_tax": "0.99"},
        "honeypot": {"is_honeypot": True, "buy_tax_pct": 50.0, "sell_tax_pct": 99.0},
    }
    f = extract_features(safety, 100.0)
    assert f["is_honeypot"] == 1.0
    assert f["max_tax_pct"] == 99.0


def test_rugcheck_risk_counts():
    safety = {
        "rugcheck": {
            "score_norm": 80,
            "risks": [
                {"name": "a", "level": "danger"},
                {"name": "b", "level": "danger"},
                {"name": "c", "level": "warn"},
            ],
        }
    }
    f = extract_features(safety, None)
    assert f["rugcheck_danger_count"] == 2.0
    assert f["rugcheck_warn_count"] == 1.0
    assert f["rugcheck_score_norm"] == 80.0


def test_unscreened_token():
    f = extract_features({}, None)
    assert f["unscreened"] == 1.0
    assert f["log_liquidity_usd"] == 0.0


def test_vector_order_matches_feature_names():
    f = extract_features({}, 1000.0)
    assert set(f.keys()) == set(FEATURE_NAMES)
    vec = to_vector(f)
    assert len(vec) == len(FEATURE_NAMES)
    assert vec[FEATURE_NAMES.index("log_liquidity_usd")] == f["log_liquidity_usd"]


def test_missing_feature_defaults_to_zero():
    vec = to_vector({})
    assert vec == [0.0] * len(FEATURE_NAMES)


def test_goplus_string_flags():
    # GoPlus sends booleans as "0"/"1" strings — both forms must work.
    f1 = extract_features({"goplus": {"is_mintable": "1"}}, None)
    f2 = extract_features({"goplus": {"is_mintable": True}}, None)
    assert f1["is_mintable"] == 1.0
    assert f2["is_mintable"] == 1.0
