"""EVM new-pair watcher: Ethereum + Base + Arbitrum via Alchemy websockets.

One asyncio task per chain, each holding its own ``eth_subscribe "logs"``
subscription against the canonical DEX factory addresses, filtered to the
UniswapV2 ``PairCreated`` and UniswapV3 ``PoolCreated`` event topics. Decoded
events are published per chain via the dual-publish pattern
(``chain.new_pair.{eth|base|arb}`` persisted + ``chain.new_pair`` base topic
not) and persisted to the ``tokens`` / ``pairs`` tables.

Decoding is defensive: if a log can't be decoded the raw log is attached to
the payload with a ``warning`` field instead of being dropped. Each chain
reconnects with its own exponential backoff — a dead chain never kills the
others.

Requires ``ALCHEMY_API_KEY`` — the watcher disables itself with a log line
when the key is missing. Never crashes.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import websockets

from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.watchers.chain_common import (
    persist_pair,
    persist_token,
    publish_new_pair,
)

log = get_logger(__name__)

# Event topic0 hashes (well-known constants):
# UniswapV2 PairCreated(address indexed token0, address indexed token1, address pair, uint256)
TOPIC_V2_PAIR_CREATED = (
    "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cd8d10b7ce1a4f3b2c"
)
# UniswapV3 PoolCreated(address indexed token0, address indexed token1,
#                       uint24 indexed fee, int24 tickSpacing, address pool)
TOPIC_V3_POOL_CREATED = (
    "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"
)

# Canonical factory addresses (well-known constants):
UNI_V2_FACTORY_ETH = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
UNI_V3_FACTORY_ETH_ARB = "0x1F98431c8aD98523631AE4a59f267346ea31F984"  # eth + arbitrum
UNI_V3_FACTORY_BASE = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
AERODROME_FACTORY_BASE = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"  # PairCreated-compatible

MAX_BACKOFF_S = 120


@dataclass(slots=True)
class ChainSpec:
    """One chain's websocket endpoint + watched factories."""

    suffix: str  # topic suffix: eth|base|arb
    name: str  # payload chain name
    ws_url: str
    # (factory_address, topic0, venue)
    factories: list[tuple[str, str, str]]


def _alchemy_url(network: str, key: str) -> str:
    return f"wss://{network}.g.alchemy.com/v2/{key}"


def build_chain_specs(api_key: str) -> list[ChainSpec]:
    return [
        ChainSpec(
            suffix="eth",
            name="ethereum",
            ws_url=_alchemy_url("eth-mainnet", api_key),
            factories=[
                (UNI_V2_FACTORY_ETH, TOPIC_V2_PAIR_CREATED, "uniswap_v2"),
                (UNI_V3_FACTORY_ETH_ARB, TOPIC_V3_POOL_CREATED, "uniswap_v3"),
            ],
        ),
        ChainSpec(
            suffix="base",
            name="base",
            ws_url=_alchemy_url("base-mainnet", api_key),
            factories=[
                (UNI_V3_FACTORY_BASE, TOPIC_V3_POOL_CREATED, "uniswap_v3"),
                (AERODROME_FACTORY_BASE, TOPIC_V2_PAIR_CREATED, "aerodrome"),
            ],
        ),
        ChainSpec(
            suffix="arb",
            name="arbitrum",
            ws_url=_alchemy_url("arb-mainnet", api_key),
            factories=[
                (UNI_V3_FACTORY_ETH_ARB, TOPIC_V3_POOL_CREATED, "uniswap_v3"),
            ],
        ),
    ]


# ---- log decoding ----------------------------------------------------------


def _topic_to_address(topic: str) -> str:
    """An indexed address sits in the last 20 bytes of a 32-byte topic."""
    return "0x" + topic.removeprefix("0x")[-40:].lower()


def _data_words(data: str) -> list[str]:
    """Split hex data into 32-byte words."""
    raw = data.removeprefix("0x")
    return [raw[i : i + 64] for i in range(0, len(raw), 64)]


def decode_pair_log(log_obj: dict[str, Any]) -> dict[str, Any]:
    """Decode a PairCreated/PoolCreated log. Returns fields, never raises."""
    try:
        topics: list[str] = log_obj.get("topics") or []
        words = _data_words(str(log_obj.get("data") or ""))
        topic0 = (topics[0] if topics else "").lower()
        out: dict[str, Any] = {
            "token0": _topic_to_address(topics[1]),
            "token1": _topic_to_address(topics[2]),
        }
        if topic0 == TOPIC_V2_PAIR_CREATED:
            # data: [pair address, pair count]
            out["pair_address"] = "0x" + words[0][-40:].lower()
        elif topic0 == TOPIC_V3_POOL_CREATED:
            # topics[3] = fee; data: [tickSpacing, pool address]
            out["fee"] = int(topics[3], 16)
            out["pair_address"] = "0x" + words[1][-40:].lower()
        else:
            out["warning"] = f"unknown topic0 {topic0}"
        return out
    except Exception as e:
        return {"warning": f"log decode failed: {e}", "raw_log": log_obj}


# ---- per-chain loop --------------------------------------------------------


def _subscribe_frames(spec: ChainSpec) -> list[str]:
    """One eth_subscribe logs frame per (factory, topic) pair."""
    frames: list[str] = []
    for i, (factory, topic0, _venue) in enumerate(spec.factories, start=1):
        frames.append(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": i,
                    "method": "eth_subscribe",
                    "params": ["logs", {"address": factory, "topics": [topic0]}],
                }
            )
        )
    return frames


async def _handle_log(spec: ChainSpec, log_obj: dict[str, Any]) -> None:
    factory = str(log_obj.get("address") or "").lower()
    venue = next(
        (v for addr, _t, v in spec.factories if addr.lower() == factory),
        "unknown",
    )
    decoded = decode_pair_log(log_obj)
    payload: dict[str, Any] = {
        "chain": spec.name,
        "venue": venue,
        "tier_hint": "firehose",
        **decoded,
    }
    log.info(
        "evm_pairs.pair_detected",
        chain=spec.name,
        venue=venue,
        pair=payload.get("pair_address"),
        warning=payload.get("warning"),
    )
    for token in (payload.get("token0"), payload.get("token1")):
        if token:
            await persist_token(spec.name, str(token), venue=venue)
    if payload.get("pair_address"):
        await persist_pair(
            spec.name,
            str(payload["pair_address"]),
            venue=venue,
            token0=payload.get("token0"),
            token1=payload.get("token1"),
        )
    await publish_new_pair(spec.suffix, payload, source="evm_pair_watcher")


async def _handle_message(spec: ChainSpec, raw: str | bytes) -> None:
    msg = json.loads(raw)
    if msg.get("method") != "eth_subscription":
        return
    log_obj = (msg.get("params") or {}).get("result") or {}
    if log_obj:
        await _handle_log(spec, log_obj)


async def run_chain_loop(
    spec: ChainSpec, stop_event: asyncio.Event | None = None
) -> None:
    """Watch one chain forever. Backoff reconnect; never raises (except cancel)."""
    backoff = 1.0
    log.info("evm_pairs.chain.started", chain=spec.name, factories=len(spec.factories))
    while not (stop_event and stop_event.is_set()):
        try:
            async with websockets.connect(
                spec.ws_url, ping_interval=20, ping_timeout=20
            ) as ws:
                for frame in _subscribe_frames(spec):
                    await ws.send(frame)
                log.info("evm_pairs.ws.connected", chain=spec.name)
                backoff = 1.0
                async for raw in ws:
                    try:
                        await _handle_message(spec, raw)
                    except Exception:
                        log.exception("evm_pairs.message.error", chain=spec.name)
                    if stop_event and stop_event.is_set():
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(
                "evm_pairs.ws.disconnect",
                chain=spec.name,
                err=str(e),
                retry_in_s=backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)


async def run_evm_pair_watcher(stop_event: asyncio.Event | None = None) -> None:
    """One task per chain; a dead chain never kills the others."""
    settings = get_settings()
    api_key = settings.alchemy_api_key
    if not api_key:
        log.info("evm_pairs.disabled", reason="ALCHEMY_API_KEY not set")
        return

    specs = build_chain_specs(api_key)
    log.info("evm_pairs.started", chains=[s.name for s in specs])
    tasks = [
        asyncio.create_task(run_chain_loop(spec, stop_event), name=f"evm-{spec.suffix}")
        for spec in specs
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        raise
