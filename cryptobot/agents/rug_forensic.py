"""Rug-forensic agent (Phase H).

Subscribes to ``intel.rug_label``.  When a coin is labeled as a rug:

1. Pulls its most recent ``risk_scores`` row.
2. Pulls all ``tg_calls`` rows for that address.
3. Pulls the ``tokens`` row for metadata.
4. Asks Claude Sonnet to write a forensic post-mortem.
5. Persists the report to ``rug_forensics``.
6. Publishes ``intel.rug_confirmed`` with the report summary.

Also runs a weekly Sunday-20:00-UTC summary job that pulls all rugs from the
past 7 days, asks Claude to identify common patterns across them, and
publishes a DM alert.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute, fetch, fetchrow
from cryptobot import llm as llm_module
from cryptobot.logging import get_logger
from cryptobot.topics import INTEL_RUG_CONFIRMED, INTEL_RUG_LABEL, SIGNAL_ALERT_DM

log = get_logger(__name__)

_FORENSIC_SYSTEM = """\
You are a crypto forensic analyst specialising in rug-pulls and exit scams.
Given on-chain risk flags, caller data, and token metadata, write a concise
post-mortem that explains:
  1. Which safety flags were present at launch and what they signified.
  2. Who the top callers were and whether they appear coordinated.
  3. The likely pattern signature (early LP removal, insider selling, fake
     volume, honeypot, etc.).
  4. A one-sentence "pattern label" (e.g. "Classic liquidity rug with shill callers").
Write in plain English.  Be precise and factual; do not speculate beyond the data.
Return JSON with keys: flags_analysis, caller_analysis, pattern_signature,
pattern_label, summary (≤3 sentences).
"""

_WEEKLY_SYSTEM = """\
You are a crypto threat-intelligence analyst.
Given a list of confirmed rug-pull post-mortems from the past 7 days,
identify common patterns, recurring caller names, and structural similarities.
Return a concise markdown report (≤400 words) with:
  - Top recurring flags
  - Notable repeat callers
  - Most common rug pattern
  - One-sentence week-in-review
"""


async def _run_forensic(address: str, chain: str | None, labeled_by: str) -> None:
    """Build and persist a forensic report for a single rug address."""
    bus = get_bus()

    # 1. Risk score row
    risk_row = await fetchrow(
        "SELECT * FROM risk_scores WHERE address = $1 ORDER BY ts DESC LIMIT 1",
        address,
    )

    # 2. TG calls
    call_rows = await fetch(
        "SELECT sender_name, chat_title, tickers, ts FROM tg_calls "
        "WHERE address = $1 ORDER BY ts ASC",
        address,
    )

    # 3. Token metadata
    token_row = await fetchrow(
        "SELECT symbol, name, chain, venue, first_seen FROM tokens "
        "WHERE address = $1 ORDER BY first_seen ASC LIMIT 1",
        address,
    )

    # Build caller summary
    caller_counts: dict[str, int] = {}
    for c in call_rows:
        name = c["sender_name"] or "unknown"
        caller_counts[name] = caller_counts.get(name, 0) + 1
    top_callers = sorted(caller_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    callers_json = [{"sender_name": n, "calls_count": cnt} for n, cnt in top_callers]

    # Flags from risk_scores.reasons
    flags = []
    if risk_row and risk_row["reasons"]:
        reasons = risk_row["reasons"]
        if isinstance(reasons, str):
            try:
                reasons = json.loads(reasons)
            except Exception:
                reasons = [reasons]
        flags = reasons if isinstance(reasons, list) else list(reasons)

    risk_score = risk_row["score"] if risk_row else None
    token_chain = (token_row and token_row["chain"]) or chain or "unknown"
    symbol = (token_row and token_row["symbol"]) or address[:8]

    user_prompt = json.dumps(
        {
            "address": address,
            "chain": token_chain,
            "symbol": symbol,
            "name": (token_row and token_row["name"]) or "",
            "risk_score": risk_score,
            "safety_flags": flags,
            "top_callers": callers_json,
            "liquidity_usd": str(risk_row["liquidity_usd"]) if risk_row else None,
            "first_seen": (
                token_row["first_seen"].isoformat() if token_row and token_row["first_seen"] else None
            ),
        },
        default=str,
    )

    try:
        result = await llm_module.analyze(
            system=_FORENSIC_SYSTEM,
            user=user_prompt,
            fast=False,
            max_tokens=1024,
            temperature=0.3,
            json_response=True,
        )
        report_json = result.get("json") or {}
        raw_report = result.get("text", "")
    except Exception:
        log.exception("rug_forensic.llm_failed", address=address)
        report_json = {}
        raw_report = ""

    pattern_summary = report_json.get("pattern_label") or report_json.get("pattern_signature") or ""
    summary_text = report_json.get("summary", "")

    forensic_id = uuid.uuid4()
    try:
        await execute(
            """
            INSERT INTO rug_forensics
                (id, address, chain, risk_score, callers, flags, pattern_summary, raw_report, ts)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            forensic_id,
            address,
            token_chain,
            risk_score,
            json.dumps(callers_json),
            json.dumps(flags),
            pattern_summary,
            raw_report,
        )
        log.info("rug_forensic.persisted", id=str(forensic_id), address=address)
    except Exception:
        log.exception("rug_forensic.persist_failed", address=address)

    # Publish intel.rug_confirmed
    try:
        await bus.publish(
            INTEL_RUG_CONFIRMED,
            {
                "address": address,
                "chain": token_chain,
                "symbol": symbol,
                "risk_score": risk_score,
                "pattern_label": pattern_summary,
                "summary": summary_text,
                "forensic_id": str(forensic_id),
                "labeled_by": labeled_by,
            },
            source="rug_forensic",
        )
        log.info("rug_forensic.confirmed_published", address=address)
    except Exception:
        log.exception("rug_forensic.publish_failed", address=address)


async def _weekly_summary() -> None:
    """Pull last-7-days rugs, generate a cross-rug pattern report, publish DM."""
    bus = get_bus()

    try:
        rows = await fetch(
            """
            SELECT rf.address, rf.chain, rf.risk_score, rf.flags, rf.callers,
                   rf.pattern_summary, rf.raw_report
            FROM rug_forensics rf
            JOIN rug_labels rl ON rl.address = rf.address AND rl.label = 'rug'
            WHERE rf.ts > NOW() - INTERVAL '7 days'
            ORDER BY rf.ts DESC
            """,
        )
    except Exception:
        log.exception("rug_forensic.weekly_query_failed")
        return

    if not rows:
        log.info("rug_forensic.weekly_summary.no_rugs")
        return

    cases = []
    for r in rows:
        cases.append(
            {
                "address": r["address"],
                "chain": r["chain"],
                "risk_score": r["risk_score"],
                "flags": r["flags"],
                "callers": r["callers"],
                "pattern_summary": r["pattern_summary"],
            }
        )

    user_prompt = (
        f"Here are {len(cases)} rug-pull post-mortems from the past 7 days:\n\n"
        + json.dumps(cases, default=str, indent=2)
    )

    try:
        result = await llm_module.analyze(
            system=_WEEKLY_SYSTEM,
            user=user_prompt,
            fast=False,
            max_tokens=800,
            temperature=0.4,
        )
        report_text = result.get("text", "(no report generated)")
    except Exception:
        log.exception("rug_forensic.weekly_llm_failed")
        return

    try:
        await bus.publish(
            SIGNAL_ALERT_DM,
            {
                "title": f"Weekly Rug Summary ({len(cases)} rugs)",
                "body": report_text,
                "severity": "low",
            },
            source="rug_forensic",
        )
        log.info("rug_forensic.weekly_summary_published", count=len(cases))
    except Exception:
        log.exception("rug_forensic.weekly_publish_failed")


async def _seconds_until_sunday_20() -> float:
    """Return seconds until the next Sunday 20:00 UTC."""
    now = datetime.now(tz=timezone.utc)
    days_ahead = (6 - now.weekday()) % 7  # 6 = Sunday
    if days_ahead == 0 and (now.hour > 20 or (now.hour == 20 and now.minute >= 0)):
        days_ahead = 7
    target = now.replace(hour=20, minute=0, second=0, microsecond=0)
    import datetime as dt_mod

    target += dt_mod.timedelta(days=days_ahead)
    return (target - now).total_seconds()


async def run_rug_forensic(stop_event: asyncio.Event | None = None) -> None:
    """Subscribe to intel.rug_label and run forensic + weekly summary loop."""
    bus = get_bus()
    log.info("rug_forensic.started")

    # Start weekly summary scheduler as a background task
    async def _weekly_loop() -> None:
        while not (stop_event and stop_event.is_set()):
            try:
                wait_s = await _seconds_until_sunday_20()
                log.info("rug_forensic.weekly_next_in_s", seconds=int(wait_s))
                await asyncio.sleep(wait_s)
                await _weekly_summary()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("rug_forensic.weekly_loop_error")
                await asyncio.sleep(3600)

    weekly_task = asyncio.create_task(_weekly_loop())

    try:
        async for msg_id, topic, event in bus.subscribe(
            [INTEL_RUG_LABEL],
            group="rug_forensic",
            consumer="rug_forensic_0",
        ):
            if stop_event and stop_event.is_set():
                break
            try:
                payload = event.payload if hasattr(event, "payload") else event
                address = payload.get("address", "")
                label = payload.get("label", "rug")
                chain = payload.get("chain_guess") or payload.get("chain")
                labeled_by = str(payload.get("labeled_by", "unknown"))

                if not address:
                    log.warning("rug_forensic.missing_address", payload=payload)
                    await bus.ack(INTEL_RUG_LABEL, "rug_forensic", msg_id)
                    continue

                if label == "rug":
                    log.info("rug_forensic.processing", address=address, chain=chain)
                    await _run_forensic(address, chain, labeled_by)
                else:
                    log.info("rug_forensic.notrug_skipped", address=address)

                await bus.ack(INTEL_RUG_LABEL, "rug_forensic", msg_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("rug_forensic.processing_error", msg_id=msg_id)
                await bus.ack(INTEL_RUG_LABEL, "rug_forensic", msg_id)
    finally:
        weekly_task.cancel()
        try:
            await weekly_task
        except asyncio.CancelledError:
            pass
        log.info("rug_forensic.stopped")
