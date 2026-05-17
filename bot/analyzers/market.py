"""
Market analyzer: BTC/ETH/major market analysis.

Combines price data and crypto news to produce a structured
market intelligence report via Claude.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot.analyzers.base import BaseAnalyzer
from bot.collectors.prices import format_prices_summary
from bot.collectors.news import format_news_summary

logger = logging.getLogger(__name__)


class MarketAnalyzer(BaseAnalyzer):
    """
    Analyzes cryptocurrency market conditions using price data and news.

    Returns a structured JSON report with:
      - market_summary      : 2-3 sentence overview
      - btc_outlook         : Bitcoin-specific analysis
      - eth_outlook         : Ethereum-specific analysis
      - top_movers          : Notable coins with significant moves
      - sentiment           : overall (bullish/bearish/neutral) + confidence (0-100)
      - key_themes          : list of dominant themes/narratives
      - risk_factors        : list of current risks
      - watch_list          : coins/events to watch
      - alert_worthy        : bool – should we send an immediate alert?
      - alert_reason        : string reason if alert_worthy is True
    """

    SYSTEM_PROMPT = """\
You are a professional cryptocurrency market analyst with deep expertise in \
on-chain data, technical analysis, and macro crypto market dynamics.

Your role is to produce concise, data-driven market intelligence reports for \
sophisticated investors and traders. You focus on actionable insights, not \
generic commentary.

Guidelines:
- Be specific with prices and percentages from the data provided
- Identify the dominant narrative driving markets
- Flag genuine risks, not hypothetical ones
- Keep sentiment labels grounded in data (bullish/bearish/neutral)
- Mark alert_worthy=true ONLY for >5% moves on BTC/ETH or systemic events
- Respond ONLY with valid JSON matching the specified schema

JSON Schema:
{
  "market_summary": "string (2-3 sentences)",
  "btc_outlook": "string",
  "eth_outlook": "string",
  "top_movers": [
    {"coin": "string", "change_pct": number, "commentary": "string"}
  ],
  "sentiment": {
    "overall": "bullish|bearish|neutral",
    "confidence": number (0-100),
    "reasoning": "string"
  },
  "key_themes": ["string"],
  "risk_factors": ["string"],
  "watch_list": ["string"],
  "alert_worthy": boolean,
  "alert_reason": "string or null"
}
"""

    async def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze market data.

        data keys:
          - prices: list[dict] from CoinGecko
          - news:   list[dict] from crypto news collectors
          - alert_threshold: float (e.g. 5.0)
        """
        prices = data.get("prices", [])
        news_items = data.get("news", [])
        alert_threshold = data.get("alert_threshold", 5.0)

        prices_text = format_prices_summary(prices) if prices else "No price data available."
        news_text = format_news_summary(news_items, max_items=25) if news_items else "No news available."

        user_message = f"""\
Analyze the current cryptocurrency market and produce a structured JSON report.

## Current Price Data (Top coins by market cap)
{prices_text}

## Recent Crypto News Headlines (last 8 hours)
{news_text}

## Instructions
- Use the price data above to identify significant moves (threshold: {alert_threshold}%)
- Cross-reference news headlines with price action to identify causation
- For alert_worthy: set to true if BTC or ETH moved >{alert_threshold}% recently \
  OR if there's a systemic event (exchange hack, regulatory ban, major protocol exploit)
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
            logger.error("Market analysis failed: %s", exc)
            result = {
                "market_summary": "Analysis unavailable due to API error.",
                "btc_outlook": "N/A",
                "eth_outlook": "N/A",
                "top_movers": [],
                "sentiment": {"overall": "neutral", "confidence": 0, "reasoning": "error"},
                "key_themes": [],
                "risk_factors": ["Analysis service temporarily unavailable"],
                "watch_list": [],
                "alert_worthy": False,
                "alert_reason": None,
            }

        # Ensure required fields exist with defaults
        result.setdefault("alert_worthy", False)
        result.setdefault("alert_reason", None)
        result.setdefault("top_movers", [])
        result.setdefault("key_themes", [])
        result.setdefault("risk_factors", [])
        result.setdefault("watch_list", [])

        logger.info(
            "Market analysis complete – sentiment: %s, alert_worthy: %s",
            result.get("sentiment", {}).get("overall", "?"),
            result.get("alert_worthy", False),
        )
        return result
