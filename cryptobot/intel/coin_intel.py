"""Coin intelligence gatherer — the "/analyze any coin" library.

Given a symbol (``btc``, ``PEPE``) or a contract address (EVM ``0x…`` or a
Solana base58 mint), pulls everything the free APIs know about it:

- CoinGecko: search → coin id → price, mcap, ATH, price changes, community
- DexScreener: pairs with liquidity, FDV, txns, volume (works for addresses)
- GoPlus token security (EVM addresses only): honeypot / tax / owner checks

Every upstream call is individually try/excepted — a dead API degrades the
result instead of failing it. The return value is a single dict with whatever
was found plus ``sources_used`` and ``warnings`` lists.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from cryptobot.intel.safety import goplus as goplus_adapter
from cryptobot.intel.safety.goplus import GOPLUS_CHAIN_IDS  # noqa: F401  (re-export)
from cryptobot.logging import get_logger

log = get_logger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search"

HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)

_EVM_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SOLANA_ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def looks_like_evm_address(query: str) -> bool:
    return bool(_EVM_ADDR_RE.match(query))


def looks_like_solana_address(query: str) -> bool:
    # Base58, 32-44 chars. Exclude plain tickers (all-lowercase short strings).
    return bool(_SOLANA_ADDR_RE.match(query)) and len(query) >= 32


def looks_like_contract_address(query: str) -> bool:
    return looks_like_evm_address(query) or looks_like_solana_address(query)


# ---- CoinGecko --------------------------------------------------------------

async def _coingecko_lookup(client: httpx.AsyncClient, query: str) -> dict[str, Any] | None:
    """Resolve a symbol via /search, then pull /coins/{id}."""
    resp = await client.get(f"{COINGECKO_BASE}/search", params={"query": query})
    resp.raise_for_status()
    coins = resp.json().get("coins") or []
    if not coins:
        return None
    # Prefer an exact symbol match; otherwise take the top hit.
    exact = [c for c in coins if (c.get("symbol") or "").lower() == query.lower()]
    coin_id = (exact[0] if exact else coins[0]).get("id")
    if not coin_id:
        return None

    resp = await client.get(
        f"{COINGECKO_BASE}/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true",
            "developer_data": "false",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    md = data.get("market_data") or {}

    def _usd(key: str) -> float | None:
        v = md.get(key)
        return (v or {}).get("usd") if isinstance(v, dict) else None

    links = data.get("links") or {}
    return {
        "id": data.get("id"),
        "symbol": data.get("symbol"),
        "name": data.get("name"),
        "description": ((data.get("description") or {}).get("en") or "")[:600] or None,
        "price_usd": _usd("current_price"),
        "market_cap_usd": _usd("market_cap"),
        "fully_diluted_valuation_usd": _usd("fully_diluted_valuation"),
        "volume_24h_usd": _usd("total_volume"),
        "ath_usd": _usd("ath"),
        "ath_change_pct": (md.get("ath_change_percentage") or {}).get("usd"),
        "price_change_pct": {
            "1h": (md.get("price_change_percentage_1h_in_currency") or {}).get("usd"),
            "24h": md.get("price_change_percentage_24h"),
            "7d": md.get("price_change_percentage_7d"),
            "30d": md.get("price_change_percentage_30d"),
        },
        "market_cap_rank": data.get("market_cap_rank"),
        "community": {
            "twitter_followers": (data.get("community_data") or {}).get("twitter_followers"),
            "reddit_subscribers": (data.get("community_data") or {}).get("reddit_subscribers"),
            "telegram_users": (data.get("community_data") or {}).get(
                "telegram_channel_user_count"
            ),
        },
        "links": {
            "homepage": next((u for u in (links.get("homepage") or []) if u), None),
            "twitter": links.get("twitter_screen_name") or None,
            "telegram": links.get("telegram_channel_identifier") or None,
            "subreddit": links.get("subreddit_url") or None,
        },
    }


# ---- DexScreener ------------------------------------------------------------

async def _dexscreener_lookup(client: httpx.AsyncClient, query: str) -> dict[str, Any] | None:
    resp = await client.get(DEXSCREENER_SEARCH, params={"q": query})
    resp.raise_for_status()
    pairs = resp.json().get("pairs") or []
    if not pairs:
        return None

    def _liq(p: dict[str, Any]) -> float:
        return float((p.get("liquidity") or {}).get("usd") or 0)

    pairs.sort(key=_liq, reverse=True)
    out: list[dict[str, Any]] = []
    for p in pairs[:5]:
        out.append(
            {
                "chain": p.get("chainId"),
                "dex": p.get("dexId"),
                "pair_address": p.get("pairAddress"),
                "base_token": (p.get("baseToken") or {}).get("symbol"),
                "base_token_address": (p.get("baseToken") or {}).get("address"),
                "quote_token": (p.get("quoteToken") or {}).get("symbol"),
                "price_usd": p.get("priceUsd"),
                "liquidity_usd": (p.get("liquidity") or {}).get("usd"),
                "fdv_usd": p.get("fdv"),
                "market_cap_usd": p.get("marketCap"),
                "price_change_pct": p.get("priceChange"),
                "txns_24h": (p.get("txns") or {}).get("h24"),
                "volume_24h_usd": (p.get("volume") or {}).get("h24"),
                "pair_created_at": p.get("pairCreatedAt"),
                "url": p.get("url"),
            }
        )
    return {"pairs": out, "pair_count": len(pairs)}


# ---- GoPlus token security (EVM) ---------------------------------------------
# Extracted to cryptobot.intel.safety.goplus in Phase D; kept as a thin alias
# so this module's behavior (including raising on transport errors, handled
# by gather()'s try/except) is unchanged.

async def _goplus_lookup(
    client: httpx.AsyncClient, chain_id: str, address: str
) -> dict[str, Any] | None:
    return await goplus_adapter.check(chain_id, address, client=client)


# ---- Public API ---------------------------------------------------------------

async def gather(query: str) -> dict[str, Any]:
    """Gather everything known about ``query`` (symbol or contract address).

    Never raises; failures degrade into ``warnings`` entries.
    """
    query = query.strip()
    is_address = looks_like_contract_address(query)
    intel: dict[str, Any] = {
        "query": query,
        "query_kind": "address" if is_address else "symbol",
        "sources_used": [],
        "warnings": [],
    }

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT, headers={"User-Agent": "CryptoBot/0.1"}
    ) as client:
        # DexScreener works for both addresses and symbols; for addresses it's
        # the primary source.
        try:
            dex = await _dexscreener_lookup(client, query)
            if dex:
                intel["dexscreener"] = dex
                intel["sources_used"].append("dexscreener")
            else:
                intel["warnings"].append("dexscreener: no pairs found")
        except Exception as e:
            log.warning("coin_intel.dexscreener.failed", query=query, err=str(e))
            intel["warnings"].append(f"dexscreener: {e}")

        # CoinGecko only makes sense for symbol-ish queries.
        if not is_address:
            try:
                cg = await _coingecko_lookup(client, query)
                if cg:
                    intel["coingecko"] = cg
                    intel["sources_used"].append("coingecko")
                else:
                    intel["warnings"].append("coingecko: no match")
            except Exception as e:
                log.warning("coin_intel.coingecko.failed", query=query, err=str(e))
                intel["warnings"].append(f"coingecko: {e}")

        # GoPlus security check for EVM addresses (best effort).
        if looks_like_evm_address(query):
            chain = None
            pairs = (intel.get("dexscreener") or {}).get("pairs") or []
            if pairs:
                chain = pairs[0].get("chain")
            goplus_chain_id = GOPLUS_CHAIN_IDS.get(chain or "ethereum", "1")
            try:
                sec = await _goplus_lookup(client, goplus_chain_id, query)
                if sec:
                    intel["goplus_security"] = sec
                    intel["sources_used"].append("goplus")
                else:
                    intel["warnings"].append("goplus: no security data")
            except Exception as e:
                log.warning("coin_intel.goplus.failed", query=query, err=str(e))
                intel["warnings"].append(f"goplus: {e}")

    if not intel["sources_used"]:
        intel["warnings"].append("no data found from any source")
    log.info(
        "coin_intel.gathered",
        query=query,
        sources=intel["sources_used"],
        warnings=len(intel["warnings"]),
    )
    return intel
