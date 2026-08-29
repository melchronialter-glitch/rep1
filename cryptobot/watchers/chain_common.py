"""Shared helpers for the Phase C chain watchers.

All new-pair watchers publish through :func:`publish_new_pair`, which follows
the dual-publish pattern established by the price watcher: the chain-specific
topic (``chain.new_pair.sol``) is persisted to the events archive, the base
aggregate topic (``chain.new_pair``) is not — Redis Streams can't wildcard,
so triage subscribes to the base topic.

Token and pair rows are persisted best-effort: a dead Postgres never stops
the bus flow.
"""

from __future__ import annotations

import json
from typing import Any

from cryptobot.bus import get_bus
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.topics import CHAIN_NEW_PAIR

log = get_logger(__name__)


async def publish_new_pair(
    chain_suffix: str, payload: dict[str, Any], *, source: str
) -> None:
    """Publish to ``chain.new_pair.{suffix}`` (persisted) and the base topic (not)."""
    bus = get_bus()
    await bus.publish(f"{CHAIN_NEW_PAIR}.{chain_suffix}", payload, source=source)
    await bus.publish(CHAIN_NEW_PAIR, payload, source=source, persist=False)


async def persist_token(
    chain: str,
    address: str,
    *,
    symbol: str | None = None,
    name: str | None = None,
    venue: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert into ``tokens`` (idempotent). Best-effort — never raises."""
    if not address:
        return
    try:
        await execute(
            "INSERT INTO tokens (address, chain, symbol, name, venue, metadata) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb) "
            "ON CONFLICT (chain, address) DO NOTHING",
            address,
            chain,
            symbol,
            name,
            venue,
            json.dumps(metadata or {}),
        )
    except Exception:
        log.exception("chain.token.persist_failed", chain=chain, address=address)


async def persist_pair(
    chain: str,
    pair_address: str,
    *,
    venue: str | None = None,
    token0: str | None = None,
    token1: str | None = None,
) -> None:
    """Insert into ``pairs`` (idempotent). Best-effort — never raises."""
    if not pair_address:
        return
    try:
        await execute(
            "INSERT INTO pairs (pair_address, chain, venue, token0, token1) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (chain, pair_address) DO NOTHING",
            pair_address,
            chain,
            venue,
            token0,
            token1,
        )
    except Exception:
        log.exception("chain.pair.persist_failed", chain=chain, pair=pair_address)
