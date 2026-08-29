"""Raydium new-pool watcher (Helius enhanced WebSocket).

Detects new Raydium AMM pools — post-bonding pump.fun migrations and direct
listings — by subscribing to logs that mention the Raydium AMM v4 program and
filtering for ``initialize2`` lines (the standard new-pool detection
technique). On a hit, the full transaction is fetched via ``getTransaction``
(jsonParsed) over Helius HTTPS RPC to recover the pool address and the two
token mints.

A Raydium listing is a stronger signal than a raw pump.fun mint, so events
carry ``tier_hint: "medium"``. Parsing is defensive: when the transaction
can't be decoded we still publish whatever was recovered plus a ``warning``
field.

Requires ``HELIUS_API_KEY`` — the watcher disables itself with a log line
when the key is missing. Reconnects with exponential backoff. Never crashes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import websockets

from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.watchers.chain_common import (
    persist_pair,
    persist_token,
    publish_new_pair,
)

log = get_logger(__name__)

# Raydium Liquidity Pool AMM v4 program (mainnet, well-known constant).
RAYDIUM_AMM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
# Native SOL wrapper mint — present in nearly every Raydium pool.
WSOL_MINT = "So11111111111111111111111111111111111111112"

HELIUS_WS = "wss://mainnet.helius-rpc.com/?api-key={key}"
HELIUS_RPC = "https://mainnet.helius-rpc.com/?api-key={key}"
INIT_LOG_MARKER = "initialize2"  # appears in program logs when a pool is created
MAX_BACKOFF_S = 120

# Account indexes within the Raydium initialize2 instruction (well-known layout):
# 4 = AMM pool id, 8 = coin (base) mint, 9 = pc (quote) mint.
_IX_IDX_POOL = 4
_IX_IDX_COIN_MINT = 8
_IX_IDX_PC_MINT = 9

_LOGS_SUBSCRIBE = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "logsSubscribe",
        "params": [
            {"mentions": [RAYDIUM_AMM_PROGRAM]},
            {"commitment": "confirmed"},
        ],
    }
)


def _extract_pool_from_tx(tx: dict[str, Any]) -> dict[str, Any]:
    """Pull pool + mint addresses out of a jsonParsed transaction. Defensive."""
    result: dict[str, Any] = {}
    message = ((tx.get("transaction") or {}).get("message")) or {}
    instructions = message.get("instructions") or []
    for ix in instructions:
        if ix.get("programId") != RAYDIUM_AMM_PROGRAM:
            continue
        accounts = ix.get("accounts") or []
        if len(accounts) > _IX_IDX_PC_MINT:
            result["pair_address"] = accounts[_IX_IDX_POOL]
            result["token0"] = accounts[_IX_IDX_COIN_MINT]
            result["token1"] = accounts[_IX_IDX_PC_MINT]
        break
    return result


async def _fetch_transaction(
    client: httpx.AsyncClient, rpc_url: str, signature: str
) -> dict[str, Any] | None:
    resp = await client.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        },
    )
    resp.raise_for_status()
    return resp.json().get("result")


async def _handle_pool_init(
    client: httpx.AsyncClient, rpc_url: str, signature: str
) -> None:
    payload: dict[str, Any] = {
        "chain": "solana",
        "venue": "raydium",
        "tx_signature": signature,
        "tier_hint": "medium",
    }
    try:
        tx = await _fetch_transaction(client, rpc_url, signature)
        if tx:
            payload.update(_extract_pool_from_tx(tx))
        if "pair_address" not in payload:
            payload["warning"] = "could not extract pool accounts from transaction"
    except Exception as e:
        payload["warning"] = f"getTransaction failed: {e}"
        log.warning("solana_dex.tx_fetch.failed", signature=signature, err=str(e))

    # The non-WSOL side is the interesting token.
    mints = [m for m in (payload.get("token0"), payload.get("token1")) if m]
    token_address = next((m for m in mints if m != WSOL_MINT), mints[0] if mints else None)
    if token_address:
        payload["token_address"] = token_address
        await persist_token("solana", str(token_address), venue="raydium")
    if payload.get("pair_address"):
        await persist_pair(
            "solana",
            str(payload["pair_address"]),
            venue="raydium",
            token0=payload.get("token0"),
            token1=payload.get("token1"),
        )

    log.info(
        "solana_dex.pool_detected",
        pool=payload.get("pair_address"),
        token=token_address,
        warning=payload.get("warning"),
    )
    await publish_new_pair("sol", payload, source="solana_dex_watcher")


async def _handle_message(
    client: httpx.AsyncClient, rpc_url: str, raw: str | bytes
) -> None:
    msg = json.loads(raw)
    if msg.get("method") != "logsNotification":
        return
    value = (((msg.get("params") or {}).get("result")) or {}).get("value") or {}
    if value.get("err") is not None:
        return
    logs = value.get("logs") or []
    if not any(INIT_LOG_MARKER in line for line in logs):
        return
    signature = value.get("signature")
    if signature:
        await _handle_pool_init(client, rpc_url, str(signature))


async def run_solana_dex_watcher(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: logsSubscribe on Raydium, reconnect with backoff. Never raises."""
    settings = get_settings()
    api_key = settings.helius_api_key
    if not api_key:
        log.info("solana_dex.disabled", reason="HELIUS_API_KEY not set")
        return

    ws_url = HELIUS_WS.format(key=api_key)
    rpc_url = HELIUS_RPC.format(key=api_key)
    backoff = 1.0
    log.info("solana_dex.started", program=RAYDIUM_AMM_PROGRAM)

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
        while not (stop_event and stop_event.is_set()):
            try:
                async with websockets.connect(
                    ws_url, ping_interval=20, ping_timeout=20
                ) as ws:
                    await ws.send(_LOGS_SUBSCRIBE)
                    log.info("solana_dex.ws.connected")
                    backoff = 1.0
                    async for raw in ws:
                        try:
                            await _handle_message(client, rpc_url, raw)
                        except Exception:
                            log.exception("solana_dex.message.error")
                        if stop_event and stop_event.is_set():
                            return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("solana_dex.ws.disconnect", err=str(e), retry_in_s=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
