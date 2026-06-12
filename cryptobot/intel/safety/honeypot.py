"""Honeypot.is adapter (EVM chains).

Runs the public honeypot simulation:

    GET https://api.honeypot.is/v2/IsHoneypot?address={addr}&chainID={id}
    → {"honeypotResult": {"isHoneypot": bool, ...},
       "simulationResult": {"buyTax": %, "sellTax": %, ...},
       "summary": {"risk": ..., "riskLevel": ...}, ...}

Normalized to ``{"source": "honeypot.is", "is_honeypot": bool | None,
"buy_tax_pct": float | None, "sell_tax_pct": float | None,
"honeypot_reason": str | None, "risk": str | None}``. Taxes are percentages
(``5.0`` == 5%), matching Honeypot.is' own units.

Best-effort: returns ``None`` on any failure.
"""

from __future__ import annotations

from typing import Any

import httpx

from cryptobot.logging import get_logger

log = get_logger(__name__)

HONEYPOT_IS_URL = "https://api.honeypot.is/v2/IsHoneypot"
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def check(
    chain_id: str, address: str, client: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """Run the Honeypot.is simulation for ``address`` on numeric ``chain_id``.

    Returns the normalized dict described in the module docstring, or ``None``
    on any failure (best-effort — never raises).
    """
    try:
        if client is not None:
            return await _check(client, chain_id, address)
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": "CryptoBot/0.1"}
        ) as own_client:
            return await _check(own_client, chain_id, address)
    except Exception as e:
        log.debug("safety.honeypot.failed", address=address, chain_id=chain_id, err=str(e))
        return None


async def _check(
    client: httpx.AsyncClient, chain_id: str, address: str
) -> dict[str, Any] | None:
    resp = await client.get(
        HONEYPOT_IS_URL, params={"address": address, "chainID": chain_id}
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        return None
    hp = data.get("honeypotResult") or {}
    sim = data.get("simulationResult") or {}
    summary = data.get("summary") or {}
    is_honeypot = hp.get("isHoneypot")
    return {
        "source": "honeypot.is",
        "is_honeypot": bool(is_honeypot) if is_honeypot is not None else None,
        "honeypot_reason": hp.get("honeypotReason"),
        "buy_tax_pct": _as_float(sim.get("buyTax")),
        "sell_tax_pct": _as_float(sim.get("sellTax")),
        "transfer_tax_pct": _as_float(sim.get("transferTax")),
        "risk": summary.get("risk"),
    }
