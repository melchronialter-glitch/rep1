"""RugCheck adapter (Solana).

Pulls the public RugCheck summary report for a mint:

    GET https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary
    → {"score": <int>, "score_normalised": <0-100>, "risks": [
          {"name": ..., "level": "danger|warn|info", "description": ..., ...}
       ], ...}

Normalization to ``score_norm`` (0 = clean, 100 = maximal risk):

- RugCheck ships ``score_normalised`` already on a 0–100 scale — used as-is
  when present.
- Otherwise the raw ``score`` (an unbounded additive sum, typically 0 for
  clean tokens up to several thousand for obvious rugs) is mapped with
  ``min(100, round(score / 100))`` — i.e. a raw 10 000 ("certain rug")
  saturates at 100, a raw 1 000 lands at 10.

Best-effort: returns ``None`` on any failure or missing data.
"""

from __future__ import annotations

from typing import Any

import httpx

from cryptobot.logging import get_logger

log = get_logger(__name__)

RUGCHECK_SUMMARY_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary"
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


def _normalize_score(report: dict[str, Any]) -> int | None:
    """Map a RugCheck summary report to a 0–100 risk score (see module doc)."""
    normalised = report.get("score_normalised")
    if isinstance(normalised, (int, float)):
        return max(0, min(100, round(normalised)))
    raw = report.get("score")
    if isinstance(raw, (int, float)):
        return max(0, min(100, round(raw / 100)))
    return None


async def check(mint: str, client: httpx.AsyncClient | None = None) -> dict[str, Any] | None:
    """Fetch and normalize the RugCheck summary for a Solana ``mint``.

    Returns ``{"source": "rugcheck", "score_norm": 0-100 | None,
    "score_raw": ..., "risks": [{"name", "level", "description"}, ...]}``
    or ``None`` on any failure (best-effort — never raises).
    """
    try:
        if client is not None:
            return await _check(client, mint)
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": "CryptoBot/0.1"}
        ) as own_client:
            return await _check(own_client, mint)
    except Exception as e:
        log.debug("safety.rugcheck.failed", mint=mint, err=str(e))
        return None


async def _check(client: httpx.AsyncClient, mint: str) -> dict[str, Any] | None:
    resp = await client.get(RUGCHECK_SUMMARY_URL.format(mint=mint))
    resp.raise_for_status()
    report = resp.json()
    if not isinstance(report, dict):
        return None
    risks = [
        {
            "name": r.get("name"),
            "level": r.get("level"),
            "description": r.get("description"),
        }
        for r in (report.get("risks") or [])
        if isinstance(r, dict)
    ]
    return {
        "source": "rugcheck",
        "score_norm": _normalize_score(report),
        "score_raw": report.get("score"),
        "risks": risks,
    }
