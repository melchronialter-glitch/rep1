"""Coin analyst agent — answers /analyze and /rugcheck queries.

Subscribes to ``intel.user_query``. For each query it gathers everything the
free APIs know via :mod:`cryptobot.intel.coin_intel`, runs a Sonnet analysis
over the raw JSON, persists the result to the ``analyses`` table, and
publishes the markdown report to ``signal.alert.dm`` (with the requester's
chat id so the Telegram sender replies in the right place).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from cryptobot import llm
from cryptobot.bus import get_bus
from cryptobot.db import execute
from cryptobot.intel import coin_intel
from cryptobot.logging import get_logger
from cryptobot.topics import INTEL_USER_QUERY, SIGNAL_ALERT_DM

log = get_logger(__name__)

ANALYZE_SYSTEM = """\
You are an expert crypto analyst. You receive raw JSON gathered about a coin
or token (CoinGecko market data, DexScreener pairs, GoPlus security checks —
whatever was available). Produce a structured assessment in clean markdown
suitable for a Telegram message:

*What it is* — one or two sentences.
*Price action* — current price, recent moves (1h/24h/7d/30d), distance from ATH.
*Liquidity & safety* — liquidity depth, FDV vs mcap, any security red flags.
*Holders & social* — holder/community signals if available.
*Risk score* — 1 (very safe, blue chip) to 10 (almost certainly a scam), with
the top reasons.
*Verdict* — one of: avoid / watch / interesting, with a one-line rationale.

Be direct and specific. If data is missing, say so briefly instead of
guessing. Note the data sources used and any warnings. Keep it under 350
words. Use plain markdown (*bold*, bullet lists), no tables, no code fences."""

RUGCHECK_SYSTEM = """\
You are a crypto token safety auditor. You receive raw JSON about a token
(DexScreener liquidity data and GoPlus contract security checks when
available). Produce a safety-focused report in clean markdown for Telegram:

*Contract safety* — honeypot status, buy/sell tax, mintable, proxy, hidden
owner, ownership renounced, pausable transfers. Flag every red flag clearly.
*Liquidity* — depth in USD, number of pairs, LP holder count, pair age.
*Concentration* — owner/creator percentage, holder count.
*Risk score* — 1 (safe) to 10 (rug/honeypot), with reasons.
*Verdict* — one of: avoid / watch / interesting.

If security data is unavailable (e.g. Solana token, or API failure), state
that explicitly and judge only on liquidity. Be blunt — this protects real
money. Keep it under 250 words. Plain markdown only, no tables, no code
fences."""


def _safety_subset(intel: dict[str, Any]) -> dict[str, Any]:
    """Strip the gathered intel down to safety/liquidity data for rugcheck."""
    return {
        "query": intel.get("query"),
        "query_kind": intel.get("query_kind"),
        "dexscreener": intel.get("dexscreener"),
        "goplus_security": intel.get("goplus_security"),
        "sources_used": intel.get("sources_used"),
        "warnings": intel.get("warnings"),
    }


async def analyze_query(query: str, query_type: str = "analyze") -> str:
    """Gather intel and run the Claude analysis. Returns markdown.

    Shared by the bus agent and the CLI ``analyze`` command.
    """
    intel = await coin_intel.gather(query)
    if query_type == "rugcheck":
        system = RUGCHECK_SYSTEM
        data: dict[str, Any] = _safety_subset(intel)
    else:
        system = ANALYZE_SYSTEM
        data = intel

    result = await llm.analyze(
        system=system,
        user=json.dumps(data, separators=(",", ":"), default=str),
        fast=False,
        max_tokens=2048,
    )
    return result["text"] or "Analysis produced no output."


async def _persist_analysis(query: str, query_type: str, result_md: str) -> None:
    try:
        await execute(
            "INSERT INTO analyses (id, query, query_type, result_md) "
            "VALUES ($1::uuid, $2, $3, $4)",
            str(uuid.uuid4()),
            query,
            query_type,
            result_md,
        )
    except Exception:
        log.exception("coin_analyst.persist_failed", query=query)


async def run_coin_analyst(stop_event: asyncio.Event | None = None) -> None:
    """Subscribe to intel.user_query and answer analyze/rugcheck requests."""
    bus = get_bus()
    log.info("coin_analyst.started")

    async for msg_id, topic, event in bus.subscribe(
        [INTEL_USER_QUERY], group="coin_analyst", consumer="coin-analyst-1"
    ):
        payload = event.payload or {}
        query_type = str(payload.get("type") or "analyze").lower()
        query = str(payload.get("query") or "").strip()
        reply_to = payload.get("reply_to_chat_id")
        try:
            if query_type not in ("analyze", "rugcheck") or not query:
                log.warning("coin_analyst.bad_query", payload=payload)
                continue
            log.info("coin_analyst.query", type=query_type, query=query)
            try:
                md = await analyze_query(query, query_type)
            except Exception as e:
                log.exception("coin_analyst.failed", query=query)
                md = f"Analysis of `{query}` failed: {e}"
            await _persist_analysis(query, query_type, md)
            label = "Rugcheck" if query_type == "rugcheck" else "Analysis"
            out: dict[str, Any] = {
                "title": f"{label}: {query}",
                "summary": md,
            }
            if reply_to:
                out["reply_to_chat_id"] = reply_to
            await bus.publish(SIGNAL_ALERT_DM, out, source="coin_analyst")
        except Exception:
            log.exception("coin_analyst.error", id=event.id)
        finally:
            await bus.ack(topic, "coin_analyst", msg_id)
        if stop_event and stop_event.is_set():
            break
