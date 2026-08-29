"""Macro / world-economy news watcher (NewsAPI.org).

Fills the gap the crypto-RSS keyword classifier can't: macro stories from the
general press (Fed decisions, tariffs, CPI, geopolitics) that never appear in
crypto outlets. Requires ``NEWS_API_KEY`` (free tier: 100 req/day) — the
watcher disables itself with a log line when the key is missing.

Publishes ``news.macro`` per new item and additionally
``news.macro.high_impact`` when high-impact keywords match. Dedupe shares the
``cb:seen:news`` Redis set with the crypto news watcher; items are persisted
to ``news_items`` with ``is_macro = true``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import redis.asyncio as redis

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.topics import NEWS_MACRO, NEWS_MACRO_HIGH_IMPACT
from cryptobot.watchers.news import SEEN_KEY, SEEN_TTL_S, _high_impact_re

log = get_logger(__name__)

NEWSAPI_URL = "https://newsapi.org/v2/everything"
POLL_INTERVAL_S = 30 * 60  # free tier is 100 req/day; 6 queries every 30 min = 96/day

# Each query is one NewsAPI request per poll cycle.
MACRO_QUERIES = [
    '"federal reserve" OR fomc OR powell',
    "inflation OR cpi OR ppi",
    "tariff OR \"trade war\" OR sanctions",
    '"interest rate" OR treasury OR yields',
    "recession OR gdp OR unemployment",
    'crypto AND (sec OR regulation OR etf OR congress)',
]


async def _poll_query(
    client: httpx.AsyncClient, r: redis.Redis, api_key: str, query: str
) -> int:
    resp = await client.get(
        NEWSAPI_URL,
        params={
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
        },
        headers={"X-Api-Key": api_key},
    )
    resp.raise_for_status()
    articles = resp.json().get("articles") or []
    bus = get_bus()
    emitted = 0

    for a in articles:
        url = a.get("url")
        title = a.get("title") or ""
        if not url or not title:
            continue
        # Shared atomic dedupe with the crypto news watcher.
        added = await r.sadd(SEEN_KEY, url)
        if not added:
            continue
        await r.expire(SEEN_KEY, SEEN_TTL_S)

        item: dict[str, Any] = {
            "title": title,
            "url": url,
            "source": (a.get("source") or {}).get("name") or "newsapi",
            "published_at": a.get("publishedAt"),
            "summary": (a.get("description") or "")[:500] or None,
        }
        try:
            await execute(
                "INSERT INTO news_items (id, title, url, source, published_at, is_macro) "
                "VALUES ($1::uuid, $2, $3, $4, NOW(), TRUE) ON CONFLICT (url) DO NOTHING",
                str(uuid.uuid4()),
                title,
                url,
                item["source"],
            )
        except Exception:
            log.exception("macro_news.persist.failed", url=url)

        await bus.publish(NEWS_MACRO, item, source="macro_news_watcher")
        if _high_impact_re.search(title):
            await bus.publish(
                NEWS_MACRO_HIGH_IMPACT,
                {**item, "severity": "high"},
                source="macro_news_watcher",
            )
        emitted += 1
    return emitted


async def run_macro_news_watcher(stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    api_key = settings.news_api_key
    if not api_key:
        log.info("macro_news.disabled", reason="NEWS_API_KEY not set")
        return

    r: redis.Redis = redis.from_url(settings.redis_url)
    log.info("macro_news.started", queries=len(MACRO_QUERIES), interval_s=POLL_INTERVAL_S)

    try:
        while not (stop_event and stop_event.is_set()):
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
                for query in MACRO_QUERIES:
                    try:
                        n = await _poll_query(client, r, api_key, query)
                        if n:
                            log.info("macro_news.emitted", query=query[:40], count=n)
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:
                            log.warning("macro_news.rate_limited")
                            break  # stop this cycle, wait for next interval
                        log.warning("macro_news.query.failed", query=query[:40], err=str(e))
                    except Exception:
                        log.exception("macro_news.query.error", query=query[:40])
            try:
                await asyncio.wait_for(
                    stop_event.wait() if stop_event else asyncio.sleep(POLL_INTERVAL_S),
                    timeout=POLL_INTERVAL_S,
                )
                if stop_event and stop_event.is_set():
                    return
            except TimeoutError:
                pass
    finally:
        await r.aclose()
