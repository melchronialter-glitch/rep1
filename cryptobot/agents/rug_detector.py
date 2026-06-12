"""Rug detector agent — Phase D deterministic risk scoring for new pairs.

Takes over ``chain.new_pair`` routing from triage. Per event:

1. ``tier_hint == "ignore"`` → dropped (already persisted by the watcher).
2. Best-effort DexScreener enrichment (:func:`cryptobot.intel.enrich.enrich_new_pair`).
3. Safety screen via :func:`cryptobot.intel.safety.safety_report` — skipped
   for fresh pump.fun mints (the safety APIs have nothing that early), which
   get neutral defaults instead.
4. Hard-rule risk score 0–100 from :func:`score_risk` (pure, additive,
   capped) with human-readable reasons.
5. Tiered routing:
   - score >= 70 → firehose only (formatter prefixes "⚠️ HIGH RISK")
   - score < 30 and liquidity >= $50k → strict (quality find)
   - score < 50 and liquidity >= $10k → medium
   - else → firehose
6. The score row is persisted to ``risk_scores`` — the Phase H ML training
   set — best-effort.

The xgboost layer (ARCHITECTURE §6, layer 2) lands in Phase H; this is
layer 1 (hard rules) only.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from cryptobot.bus import get_bus
from cryptobot.db import execute
from cryptobot.intel.enrich import enrich_new_pair
from cryptobot.intel.safety import safety_report
from cryptobot.logging import get_logger
from cryptobot.topics import (
    CHAIN_NEW_PAIR,
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MEDIUM,
    SIGNAL_ALERT_STRICT,
)

log = get_logger(__name__)

# Routing thresholds
HIGH_RISK_SCORE = 70
STRICT_MAX_SCORE = 30
STRICT_MIN_LIQUIDITY_USD = 50_000.0
MEDIUM_MAX_SCORE = 50
MEDIUM_MIN_LIQUIDITY_USD = 10_000.0
LOW_LIQUIDITY_USD = 1_000.0

# Per-source cap on the RugCheck risks contribution
RUGCHECK_CONTRIBUTION_CAP = 50 + 10  # 60


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flag(value: Any) -> bool:
    """GoPlus boolean flags arrive as "0"/"1" strings."""
    return str(value) == "1" or value is True


def _max_tax_pct(safety: dict[str, Any]) -> float | None:
    """Highest buy/sell tax across sources, as a percentage (5.0 == 5%)."""
    taxes: list[float] = []
    gp = safety.get("goplus") or {}
    for key in ("buy_tax", "sell_tax"):
        v = _as_float(gp.get(key))
        if v is not None:
            taxes.append(v * 100.0)  # GoPlus taxes are fractions (0.05 == 5%)
    hp = safety.get("honeypot") or {}
    for key in ("buy_tax_pct", "sell_tax_pct"):
        v = _as_float(hp.get(key))
        if v is not None:
            taxes.append(v)  # Honeypot.is taxes are already percentages
    return max(taxes) if taxes else None


def score_risk(payload: dict[str, Any], safety: dict[str, Any]) -> tuple[int, list[str]]:
    """Deterministic hard-rule risk score for a new pair. Pure function.

    Additive rules, capped at 100. Returns ``(score, reasons)``.
    """
    score = 0
    reasons: list[str] = []
    gp = safety.get("goplus") or {}
    hp = safety.get("honeypot") or {}
    rc = safety.get("rugcheck") or {}

    # Honeypot — from either source.
    if hp.get("is_honeypot") is True or _flag(gp.get("is_honeypot")):
        score += 70
        reasons.append("honeypot")

    # Taxes (tiered: take the worse bracket only).
    max_tax = _max_tax_pct(safety)
    if max_tax is not None:
        if max_tax > 30:
            score += 50
            reasons.append(f"tax {max_tax:.0f}% (>30%)")
        elif max_tax > 10:
            score += 25
            reasons.append(f"tax {max_tax:.0f}% (>10%)")

    # GoPlus contract flags.
    for field, points, label in (
        ("is_mintable", 20, "mintable"),
        ("is_proxy", 15, "proxy contract"),
        ("can_take_back_ownership", 20, "can take back ownership"),
        ("hidden_owner", 20, "hidden owner"),
        ("selfdestruct", 40, "selfdestruct"),
    ):
        if _flag(gp.get(field)):
            score += points
            reasons.append(label)

    # Owner/creator concentration (GoPlus percents are fractions: 0.5 == 50%).
    owner_pct = max(
        (_as_float(gp.get(k)) or 0.0) for k in ("owner_percent", "creator_percent")
    ) * 100.0
    if owner_pct > 50:
        score += 50
        reasons.append(f"owner/creator holds {owner_pct:.0f}% (>50%)")
    elif owner_pct > 20:
        score += 25
        reasons.append(f"owner/creator holds {owner_pct:.0f}% (>20%)")

    # Source code
    if gp and str(gp.get("is_open_source")) == "0":
        score += 15
        reasons.append("not open source")

    # RugCheck risk items: danger +50, warn +20 each, contribution capped at 60.
    rc_points = 0
    for risk in rc.get("risks") or []:
        level = str(risk.get("level") or "").lower()
        name = risk.get("name") or "unnamed risk"
        if level == "danger":
            rc_points += 50
            reasons.append(f"rugcheck danger: {name}")
        elif level == "warn":
            rc_points += 20
            reasons.append(f"rugcheck warn: {name}")
    score += min(rc_points, RUGCHECK_CONTRIBUTION_CAP)

    # Liquidity floor.
    liquidity = _as_float(payload.get("liquidity_usd")) or 0.0
    if liquidity < LOW_LIQUIDITY_USD:
        score += 20
        reasons.append("liquidity < $1k")

    # No safety data at all → mild penalty so unknowns don't look clean.
    if not (gp or hp or rc):
        score += 10
        reasons.append("unscreened")

    return min(score, 100), reasons


def _route(score: int, liquidity_usd: float) -> str:
    """Map (score, liquidity) to an alert topic per the Phase D tier rules."""
    if score >= HIGH_RISK_SCORE:
        return SIGNAL_ALERT_FIREHOSE
    if score < STRICT_MAX_SCORE and liquidity_usd >= STRICT_MIN_LIQUIDITY_USD:
        return SIGNAL_ALERT_STRICT
    if score < MEDIUM_MAX_SCORE and liquidity_usd >= MEDIUM_MIN_LIQUIDITY_USD:
        return SIGNAL_ALERT_MEDIUM
    return SIGNAL_ALERT_FIREHOSE


def _trim_safety(safety: dict[str, Any]) -> dict[str, Any]:
    """Trim the merged safety report to alert-payload essentials."""
    out: dict[str, Any] = {"sources": safety.get("sources") or []}
    gp = safety.get("goplus")
    if gp:
        out["goplus"] = {
            k: gp[k]
            for k in (
                "is_honeypot", "buy_tax", "sell_tax", "is_mintable", "is_proxy",
                "is_open_source", "can_take_back_ownership", "hidden_owner",
                "selfdestruct", "owner_percent", "creator_percent", "holder_count",
            )
            if k in gp
        }
    hp = safety.get("honeypot")
    if hp:
        out["honeypot"] = {
            k: hp[k]
            for k in ("is_honeypot", "buy_tax_pct", "sell_tax_pct", "risk")
            if k in hp
        }
    rc = safety.get("rugcheck")
    if rc:
        out["rugcheck"] = {
            "score_norm": rc.get("score_norm"),
            "risks": [
                {"name": r.get("name"), "level": r.get("level")}
                for r in (rc.get("risks") or [])[:5]
            ],
        }
    return out


async def _persist_score(
    payload: dict[str, Any],
    score: int,
    reasons: list[str],
    safety: dict[str, Any],
    routed_to: str,
) -> None:
    """Write a risk_scores row (Phase H training data). Best-effort."""
    try:
        await execute(
            "INSERT INTO risk_scores "
            "(id, chain, address, pair_address, score, reasons, safety, "
            " liquidity_usd, routed_to) "
            "VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)",
            str(uuid.uuid4()),
            payload.get("chain"),
            payload.get("token_address") or payload.get("token0"),
            payload.get("pair_address"),
            score,
            json.dumps(reasons),
            json.dumps(safety, default=str),
            _as_float(payload.get("liquidity_usd")),
            routed_to,
        )
    except Exception:
        log.exception(
            "rug_detector.persist_failed",
            chain=payload.get("chain"),
            address=payload.get("token_address"),
        )


async def _handle_new_pair(payload: dict[str, Any]) -> None:
    """Enrich → screen → score → route → persist one new-pair event."""
    bus = get_bus()
    if payload.get("tier_hint") == "ignore":
        log.debug("rug_detector.ignored", chain=payload.get("chain"))
        return

    payload = await enrich_new_pair(payload)  # never raises
    address = payload.get("token_address") or payload.get("token0")
    chain = str(payload.get("chain") or "")

    if payload.get("venue") == "pump.fun":
        # Too new — the safety APIs won't know the mint yet. Neutral default.
        safety: dict[str, Any] = {"chain": chain, "address": address, "sources": []}
    else:
        safety = await safety_report(chain, address or "")

    score, reasons = score_risk(payload, safety)
    liquidity = _as_float(payload.get("liquidity_usd")) or 0.0
    target = _route(score, liquidity)

    out = dict(payload)
    out["risk_score"] = score
    out["risk_reasons"] = reasons
    out["safety"] = _trim_safety(safety)
    await bus.publish(target, out, source="rug_detector:chain.new_pair")
    await _persist_score(payload, score, reasons, _trim_safety(safety), target)
    log.info(
        "rug_detector.routed",
        to=target,
        chain=chain,
        address=address,
        score=score,
        reasons=reasons[:5],
        liquidity_usd=liquidity or None,
    )


async def run_rug_detector(stop_event: asyncio.Event | None = None) -> None:
    """Subscribe to chain.new_pair and score every event. Never crashes."""
    bus = get_bus()
    log.info("rug_detector.started", watched=[CHAIN_NEW_PAIR])

    async for msg_id, topic, event in bus.subscribe(
        [CHAIN_NEW_PAIR], group="rug_detector", consumer="rug-detector-1"
    ):
        try:
            await _handle_new_pair(event.payload or {})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("rug_detector.error", id=event.id)
        finally:
            await bus.ack(topic, "rug_detector", msg_id)
        if stop_event and stop_event.is_set():
            break
