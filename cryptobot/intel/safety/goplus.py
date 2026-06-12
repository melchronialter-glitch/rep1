"""GoPlus token-security adapter (EVM chains).

Extracted from :mod:`cryptobot.intel.coin_intel` in Phase D so the safety
fan-out (:func:`cryptobot.intel.safety.safety_report`) and the coin intel
gatherer share one implementation. Behavior is unchanged: a single GET to the
GoPlus ``token_security`` endpoint, trimmed down to the fields that matter
for a safety read.
"""

from __future__ import annotations

from typing import Any

import httpx

from cryptobot.logging import get_logger

log = get_logger(__name__)

GOPLUS_TOKEN_SECURITY = "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)

# DexScreener chain id -> GoPlus numeric chain id (EVM chains only)
GOPLUS_CHAIN_IDS: dict[str, str] = {
    "ethereum": "1",
    "bsc": "56",
    "polygon": "137",
    "arbitrum": "42161",
    "base": "8453",
    "optimism": "10",
    "avalanche": "43114",
}

# Only the fields that matter for a safety read.
_KEEP_FIELDS = [
    "is_honeypot", "honeypot_with_same_creator", "buy_tax", "sell_tax",
    "is_mintable", "is_proxy", "is_open_source", "can_take_back_ownership",
    "owner_address", "owner_percent", "creator_address", "creator_percent",
    "is_blacklisted", "is_whitelisted", "transfer_pausable", "trading_cooldown",
    "hidden_owner", "selfdestruct", "anti_whale_modifiable", "slippage_modifiable",
    "holder_count", "lp_holder_count", "total_supply",
]


async def check(
    chain_id: str, address: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """Fetch GoPlus token security for ``address`` on numeric ``chain_id``.

    Returns the trimmed raw GoPlus result dict, or ``None`` when GoPlus has
    no data. Raises on transport/HTTP errors when called with an external
    ``client`` (callers like coin_intel handle their own try/except); when it
    creates its own client it is still the caller's job to catch — the
    package-level :func:`safety_report` wraps every adapter in best-effort.
    """
    if client is not None:
        return await _check(client, chain_id, address)
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT, headers={"User-Agent": "CryptoBot/0.1"}
    ) as own_client:
        return await _check(own_client, chain_id, address)


async def _check(
    client: httpx.AsyncClient, chain_id: str, address: str
) -> dict[str, Any] | None:
    resp = await client.get(
        GOPLUS_TOKEN_SECURITY.format(chain_id=chain_id),
        params={"contract_addresses": address},
    )
    resp.raise_for_status()
    result = (resp.json().get("result") or {}).get(address.lower())
    if not result:
        return None
    return {k: result[k] for k in _KEEP_FIELDS if k in result}
