from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.topics import CHAIN_LARGE_TRANSFER, CHAIN_WHALE_MOVE

log = get_logger(__name__)

_HELIUS_TX_URL = "https://api.helius.xyz/v0/addresses/{wallet}/transactions"
_ALCHEMY_TRANSFERS_URL = "https://eth-mainnet.g.alchemy.com/v2/{key}"
_REDIS_WALLETS_KEY = "cb:watched_wallets:{chain}"
_SEEN_KEY_PREFIX = "cb:whale_seen:{chain}:{tx}"
_SEEN_TTL = 86400 * 3  # 3 days
_POLL_INTERVAL = 60


async def _get_wallets(redis: Any, chain: str) -> list[str]:
    key = _REDIS_WALLETS_KEY.format(chain=chain)
    try:
        members = await redis.smembers(key)
        return [m.decode() if isinstance(m, bytes) else m for m in members]
    except Exception as exc:
        log.warning("whale_watcher.redis.wallets_error", chain=chain, error=str(exc))
        return []


async def _already_seen(redis: Any, chain: str, tx: str) -> bool:
    key = _SEEN_KEY_PREFIX.format(chain=chain, tx=tx)
    try:
        result = await redis.set(key, "1", nx=True, ex=_SEEN_TTL)
        return result is None
    except Exception:
        return False


async def _poll_solana_wallet(
    client: httpx.AsyncClient,
    wallet: str,
    api_key: str,
    min_sol: float,
) -> list[dict[str, Any]]:
    url = _HELIUS_TX_URL.format(wallet=wallet)
    try:
        resp = await client.get(
            url,
            params={"api-key": api_key, "limit": 10},
            timeout=20,
        )
        resp.raise_for_status()
        txs = resp.json()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("whale_watcher.helius.error", wallet=wallet, error=str(exc))
        return []

    moves = []
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        tx_hash = tx.get("signature", "")
        native_transfers = tx.get("nativeTransfers", [])
        for transfer in native_transfers:
            lamports = transfer.get("amount", 0)
            sol_amount = lamports / 1_000_000_000
            if sol_amount < min_sol:
                continue
            moves.append({
                "wallet": wallet,
                "chain": "solana",
                "amount": sol_amount,
                "token": "SOL",
                "direction": "out" if transfer.get("fromUserAccount") == wallet else "in",
                "tx_hash": tx_hash,
                "counterparty": transfer.get("toUserAccount", "")
                if transfer.get("fromUserAccount") == wallet
                else transfer.get("fromUserAccount", ""),
            })
    return moves


async def _poll_evm_wallet(
    client: httpx.AsyncClient,
    wallet: str,
    api_key: str,
    chain: str,
    min_eth: float,
) -> list[dict[str, Any]]:
    chain_url_map = {
        "ethereum": f"https://eth-mainnet.g.alchemy.com/v2/{api_key}",
        "base": f"https://base-mainnet.g.alchemy.com/v2/{api_key}",
        "arb": f"https://arb-mainnet.g.alchemy.com/v2/{api_key}",
    }
    url = chain_url_map.get(chain, f"https://eth-mainnet.g.alchemy.com/v2/{api_key}")

    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromAddress": wallet,
                "category": ["external", "erc20"],
                "maxCount": "0xa",
                "withMetadata": True,
                "excludeZeroValue": True,
            }
        ],
    }
    try:
        resp = await client.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("whale_watcher.alchemy.error", wallet=wallet, chain=chain, error=str(exc))
        return []

    transfers = data.get("result", {}).get("transfers", [])
    moves = []
    for t in transfers:
        value = t.get("value") or 0.0
        asset = t.get("asset", "ETH") or "ETH"
        if asset == "ETH" and value < min_eth:
            continue
        tx_hash = t.get("hash", "")
        moves.append({
            "wallet": wallet,
            "chain": chain,
            "amount": float(value),
            "token": asset,
            "direction": "out",
            "tx_hash": tx_hash,
            "counterparty": t.get("to", ""),
        })

    payload_in = {**payload}
    payload_in["params"][0] = {
        "toAddress": wallet,
        "category": ["external", "erc20"],
        "maxCount": "0xa",
        "withMetadata": True,
        "excludeZeroValue": True,
    }
    try:
        resp2 = await client.post(url, json=payload_in, timeout=20)
        resp2.raise_for_status()
        data2 = resp2.json()
        for t in data2.get("result", {}).get("transfers", []):
            value = t.get("value") or 0.0
            asset = t.get("asset", "ETH") or "ETH"
            if asset == "ETH" and value < min_eth:
                continue
            tx_hash = t.get("hash", "")
            moves.append({
                "wallet": wallet,
                "chain": chain,
                "amount": float(value),
                "token": asset,
                "direction": "in",
                "tx_hash": tx_hash,
                "counterparty": t.get("from", ""),
            })
    except asyncio.CancelledError:
        raise
    except Exception:
        pass

    return moves


async def run_whale_watcher(stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    if not settings.helius_api_key and not settings.alchemy_api_key:
        log.info("whale_watcher.disabled", reason="no HELIUS_API_KEY or ALCHEMY_API_KEY set")
        return

    log.info("whale_watcher.started", min_sol=settings.whale_min_sol, min_eth=settings.whale_min_eth)
    bus = get_bus()
    redis = bus._redis

    async with httpx.AsyncClient() as client:
        while not (stop_event and stop_event.is_set()):
            sol_wallets: list[str] = []
            evm_chains = ["ethereum", "base", "arb"]

            if settings.helius_api_key:
                sol_wallets = await _get_wallets(redis, "solana")

            for wallet in sol_wallets:
                try:
                    moves = await _poll_solana_wallet(
                        client, wallet, settings.helius_api_key, settings.whale_min_sol
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("whale_watcher.solana.poll_error", wallet=wallet, error=str(exc))
                    continue

                for move in moves:
                    tx_hash = move["tx_hash"]
                    if not tx_hash or await _already_seen(redis, "solana", tx_hash):
                        continue
                    log.info(
                        "whale_watcher.tx.detected",
                        chain="solana",
                        wallet=wallet,
                        amount=move["amount"],
                        token=move["token"],
                    )
                    try:
                        bus.publish(CHAIN_WHALE_MOVE, move, source="whale_watcher")
                        bus.publish(CHAIN_LARGE_TRANSFER, move, source="whale_watcher")
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        log.warning("whale_watcher.publish.error", error=str(exc))

            if settings.alchemy_api_key:
                for chain in evm_chains:
                    evm_wallets = await _get_wallets(redis, chain)
                    for wallet in evm_wallets:
                        try:
                            moves = await _poll_evm_wallet(
                                client, wallet, settings.alchemy_api_key, chain, settings.whale_min_eth
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            log.warning(
                                "whale_watcher.evm.poll_error",
                                wallet=wallet,
                                chain=chain,
                                error=str(exc),
                            )
                            continue

                        for move in moves:
                            tx_hash = move["tx_hash"]
                            if not tx_hash or await _already_seen(redis, chain, tx_hash):
                                continue
                            log.info(
                                "whale_watcher.tx.detected",
                                chain=chain,
                                wallet=wallet,
                                amount=move["amount"],
                                token=move["token"],
                            )
                            try:
                                bus.publish(CHAIN_WHALE_MOVE, move, source="whale_watcher")
                                bus.publish(CHAIN_LARGE_TRANSFER, move, source="whale_watcher")
                            except asyncio.CancelledError:
                                raise
                            except Exception as exc:
                                log.warning("whale_watcher.publish.error", error=str(exc))

            try:
                await asyncio.wait_for(
                    asyncio.shield(
                        asyncio.get_event_loop().run_in_executor(None, lambda: None)
                    )
                    if False
                    else asyncio.sleep(_POLL_INTERVAL),
                    timeout=_POLL_INTERVAL + 5,
                )
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise

    log.info("whale_watcher.stopped")
