"""Outcome tracker — the bot labels rugs itself by reading the chain.

The chain already contains the verdict on every token we alerted on: a token
whose liquidity vanished days after launch WAS a rug; one still trading with
real liquidity was not. No human labeling required.

Every ``OUTCOME_CHECK_INTERVAL_S`` (default 6h) the tracker:

1. Pulls tokens we've seen (``tokens`` ⟕ ``rug_labels``) that are old enough
   to judge (24h–14d) and not yet labeled.
2. Looks up their *current* liquidity on DexScreener.
3. Classifies the outcome with :func:`classify_outcome` (pure, unit-tested)
   and writes ``rug_labels`` rows with ``labeled_by='auto'``.
4. Publishes ``chain.lp_event`` + a firehose alert when a token we scored
   with real liquidity has since lost >80% of it (LP pull in progress).
5. Retrains the rug classifier automatically once enough new labels have
   accumulated since the current model was trained.

This closes the learning loop without any /rug commands: detect → wait →
read the outcome on-chain → label → retrain.
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime, timezone
from typing import Any

import httpx

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute, fetch
from cryptobot.logging import get_logger
from cryptobot.topics import CHAIN_LP_EVENT, SIGNAL_ALERT_FIREHOSE

log = get_logger(__name__)

DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"

# Outcome thresholds — deliberately conservative so auto-labels stay clean.
RUG_DEAD_LIQUIDITY_USD = 500.0      # below this the pool is effectively gone
RUG_REQUIRED_PRIOR_LIQ_USD = 2_000.0  # it must have HAD something to lose
SURVIVOR_MIN_LIQUIDITY_USD = 10_000.0
SURVIVOR_MIN_AGE_H = 72.0
DEAD_MIN_AGE_H = 48.0
FAST_RUG_MIN_AGE_H = 6.0
LP_PULL_RETAIN_FRACTION = 0.2       # <20% of detected liquidity = LP pull

BATCH_PER_CYCLE = 100
LOOKUP_DELAY_S = 0.3                # stay well under DexScreener rate limits


def classify_outcome(
    age_hours: float,
    liq_now_usd: float,
    liq_at_detection_usd: float | None,
) -> str | None:
    """Judge a token's fate from its liquidity history. Pure — no I/O.

    Returns ``"rug"``, ``"notrug"``, or ``None`` (undecided — check again
    next cycle).
    """
    # Fast path: when we know the before AND after, a drained pool is an
    # unambiguous LP pull — no need to wait a day. 6h guards against
    # migration noise (e.g. pump.fun → Raydium liquidity moves).
    if (
        age_hours >= FAST_RUG_MIN_AGE_H
        and liq_at_detection_usd is not None
        and liq_at_detection_usd >= RUG_REQUIRED_PRIOR_LIQ_USD
        and liq_now_usd < RUG_DEAD_LIQUIDITY_USD
    ):
        return "rug"
    if age_hours < 24.0:
        return None
    # Effectively zero liquidity after 48h, regardless of history → dead/rug.
    if age_hours >= DEAD_MIN_AGE_H and liq_now_usd < 100.0:
        return "rug"
    # Still holding real liquidity after 72h → survivor.
    if age_hours >= SURVIVOR_MIN_AGE_H and liq_now_usd >= SURVIVOR_MIN_LIQUIDITY_USD:
        return "notrug"
    return None


async def current_liquidity_usd(client: httpx.AsyncClient, address: str) -> float | None:
    """Highest-liquidity pair for the token on DexScreener, or None on failure."""
    try:
        r = await client.get(DEXSCREENER_TOKEN_URL.format(address=address))
        if r.status_code != 200:
            return None
        pairs = (r.json() or {}).get("pairs") or []
        if not pairs:
            return 0.0  # delisted / no pairs left — that IS the signal
        best = 0.0
        for p in pairs:
            liq = ((p.get("liquidity") or {}).get("usd")) or 0.0
            try:
                best = max(best, float(liq))
            except (TypeError, ValueError):
                continue
        return best
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("outcome_tracker.liquidity_lookup_failed", address=address)
        return None


async def _candidates(settings: Any) -> list[Any]:
    """Unlabeled tokens old enough to judge, plus their detection-time liquidity."""
    return await fetch(
        "SELECT t.chain, t.address, t.symbol, t.first_seen, "
        "  (SELECT rs.liquidity_usd FROM risk_scores rs "
        "   WHERE rs.address = t.address ORDER BY rs.ts ASC LIMIT 1) AS liq_then "
        "FROM tokens t "
        "LEFT JOIN rug_labels l ON l.address = t.address "
        "WHERE l.address IS NULL "
        f"  AND t.first_seen < NOW() - INTERVAL '{settings.outcome_min_age_h} hours' "
        f"  AND t.first_seen > NOW() - INTERVAL '{settings.outcome_max_age_d} days' "
        "ORDER BY t.first_seen ASC LIMIT $1",
        BATCH_PER_CYCLE,
    )


async def _label(address: str, chain: str | None, label: str) -> None:
    await execute(
        "INSERT INTO rug_labels (address, chain, label, labeled_by) "
        "VALUES ($1, $2, $3, 'auto') ON CONFLICT (address, label) DO NOTHING",
        address,
        chain,
        label,
    )


async def _maybe_lp_event(
    row: Any, liq_now: float, liq_then: float | None
) -> None:
    """Publish chain.lp_event when liquidity collapsed vs. detection time."""
    if liq_then is None or float(liq_then) < RUG_REQUIRED_PRIOR_LIQ_USD:
        return
    if liq_now >= float(liq_then) * LP_PULL_RETAIN_FRACTION:
        return
    bus = get_bus()
    payload = {
        "title": f"LP pull: {row['symbol'] or row['address'][:12]} [{row['chain']}]",
        "chain": row["chain"],
        "token_address": row["address"],
        "symbol": row["symbol"],
        "liquidity_at_detection_usd": float(liq_then),
        "liquidity_now_usd": liq_now,
        "retained_pct": round(100.0 * liq_now / float(liq_then), 1),
    }
    await bus.publish(CHAIN_LP_EVENT, payload, source="outcome_tracker")
    await bus.publish(SIGNAL_ALERT_FIREHOSE, payload, source="outcome_tracker")
    log.info(
        "outcome_tracker.lp_pull",
        address=row["address"],
        chain=row["chain"],
        liq_then=float(liq_then),
        liq_now=liq_now,
    )


async def _run_cycle() -> dict[str, int]:
    settings = get_settings()
    rows = await _candidates(settings)
    stats = {"checked": 0, "rug": 0, "notrug": 0, "undecided": 0}
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=15.0) as client:
        for row in rows:
            stats["checked"] += 1
            liq_now = await current_liquidity_usd(client, row["address"])
            if liq_now is None:
                stats["undecided"] += 1
                await asyncio.sleep(LOOKUP_DELAY_S)
                continue

            age_h = (now - row["first_seen"]).total_seconds() / 3600.0
            liq_then = float(row["liq_then"]) if row["liq_then"] is not None else None
            label = classify_outcome(age_h, liq_now, liq_then)

            await _maybe_lp_event(row, liq_now, liq_then)

            if label is None:
                stats["undecided"] += 1
            else:
                await _label(row["address"], row["chain"], label)
                stats[label] += 1
            await asyncio.sleep(LOOKUP_DELAY_S)

    log.info("outcome_tracker.cycle_done", **stats)
    return stats


async def _maybe_retrain() -> None:
    """Retrain when enough labels are newer than the current model file."""
    settings = get_settings()
    model_path = pathlib.Path(settings.ml_model_path)
    since = (
        datetime.fromtimestamp(model_path.stat().st_mtime, tz=timezone.utc)
        if model_path.exists()
        else datetime.fromtimestamp(0, tz=timezone.utc)
    )
    try:
        row = await fetch(
            "SELECT count(*) AS n FROM rug_labels WHERE ts > $1", since
        )
        new_labels = int(row[0]["n"]) if row else 0
    except Exception:
        log.exception("outcome_tracker.retrain_count_failed")
        return
    if new_labels < settings.rug_retrain_min_new_labels:
        log.debug("outcome_tracker.retrain_skipped", new_labels=new_labels)
        return

    from cryptobot.ml.train import train

    metrics = await train()
    if metrics.get("trained"):
        from cryptobot.ml.infer import reset_cache

        reset_cache()  # pick up the new model without a restart
        log.info("outcome_tracker.retrained", **{
            k: v for k, v in metrics.items() if k != "top_features"
        })


async def run_outcome_tracker(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: judge token outcomes from the chain, label, retrain."""
    settings = get_settings()
    log.info(
        "outcome_tracker.started",
        interval_s=settings.outcome_check_interval_s,
        window=f"{settings.outcome_min_age_h}h–{settings.outcome_max_age_d}d",
    )
    # Short first delay so a fresh deployment labels its backlog quickly.
    delay = 60.0
    while not (stop_event and stop_event.is_set()):
        if stop_event:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
                break
            except TimeoutError:
                pass
        else:
            await asyncio.sleep(delay)
        try:
            await _run_cycle()
            await _maybe_retrain()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("outcome_tracker.cycle_failed")
        delay = float(settings.outcome_check_interval_s)
    log.info("outcome_tracker.stopped")
