"""Pump.fun new-token watcher (PumpPortal public WebSocket).

Connects to ``wss://pumpportal.fun/api/data``, sends a ``subscribeNewToken``
request, and treats every ``txType == "create"`` message as a freshly minted
pump.fun token. Each token is:

- published via the dual-publish pattern (``chain.new_pair.sol`` persisted,
  ``chain.new_pair`` base topic not) — see
  :func:`cryptobot.watchers.chain_common.publish_new_pair`
- persisted to the ``tokens`` table for later pattern learning

Pump.fun mints tens of thousands of tokens per day, so everything carries a
``tier_hint``: tokens whose creator buy-in is below
``pumpfun_min_initial_buy_sol`` get ``tier_hint: "ignore"`` (triage drops
them; the tokens-table row survives), everything else gets ``"firehose"``.

No API key required — this watcher is always on. Reconnects with exponential
backoff. Never crashes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import websockets

from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.watchers.chain_common import persist_token, publish_new_pair

log = get_logger(__name__)

PUMPPORTAL_WS = "wss://pumpportal.fun/api/data"
SUBSCRIBE_MSG = json.dumps({"method": "subscribeNewToken"})
MAX_BACKOFF_S = 120


def build_payload(msg: dict[str, Any], min_initial_buy_sol: float) -> dict[str, Any]:
    """Map a PumpPortal ``create`` message to a chain.new_pair payload."""
    sol_amount = float(msg.get("solAmount") or 0.0)
    tier_hint = "firehose" if sol_amount >= min_initial_buy_sol else "ignore"
    return {
        "chain": "solana",
        "venue": "pump.fun",
        "token_address": msg.get("mint"),
        "symbol": msg.get("symbol"),
        "name": msg.get("name"),
        "market_cap_sol": msg.get("marketCapSol"),
        "initial_buy_sol": sol_amount,
        "uri": msg.get("uri"),
        "tier_hint": tier_hint,
    }


async def _handle_message(raw: str | bytes, min_initial_buy_sol: float) -> None:
    msg = json.loads(raw)
    if not isinstance(msg, dict) or msg.get("txType") != "create":
        return
    mint = msg.get("mint")
    if not mint:
        return

    payload = build_payload(msg, min_initial_buy_sol)
    log.debug(
        "pumpfun.token_created",
        mint=mint,
        symbol=payload["symbol"],
        initial_buy_sol=payload["initial_buy_sol"],
        tier_hint=payload["tier_hint"],
    )
    # Persist even "ignore"-tier tokens — cheap training data for Phase H.
    await persist_token(
        "solana",
        str(mint),
        symbol=payload["symbol"],
        name=payload["name"],
        venue="pump.fun",
        metadata={
            "uri": payload["uri"],
            "market_cap_sol": payload["market_cap_sol"],
            "initial_buy_sol": payload["initial_buy_sol"],
            "pool": msg.get("pool"),
        },
    )
    await publish_new_pair("sol", payload, source="pumpfun_watcher")


async def run_pumpfun_watcher(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: connect, subscribe, consume, reconnect with backoff. Never raises."""
    settings = get_settings()
    min_buy = settings.pumpfun_min_initial_buy_sol
    backoff = 1.0
    log.info("pumpfun.started", min_initial_buy_sol=min_buy)

    while not (stop_event and stop_event.is_set()):
        try:
            async with websockets.connect(
                PUMPPORTAL_WS, ping_interval=20, ping_timeout=20
            ) as ws:
                await ws.send(SUBSCRIBE_MSG)
                log.info("pumpfun.ws.connected")
                backoff = 1.0
                async for raw in ws:
                    try:
                        await _handle_message(raw, min_buy)
                    except Exception:
                        log.exception("pumpfun.message.error")
                    if stop_event and stop_event.is_set():
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("pumpfun.ws.disconnect", err=str(e), retry_in_s=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
