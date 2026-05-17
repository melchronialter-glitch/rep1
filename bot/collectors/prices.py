"""
CoinGecko price collector.

Uses the free v3 API (no API key required for basic endpoints).
Fetches top-N coins by market cap with price change data.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Coins to always include even if not in top-20
PINNED_COINS = ["bitcoin", "ethereum"]


async def fetch_prices(
    vs_currency: str = "usd",
    per_page: int = 20,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """
    Fetch the top `per_page` coins by market cap from CoinGecko.

    Returns a list of coin dicts compatible with the DB schema.
    """
    url = f"{COINGECKO_BASE}/coins/markets"
    params: dict[str, Any] = {
        "vs_currency": vs_currency,
        "order": "market_cap_desc",
        "per_page": per_page,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "1h,24h,7d",
    }

    logger.info("Fetching CoinGecko prices (top %d coins)…", per_page)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                resp.raise_for_status()
                data: list[dict[str, Any]] = await resp.json()
    except aiohttp.ClientResponseError as exc:
        logger.error("CoinGecko HTTP error %s: %s", exc.status, exc.message)
        return []
    except Exception as exc:
        logger.error("CoinGecko request failed: %s", exc)
        return []

    logger.info("Fetched %d coin prices from CoinGecko", len(data))
    return data


def detect_major_moves(
    prices: list[dict[str, Any]],
    threshold_pct: float = 5.0,
    window: str = "1h",
) -> list[dict[str, Any]]:
    """
    Return coins whose price changed more than `threshold_pct` in the given window.

    window: '1h' | '24h' | '7d'
    """
    key_map = {
        "1h": "price_change_percentage_1h_in_currency",
        "24h": "price_change_percentage_24h",
        "7d": "price_change_percentage_7d_in_currency",
    }
    change_key = key_map.get(window, "price_change_percentage_24h")
    alerts = []
    for coin in prices:
        change = coin.get(change_key)
        if change is not None and abs(change) >= threshold_pct:
            alerts.append({
                "coin_id": coin["id"],
                "symbol": coin.get("symbol", "").upper(),
                "name": coin.get("name", ""),
                "price_usd": coin.get("current_price", 0),
                "change_pct": change,
                "window": window,
            })
    return alerts


def format_prices_summary(prices: list[dict[str, Any]]) -> str:
    """Build a compact human-readable price table for use in prompts."""
    lines = ["Coin | Price USD | 1h% | 24h% | 7d% | Mkt Cap"]
    lines.append("-" * 70)
    for p in prices:
        def fmt_pct(v: Any) -> str:
            if v is None:
                return "  n/a"
            return f"{v:+.2f}%"

        def fmt_usd(v: Any) -> str:
            if v is None:
                return "n/a"
            if v >= 1_000:
                return f"${v:,.0f}"
            return f"${v:.4f}"

        def fmt_cap(v: Any) -> str:
            if v is None:
                return "n/a"
            if v >= 1e9:
                return f"${v/1e9:.1f}B"
            if v >= 1e6:
                return f"${v/1e6:.0f}M"
            return f"${v:.0f}"

        lines.append(
            f"{p.get('symbol','').upper():<6} | "
            f"{fmt_usd(p.get('current_price')):<12} | "
            f"{fmt_pct(p.get('price_change_percentage_1h_in_currency')):<8} | "
            f"{fmt_pct(p.get('price_change_percentage_24h')):<8} | "
            f"{fmt_pct(p.get('price_change_percentage_7d_in_currency')):<8} | "
            f"{fmt_cap(p.get('market_cap'))}"
        )
    return "\n".join(lines)
