"""BSC new-pair watcher: PancakeSwap V2 factory over a configurable WS RPC.

Same mechanics as the EVM pair watcher (eth_subscribe "logs" on the factory's
``PairCreated`` topic, defensive decode, dual publish to
``chain.new_pair.bsc`` + the base topic, tokens/pairs persistence) — reuses
:class:`cryptobot.watchers.evm.pairs.ChainSpec` and the per-chain loop.

The websocket endpoint comes from ``BSC_WS_URL`` (e.g. a QuickNode free-tier
or public WS endpoint); the watcher disables itself with a log line when it
is empty. Reconnects with exponential backoff. Never crashes.
"""

from __future__ import annotations

import asyncio

from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.watchers.evm.pairs import (
    TOPIC_V2_PAIR_CREATED,
    ChainSpec,
    run_chain_loop,
)

log = get_logger(__name__)

# PancakeSwap V2 factory (well-known constant).
PANCAKE_V2_FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"


async def run_bsc_pair_watcher(stop_event: asyncio.Event | None = None) -> None:
    """Watch PancakeSwap V2 PairCreated events. Self-disables without BSC_WS_URL."""
    settings = get_settings()
    ws_url = settings.bsc_ws_url
    if not ws_url:
        log.info("bsc_pairs.disabled", reason="BSC_WS_URL not set")
        return

    spec = ChainSpec(
        suffix="bsc",
        name="bsc",
        ws_url=ws_url,
        factories=[(PANCAKE_V2_FACTORY, TOPIC_V2_PAIR_CREATED, "pancakeswap_v2")],
    )
    log.info("bsc_pairs.started", factory=PANCAKE_V2_FACTORY)
    await run_chain_loop(spec, stop_event)
