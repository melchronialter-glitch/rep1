"""
Macro analyzer: macro-economic events and their impact on crypto markets.

Uses newsapi macro articles + Reddit sentiment to assess how broader
economic conditions affect the crypto market.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot.analyzers.base import BaseAnalyzer
from bot.collectors.macro import format_macro_summary
from bot.collectors.social import format_reddit_summary

logger = logging.getLogger(__name__)


class MacroAnalyzer(BaseAnalyzer):
    """
    Analyzes macro-economic conditions and their crypto market implications.

    Returns structured JSON with:
      - macro_summary       : Brief overview of current macro landscape
      - fed_stance          : Current Fed/central bank posture
      - inflation_outlook   : Inflation trajectory assessment
      - crypto_impact       : How macro conditions affect crypto
      - sentiment           : retail sentiment from Reddit
      - narrative_shifts    : Emerging narratives to watch
      - correlation_signals : Macro-crypto correlation observations
      - risk_level          : low/medium/high/critical
      - key_events_ahead    : Upcoming macro events to watch
    """

    SYSTEM_PROMPT = """\
You are a macro-economic analyst specializing in the intersection of \
traditional finance and cryptocurrency markets.

Your expertise covers:
- Federal Reserve policy and its impact on risk assets including crypto
- Inflation dynamics and how they affect Bitcoin as a store of value
- Global trade policy (tariffs) and their effects on risk appetite
- Dollar strength/weakness and crypto correlations
- Retail investor sentiment vs institutional macro positioning

Guidelines:
- Assess how macro developments specifically affect crypto markets
- Bitcoin is often treated as a risk-on/risk-off asset; factor this in
- Rate hike expectations increase risk-off pressure; rate cuts are bullish
- Dollar strength (DXY up) is typically bearish for BTC/crypto
- Tariff escalation → uncertainty → risk-off → typically bearish for crypto
- Be specific about the directional impact (bullish/bearish/neutral for crypto)
- Respond ONLY with valid JSON matching the specified schema

JSON Schema:
{
  "macro_summary": "string (2-3 sentences)",
  "fed_stance": "hawkish|dovish|neutral|uncertain",
  "inflation_outlook": "string",
  "crypto_impact": {
    "direction": "bullish|bearish|neutral",
    "magnitude": "low|medium|high",
    "explanation": "string"
  },
  "sentiment": {
    "reddit_overall": "bullish|bearish|neutral|mixed",
    "notable_narratives": ["string"]
  },
  "narrative_shifts": ["string"],
  "correlation_signals": ["string"],
  "risk_level": "low|medium|high|critical",
  "key_events_ahead": ["string"]
}
"""

    async def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze macro data.

        data keys:
          - macro_news:    list[dict] from NewsAPI
          - reddit_posts:  list[dict] from Reddit
        """
        macro_news = data.get("macro_news", [])
        reddit_posts = data.get("reddit_posts", [])

        macro_text = format_macro_summary(macro_news, max_items=20) if macro_news else "No macro news available."
        reddit_text = format_reddit_summary(reddit_posts, max_posts=20) if reddit_posts else "No Reddit data available."

        user_message = f"""\
Analyze current macro-economic conditions and their impact on cryptocurrency markets.

## Recent Macro-Economic News (last 8 hours)
{macro_text}

## Reddit Crypto Community Pulse (top posts by score)
{reddit_text}

## Instructions
- Assess Fed stance based on recent news (look for rate hints, FOMC mentions)
- Evaluate inflation trajectory from CPI/PCE mentions
- Determine how current macro conditions affect crypto market direction
- Extract 2-3 notable narratives from Reddit community posts
- Identify key upcoming macro events investors should watch
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
            logger.error("Macro analysis failed: %s", exc)
            result = {
                "macro_summary": "Macro analysis unavailable due to API error.",
                "fed_stance": "uncertain",
                "inflation_outlook": "N/A",
                "crypto_impact": {
                    "direction": "neutral",
                    "magnitude": "low",
                    "explanation": "Analysis service unavailable",
                },
                "sentiment": {"reddit_overall": "mixed", "notable_narratives": []},
                "narrative_shifts": [],
                "correlation_signals": [],
                "risk_level": "medium",
                "key_events_ahead": [],
            }

        logger.info(
            "Macro analysis complete – risk_level: %s, crypto_impact: %s",
            result.get("risk_level", "?"),
            result.get("crypto_impact", {}).get("direction", "?"),
        )
        return result
