"""Feature extraction for the rug classifier.

Turns a trimmed safety report (the ``safety`` JSONB stored on every
``risk_scores`` row) plus liquidity into a fixed-order numeric vector.
``FEATURE_NAMES`` is the canonical column order — training and inference
both import it, so the two can never drift apart.

Pure functions only — no I/O.
"""

from __future__ import annotations

import math
from typing import Any

FEATURE_NAMES: list[str] = [
    "is_honeypot",
    "max_tax_pct",
    "is_mintable",
    "is_proxy",
    "can_take_back_ownership",
    "hidden_owner",
    "selfdestruct",
    "not_open_source",
    "owner_pct",
    "rugcheck_danger_count",
    "rugcheck_warn_count",
    "rugcheck_score_norm",
    "log_liquidity_usd",
    "log_holder_count",
    "unscreened",
]


def _flag(value: Any) -> float:
    """GoPlus booleans arrive as "0"/"1" strings; normalize to 0.0/1.0."""
    return 1.0 if (str(value) == "1" or value is True) else 0.0


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_features(
    safety: dict[str, Any], liquidity_usd: float | None
) -> dict[str, float]:
    """Build the feature dict for one token. Keys == FEATURE_NAMES exactly."""
    gp = safety.get("goplus") or {}
    hp = safety.get("honeypot") or {}
    rc = safety.get("rugcheck") or {}

    taxes: list[float] = []
    for key in ("buy_tax", "sell_tax"):
        v = _as_float(gp.get(key))
        if v is not None:
            taxes.append(v * 100.0)  # GoPlus taxes are fractions
    for key in ("buy_tax_pct", "sell_tax_pct"):
        v = _as_float(hp.get(key))
        if v is not None:
            taxes.append(v)

    owner_pct = max(
        (_as_float(gp.get(k)) or 0.0) for k in ("owner_percent", "creator_percent")
    ) * 100.0

    danger = sum(
        1 for r in (rc.get("risks") or []) if str(r.get("level") or "").lower() == "danger"
    )
    warn = sum(
        1 for r in (rc.get("risks") or []) if str(r.get("level") or "").lower() == "warn"
    )

    liquidity = max(liquidity_usd or 0.0, 0.0)
    holders = _as_float(gp.get("holder_count")) or 0.0

    return {
        "is_honeypot": 1.0 if (hp.get("is_honeypot") is True or _flag(gp.get("is_honeypot"))) else 0.0,
        "max_tax_pct": max(taxes) if taxes else 0.0,
        "is_mintable": _flag(gp.get("is_mintable")),
        "is_proxy": _flag(gp.get("is_proxy")),
        "can_take_back_ownership": _flag(gp.get("can_take_back_ownership")),
        "hidden_owner": _flag(gp.get("hidden_owner")),
        "selfdestruct": _flag(gp.get("selfdestruct")),
        "not_open_source": 1.0 if (gp and str(gp.get("is_open_source")) == "0") else 0.0,
        "owner_pct": owner_pct,
        "rugcheck_danger_count": float(danger),
        "rugcheck_warn_count": float(warn),
        "rugcheck_score_norm": _as_float(rc.get("score_norm")) or 0.0,
        "log_liquidity_usd": math.log10(liquidity + 1.0),
        "log_holder_count": math.log10(max(holders, 0.0) + 1.0),
        "unscreened": 0.0 if (gp or hp or rc) else 1.0,
    }


def to_vector(features: dict[str, float]) -> list[float]:
    """Fixed-order vector for sklearn, in FEATURE_NAMES order."""
    return [float(features.get(name, 0.0)) for name in FEATURE_NAMES]
