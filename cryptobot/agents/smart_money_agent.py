from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute, fetch, fetchrow
from cryptobot.logging import get_logger
from cryptobot.topics import (
    CHAIN_NEW_PAIR,
    CHAIN_WHALE_MOVE,
    SIGNAL_ALERT_FIREHOSE,
    SIGNAL_ALERT_MEDIUM,
    SMART_MONEY_WALLET,
)

log = get_logger(__name__)

_GROUP = "smart_money_agent"
_CONSUMER = "smart_money_agent_1"

_UPSERT_WALLET = """
INSERT INTO smart_wallets (wallet_address, chain, first_seen, last_active, calls_count, profitable_calls, total_pnl_usd)
VALUES ($1, $2, NOW(), NOW(), 0, 0, 0)
ON CONFLICT (wallet_address, chain)
DO UPDATE SET last_active = NOW()
"""

_GET_WALLET = """
SELECT wallet_address, chain, calls_count, profitable_calls, total_pnl_usd
FROM smart_wallets
WHERE wallet_address = $1 AND chain = $2
"""

_INCREMENT_CALLS = """
UPDATE smart_wallets SET calls_count = calls_count + 1, last_active = NOW()
WHERE wallet_address = $1 AND chain = $2
"""

_NEW_PAIR_RECENT_KEY = "cb:new_pair:{coin}:{chain}"
_NEW_PAIR_TTL = 4 * 3600


async def _upsert_wallet(wallet: str, chain: str) -> None:
    try:
        await execute(_UPSERT_WALLET, wallet, chain)
    except Exception as exc:
        log.warning("smart_money.upsert.error", wallet=wallet, chain=chain, error=str(exc))


async def _get_wallet_record(wallet: str, chain: str) -> dict[str, Any] | None:
    try:
        row = await fetchrow(_GET_WALLET, wallet, chain)
        return dict(row) if row else None
    except Exception as exc:
        log.warning("smart_money.db.error", wallet=wallet, error=str(exc))
        return None


async def _handle_whale_move(payload: dict[str, Any], bus: Any, redis: Any) -> None:
    wallet = payload.get("wallet", "")
    chain = payload.get("chain", "solana")
    token = payload.get("token", "")
    amount = payload.get("amount", 0.0)
    tx_hash = payload.get("tx_hash", "")
    direction = payload.get("direction", "")

    if not wallet:
        return

    await _upsert_wallet(wallet, chain)

    new_pair_key = _NEW_PAIR_RECENT_KEY.format(coin=token, chain=chain)
    try:
        recently_paired = await redis.exists(new_pair_key)
    except Exception:
        recently_paired = False

    record = await _get_wallet_record(wallet, chain)
    calls_count = record.get("calls_count", 0) if record else 0

    signal_payload = {
        "wallet": wallet,
        "chain": chain,
        "amount": amount,
        "token": token,
        "direction": direction,
        "tx_hash": tx_hash,
        "recently_paired": bool(recently_paired),
        "calls_count": calls_count,
    }

    if recently_paired:
        log.info(
            "smart_money.signal.new_pair_match",
            wallet=wallet,
            chain=chain,
            token=token,
            calls_count=calls_count,
        )
        try:
            await execute(_INCREMENT_CALLS, wallet, chain)
        except Exception as exc:
            log.warning("smart_money.increment.error", error=str(exc))

        topic = SIGNAL_ALERT_MEDIUM if calls_count > 0 else SIGNAL_ALERT_FIREHOSE
        try:
            bus.publish(SMART_MONEY_WALLET, signal_payload, source="smart_money_agent")
            bus.publish(topic, signal_payload, source="smart_money_agent")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("smart_money.publish.error", error=str(exc))
    else:
        try:
            bus.publish(SMART_MONEY_WALLET, signal_payload, source="smart_money_agent")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("smart_money.publish.error", error=str(exc))


async def _handle_new_pair(payload: dict[str, Any], redis: Any) -> None:
    coin = payload.get("symbol", "") or payload.get("token", "")
    chain = payload.get("chain", "unknown")
    if not coin:
        return

    key = _NEW_PAIR_RECENT_KEY.format(coin=coin, chain=chain)
    try:
        await redis.set(key, "1", ex=_NEW_PAIR_TTL)
    except Exception as exc:
        log.warning("smart_money.redis.set_error", key=key, error=str(exc))


async def run_smart_money_agent(stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    if not settings.helius_api_key and not settings.alchemy_api_key:
        log.info("smart_money_agent.disabled", reason="no chain API keys configured")
        return

    log.info("smart_money_agent.started")
    bus = get_bus()
    redis = bus._redis

    topics = [CHAIN_WHALE_MOVE, CHAIN_NEW_PAIR]
    stream = bus.subscribe(topics, group=_GROUP, consumer=_CONSUMER)

    try:
        async for topic, msg_id, event in stream:
            if stop_event and stop_event.is_set():
                break

            payload = event.payload
            try:
                if topic == CHAIN_WHALE_MOVE:
                    await _handle_whale_move(payload, bus, redis)
                elif topic == CHAIN_NEW_PAIR:
                    await _handle_new_pair(payload, redis)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("smart_money_agent.handler.error", topic=topic, error=str(exc))
            finally:
                try:
                    bus.ack(topic, _GROUP, msg_id)
                except Exception:
                    pass
    except asyncio.CancelledError:
        raise
    finally:
        log.info("smart_money_agent.stopped")
