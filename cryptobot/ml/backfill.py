"""Historical backfill — build a labeled training set from data already online.

The chain's recent past is full of finished outcomes: pools created days ago
that are now drained (rugs) and pools that kept their liquidity (survivors).
GeckoTerminal's free API exposes both — ``new_pools`` for the recent cohort
and the top ``pools`` for established survivors — with creation time and
current reserve in one response. No API key, no waiting weeks for live data.

For every pool whose outcome is already decided (via the same
:func:`classify_outcome` rules the live tracker uses) we:

1. run the normal safety fan-out (GoPlus / RugCheck) for the feature vector —
   the contract-level flags (honeypot, mint authority, taxes, proxy) are
   mostly immutable, so screening "late" still reflects launch-time reality;
2. score it with the live ``score_risk`` rules and insert a ``risk_scores``
   row (``routed_to='backfill'``) so training joins work exactly like they
   do for live detections;
3. write the ``rug_labels`` row (``labeled_by='backfill'``).

Run via ``cryptobot backfill-rugs``; pass ``--train`` to retrain immediately.

GeckoTerminal allows ~30 calls/min — the pager sleeps between calls.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from cryptobot.agents.outcome_tracker import classify_outcome
from cryptobot.db import execute, fetchrow
from cryptobot.logging import get_logger

log = get_logger(__name__)

GT_BASE = "https://api.geckoterminal.com/api/v2"
GT_PAGE_DELAY_S = 2.5      # ~24 calls/min, under the 30/min limit
SAFETY_DELAY_S = 1.0       # be polite to GoPlus / RugCheck
SEED_MIN_LIQUIDITY_USD = 1_000.0  # don't waste screening on liquidity-less dust

# GeckoTerminal network id → the chain name our safety adapters expect.
NETWORK_TO_CHAIN = {
    "solana": "solana",
    "eth": "ethereum",
    "base": "base",
    "bsc": "bsc",
    "arbitrum": "arbitrum",
}


def _parse_pool(item: dict[str, Any]) -> dict[str, Any] | None:
    """Extract (address, liquidity, age) from one GeckoTerminal pool item."""
    attrs = item.get("attributes") or {}
    rel = item.get("relationships") or {}
    base_token = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
    # Token ids look like "solana_So11..." / "eth_0xabc..." — strip the prefix.
    if "_" not in base_token:
        return None
    address = base_token.split("_", 1)[1]
    created_raw = attrs.get("pool_created_at")
    if not created_raw:
        return None
    try:
        created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        reserve = float(attrs.get("reserve_in_usd") or 0.0)
    except (TypeError, ValueError):
        reserve = 0.0
    return {
        "address": address,
        "name": attrs.get("name"),
        "liquidity_usd": reserve,
        "age_hours": (datetime.now(timezone.utc) - created).total_seconds() / 3600.0,
        "created_at": created,
    }


async def _fetch_pools(
    client: httpx.AsyncClient, network: str, endpoint: str, pages: int
) -> list[dict[str, Any]]:
    pools: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        try:
            r = await client.get(
                f"{GT_BASE}/networks/{network}/{endpoint}", params={"page": page}
            )
            if r.status_code != 200:
                log.warning(
                    "backfill.gt_bad_response",
                    network=network,
                    endpoint=endpoint,
                    page=page,
                    status=r.status_code,
                )
                break
            for item in (r.json() or {}).get("data") or []:
                parsed = _parse_pool(item)
                if parsed:
                    pools.append(parsed)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("backfill.gt_fetch_failed", network=network, page=page)
            break
        await asyncio.sleep(GT_PAGE_DELAY_S)
    return pools


async def _already_labeled(address: str) -> bool:
    row = await fetchrow("SELECT 1 FROM rug_labels WHERE address = $1 LIMIT 1", address)
    return row is not None


async def _already_seen(chain: str, address: str) -> bool:
    row = await fetchrow(
        "SELECT 1 FROM tokens WHERE chain = $1 AND address = $2 LIMIT 1", chain, address
    )
    return row is not None


async def _ingest_token(
    chain: str, pool: dict[str, Any], label: str | None
) -> None:
    """Safety-screen + score + persist one backfilled token like a live detection.

    ``label=None`` seeds the token unlabeled — the outcome tracker judges it
    from the chain on its next cycles.
    """
    from cryptobot.agents.rug_detector import _trim_safety, score_risk
    from cryptobot.intel.safety import safety_report

    address = pool["address"]
    safety = await safety_report(chain, address)
    payload = {"chain": chain, "token_address": address, "liquidity_usd": pool["liquidity_usd"]}
    score, reasons = score_risk(payload, safety)
    trimmed = _trim_safety(safety)

    await execute(
        "INSERT INTO risk_scores "
        "(id, chain, address, pair_address, score, reasons, safety, liquidity_usd, routed_to) "
        "VALUES ($1::uuid, $2, $3, NULL, $4, $5::jsonb, $6::jsonb, $7, 'backfill')",
        str(uuid.uuid4()),
        chain,
        address,
        score,
        json.dumps(reasons),
        json.dumps(trimmed, default=str),
        pool["liquidity_usd"],
    )
    if label is not None:
        await execute(
            "INSERT INTO rug_labels (address, chain, label, labeled_by, notes) "
            "VALUES ($1, $2, $3, 'backfill', $4) ON CONFLICT (address, label) DO NOTHING",
            address,
            chain,
            label,
            f"liq=${pool['liquidity_usd']:,.0f} age={pool['age_hours']:.0f}h",
        )
    await execute(
        "INSERT INTO tokens (address, chain, name, venue, first_seen) "
        "VALUES ($1, $2, $3, 'backfill', $4) ON CONFLICT (chain, address) DO NOTHING",
        address,
        chain,
        pool.get("name"),
        pool["created_at"],
    )


async def backfill(
    network: str = "solana", pages: int = 5, max_tokens: int = 100
) -> dict[str, Any]:
    """Pull aged pools from GeckoTerminal, classify outcomes, ingest labeled rows."""
    chain = NETWORK_TO_CHAIN.get(network)
    if chain is None:
        return {"error": f"unknown network '{network}'; one of {sorted(NETWORK_TO_CHAIN)}"}

    stats = {"network": network, "pools_seen": 0, "rug": 0, "notrug": 0,
             "seeded": 0, "undecided": 0, "skipped_existing": 0}

    async with httpx.AsyncClient(
        timeout=20.0, headers={"accept": "application/json"}
    ) as client:
        # Recent cohort: many are already dead → rug examples.
        recent = await _fetch_pools(client, network, "new_pools", pages)
        # Established top pools: liquidity held over time → notrug examples.
        top = await _fetch_pools(client, network, "pools", max(1, pages // 2))

        ingested = 0
        for pool in recent + top:
            if ingested >= max_tokens:
                break
            stats["pools_seen"] += 1
            label = classify_outcome(pool["age_hours"], pool["liquidity_usd"], None)
            # The top-pools cohort lacks detection-time liquidity; an old pool
            # holding real liquidity now is a survivor by definition.
            if label is None and pool["age_hours"] >= 7 * 24 and pool["liquidity_usd"] >= 50_000:
                label = "notrug"
            if await _already_labeled(pool["address"]):
                stats["skipped_existing"] += 1
                continue
            if label is None:
                # Outcome not decided yet. Seed it as a detection (safety
                # screen + risk score + tokens row with today's liquidity as
                # the baseline) — the outcome tracker reads its fate off the
                # chain in 6–72h and labels it automatically. Dust pools that
                # never had liquidity teach nothing; skip them.
                if pool["liquidity_usd"] >= SEED_MIN_LIQUIDITY_USD:
                    if await _already_seen(chain, pool["address"]):
                        stats["skipped_existing"] += 1
                        continue
                    try:
                        await _ingest_token(chain, pool, label=None)
                        stats["seeded"] += 1
                        ingested += 1
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.exception("backfill.seed_failed", address=pool["address"])
                    await asyncio.sleep(SAFETY_DELAY_S)
                else:
                    stats["undecided"] += 1
                continue
            try:
                await _ingest_token(chain, pool, label)
                stats[label] += 1
                ingested += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("backfill.ingest_failed", address=pool["address"])
            await asyncio.sleep(SAFETY_DELAY_S)

    log.info("backfill.done", **stats)
    return stats
