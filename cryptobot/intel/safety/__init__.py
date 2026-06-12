"""Token safety screening — Phase D fan-out over the free safety APIs.

One entry point, :func:`safety_report`, dispatches by chain:

- ``solana`` → RugCheck summary report
- EVM chains (``ethereum``, ``bsc``, ``base``, ``arbitrum``, …) → GoPlus
  token security + Honeypot.is simulation, concurrently

The merged report never raises; sources that fail or return nothing are
simply absent and listed in neither ``sources`` nor the payload. The chain
name → GoPlus numeric id mapping is shared with the coin intel gatherer via
:data:`GOPLUS_CHAIN_IDS`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from cryptobot.intel.safety import goplus, honeypot, rugcheck
from cryptobot.intel.safety.goplus import GOPLUS_CHAIN_IDS
from cryptobot.logging import get_logger

__all__ = ["GOPLUS_CHAIN_IDS", "safety_report"]

log = get_logger(__name__)

HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


async def safety_report(chain: str, address: str) -> dict[str, Any]:
    """Run every safety adapter that applies to ``chain`` and merge results.

    Returns ``{"chain", "address", "sources": [...], "goplus": ...,
    "honeypot": ..., "rugcheck": ...}`` with absent/failed sources omitted.
    Best-effort throughout — never raises (CancelledError excepted).
    """
    chain = (chain or "").strip().lower()
    report: dict[str, Any] = {"chain": chain, "address": address, "sources": []}
    if not address:
        return report

    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": "CryptoBot/0.1"}
        ) as client:
            if chain in ("solana", "sol"):
                rc = await rugcheck.check(address, client=client)
                if rc:
                    report["rugcheck"] = rc
                    report["sources"].append("rugcheck")
            elif chain in GOPLUS_CHAIN_IDS:
                chain_id = GOPLUS_CHAIN_IDS[chain]
                gp_result, hp_result = await asyncio.gather(
                    _goplus_safe(client, chain_id, address),
                    honeypot.check(chain_id, address, client=client),
                )
                if gp_result:
                    report["goplus"] = gp_result
                    report["sources"].append("goplus")
                if hp_result:
                    report["honeypot"] = hp_result
                    report["sources"].append("honeypot.is")
            else:
                log.debug("safety.unsupported_chain", chain=chain, address=address)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("safety.report.failed", chain=chain, address=address, err=str(e))

    log.debug(
        "safety.report.done", chain=chain, address=address, sources=report["sources"]
    )
    return report


async def _goplus_safe(
    client: httpx.AsyncClient, chain_id: str, address: str
) -> dict[str, Any] | None:
    """GoPlus check that swallows errors (the adapter raises on transport)."""
    try:
        return await goplus.check(chain_id, address, client=client)
    except Exception as e:
        log.debug("safety.goplus.failed", address=address, chain_id=chain_id, err=str(e))
        return None
