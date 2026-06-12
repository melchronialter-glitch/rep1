"""Best-effort enrichment for chain.new_pair payloads.

Used by triage before tiering: looks the token up on DexScreener and merges
liquidity / FDV / price into the payload. Strictly best-effort — a 10s
timeout, any failure logged and swallowed, the original payload always comes
back. Fresh pump.fun mints are skipped entirely (DexScreener has no data
until the token graduates to a DEX).
"""

from __future__ import annotations

from typing import Any

import httpx

from cryptobot.logging import get_logger

log = get_logger(__name__)

DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"
ENRICH_TIMEOUT_S = 10.0


def _pick_address(payload: dict[str, Any]) -> str | None:
    """The address to enrich: token_address if present, else token0/token1."""
    return payload.get("token_address") or payload.get("token0") or payload.get("token1")


def _best_pair(pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the DexScreener pair with the deepest USD liquidity."""
    scored = [
        (float((p.get("liquidity") or {}).get("usd") or 0.0), p) for p in pairs
    ]
    if not scored:
        return None
    return max(scored, key=lambda t: t[0])[1]


async def enrich_new_pair(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge DexScreener liquidity/fdv/price into a new_pair payload.

    Never raises; returns the (possibly unchanged) payload.
    """
    if payload.get("venue") == "pump.fun":
        return payload  # DexScreener has nothing for fresh pump.fun mints
    address = _pick_address(payload)
    if not address:
        return payload

    try:
        async with httpx.AsyncClient(timeout=ENRICH_TIMEOUT_S) as client:
            resp = await client.get(DEXSCREENER_TOKEN_URL.format(address=address))
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
    except Exception as e:
        log.debug("enrich.dexscreener.failed", address=address, err=str(e))
        return payload

    best = _best_pair(pairs)
    if best is None:
        return payload

    enriched = dict(payload)
    liquidity_usd = (best.get("liquidity") or {}).get("usd")
    if liquidity_usd is not None:
        enriched["liquidity_usd"] = float(liquidity_usd)
    if best.get("fdv") is not None:
        enriched["fdv"] = best["fdv"]
    if best.get("priceUsd") is not None:
        enriched["price_usd"] = best["priceUsd"]
    if best.get("url"):
        enriched["dexscreener_url"] = best["url"]
    base_token = best.get("baseToken") or {}
    if not enriched.get("symbol") and base_token.get("symbol"):
        enriched["symbol"] = base_token["symbol"]
    log.debug(
        "enrich.dexscreener.ok",
        address=address,
        liquidity_usd=enriched.get("liquidity_usd"),
    )
    return enriched
