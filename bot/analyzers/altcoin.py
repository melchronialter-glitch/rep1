"""
Altcoin analyzer: focused analysis on non-BTC/ETH assets.

Phase 2 feature – provides a lightweight altcoin-season and
sector rotation analysis based on price data.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot.analyzers.base import BaseAnalyzer
from bot.collectors.prices import format_prices_summary

logger = logging.getLogger(__name__)


class AltcoinAnalyzer(BaseAnalyzer):
    """
    Analyzes altcoin market conditions, sector performance, and rotation signals.

    Returns structured JSON with:
      - altcoin_season_index   : 0-100 (100 = full altseason)
      - top_sectors            : e.g. ['DeFi', 'L2', 'AI']
      - outperformers          : coins beating BTC this cycle
      - underperformers        : lagging coins
      - rotation_signal        : early/mid/late cycle signal
      - sector_breakdown       : brief per-sector commentary
      - phase_2_note           : reminder this module is a stub
    """

    SYSTEM_PROMPT = """\
You are a cryptocurrency altcoin market analyst specializing in sector \
rotation, altcoin season analysis, and emerging narrative tracking.

Your expertise covers:
- Altcoin season indicators (BTC dominance, altcoin vs BTC performance)
- Sector rotation: DeFi, Layer 1s, Layer 2s, AI/data tokens, GameFi, RWA
- Identifying early vs late cycle altcoin opportunities
- Bitcoin dominance as a market cycle indicator

Guidelines:
- BTC dominance >55% = early cycle (BTC leads), <45% = altseason
- Altseason index: calculate based on how many top 50 coins beat BTC 90-day returns
- Be realistic about current market phase based on the price data
- Respond ONLY with valid JSON matching the specified schema

JSON Schema:
{
  "altcoin_season_index": number (0-100),
  "btc_dominance_assessment": "string",
  "top_sectors": ["string"],
  "outperformers": [{"coin": "string", "reason": "string"}],
  "underperformers": [{"coin": "string", "reason": "string"}],
  "rotation_signal": "early_cycle|mid_cycle|late_cycle|uncertain",
  "sector_breakdown": {"sector_name": "commentary"},
  "phase_2_note": "Altcoin analysis module - basic implementation"
}
"""

    async def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze altcoin market data.

        data keys:
          - prices: list[dict] from CoinGecko (top 20+)
        """
        prices = data.get("prices", [])

        if not prices:
            return {
                "altcoin_season_index": 50,
                "btc_dominance_assessment": "No data available",
                "top_sectors": [],
                "outperformers": [],
                "underperformers": [],
                "rotation_signal": "uncertain",
                "sector_breakdown": {},
                "phase_2_note": "Altcoin analysis module – no price data",
            }

        prices_text = format_prices_summary(prices)

        # Extract BTC performance for comparison
        btc_data = next((p for p in prices if p.get("id") == "bitcoin"), None)
        btc_24h = btc_data.get("price_change_percentage_24h", 0) if btc_data else 0

        # Count how many non-BTC coins beat BTC 24h
        non_btc = [p for p in prices if p.get("id") != "bitcoin"]
        beats_btc = sum(
            1 for p in non_btc
            if (p.get("price_change_percentage_24h") or 0) > btc_24h
        )
        rough_altseason_idx = int((beats_btc / max(len(non_btc), 1)) * 100)

        user_message = f"""\
Analyze the altcoin market based on current price data.

## Current Price Data (Top coins by market cap)
{prices_text}

## Quick Stats
- BTC 24h change: {btc_24h:+.2f}%
- Coins beating BTC (24h): {beats_btc}/{len(non_btc)}
- Rough altseason estimate: {rough_altseason_idx}/100

## Instructions
- Refine the altcoin season index estimate based on price patterns
- Identify which sectors appear to be leading (DeFi, L2, AI, Gaming, etc.)
- Note the top 3 outperformers and underperformers with brief reasoning
- Assess the current market cycle phase for altcoins
- Output ONLY the JSON object, no surrounding text
"""

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._call_claude(user_message, require_json=True),
            )
            if not isinstance(result, dict):
                result = {}
        except Exception as exc:
            logger.error("Altcoin analysis failed: %s", exc)
            result = {
                "altcoin_season_index": rough_altseason_idx,
                "btc_dominance_assessment": "Analysis unavailable",
                "top_sectors": [],
                "outperformers": [],
                "underperformers": [],
                "rotation_signal": "uncertain",
                "sector_breakdown": {},
                "phase_2_note": "Analysis service temporarily unavailable",
            }

        result.setdefault("phase_2_note", "Altcoin analysis module – Phase 2 feature")
        logger.info(
            "Altcoin analysis complete – season index: %s, rotation: %s",
            result.get("altcoin_season_index", "?"),
            result.get("rotation_signal", "?"),
        )
        return result
