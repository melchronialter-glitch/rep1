"""News watcher — CryptoPanic API + RSS feeds.

Polls CryptoPanic every 5 minutes (skipped silently if no API key) and a set
of crypto RSS feeds every 10 minutes. Every new item is:

- deduped by URL via a Redis set (``cb:seen:news``, 7 day TTL)
- persisted to the ``news_items`` table
- published to ``news.crypto``
- additionally published to ``news.macro`` if the title matches macro
  keywords, and to ``news.macro.high_impact`` for strong-impact keywords

Both pollers run forever and survive any error with a log + backoff.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
import redis.asyncio as redis

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.topics import NEWS_CRYPTO, NEWS_MACRO, NEWS_MACRO_HIGH_IMPACT

log = get_logger(__name__)

CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"
CRYPTOPANIC_INTERVAL_S = 5 * 60
RSS_INTERVAL_S = 10 * 60
SEEN_KEY = "cb:seen:news"
SEEN_TTL_S = 7 * 24 * 3600

RSS_FEEDS: dict[str, str] = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
}

MACRO_KEYWORDS = [
    "fed", "fomc", "rate", "inflation", "cpi", "tariff", "treasury",
    "recession", "gdp", "unemployment", "powell", "ecb", "regulation",
    "sec", "etf approval",
]
HIGH_IMPACT_KEYWORDS = ["fomc", "rate decision", "cpi print", "emergency", "tariff"]

_macro_re = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in MACRO_KEYWORDS) + r")\b", re.IGNORECASE
)
_high_impact_re = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in HIGH_IMPACT_KEYWORDS) + r")\b", re.IGNORECASE
)


def classify_macro(title: str) -> tuple[bool, bool]:
    """Return (is_macro, is_high_impact) based on title keywords."""
    is_macro = bool(_macro_re.search(title))
    is_high = bool(_high_impact_re.search(title))
    return is_macro or is_high, is_high


async def _already_seen(r: redis.Redis, url: str) -> bool:
    """Atomically mark a URL as seen; return True if it was already there."""
    added = await r.sadd(SEEN_KEY, url)
    await r.expire(SEEN_KEY, SEEN_TTL_S)
    return added == 0


async def _persist_item(item: dict[str, Any], is_macro: bool) -> None:
    try:
        await execute(
            """
            INSERT INTO news_items (id, title, url, source, published_at, is_macro)
            VALUES ($1::uuid, $2, $3, $4, $5::timestamptz, $6)
            ON CONFLICT (url) DO NOTHING
            """,
            str(uuid.uuid4()),
            item["title"],
            item["url"],
            item["source"],
            item.get("published_at") or datetime.now(UTC).isoformat(),
            is_macro,
        )
    except Exception:
        log.exception("news.persist.failed", url=item.get("url"))


async def _emit(item: dict[str, Any]) -> None:
    """Publish a news item to the appropriate topics + persist it."""
    bus = get_bus()
    is_macro, is_high = classify_macro(item.get("title") or "")
    await _persist_item(item, is_macro)
    await bus.publish(NEWS_CRYPTO, item, source="news_watcher")
    if is_macro:
        await bus.publish(NEWS_MACRO, item, source="news_watcher")
    if is_high:
        await bus.publish(
            NEWS_MACRO_HIGH_IMPACT, {**item, "severity": "high"}, source="news_watcher"
        )
    log.info(
        "news.item", title=(item.get("title") or "")[:80],
        source=item.get("source"), macro=is_macro, high_impact=is_high,
    )


# ---- CryptoPanic -----------------------------------------------------------

async def _poll_cryptopanic(client: httpx.AsyncClient, r: redis.Redis, api_key: str) -> int:
    resp = await client.get(
        CRYPTOPANIC_URL, params={"auth_token": api_key, "kind": "news", "public": "true"}
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    emitted = 0
    for post in results:
        url = post.get("url") or ""
        title = post.get("title") or ""
        if not url or not title:
            continue
        if await _already_seen(r, url):
            continue
        currencies = [
            c.get("code") for c in (post.get("currencies") or []) if c.get("code")
        ]
        await _emit(
            {
                "title": title,
                "url": url,
                "source": (post.get("source") or {}).get("title") or "CryptoPanic",
                "published_at": post.get("published_at"),
                "summary": None,
                "currencies": currencies,
            }
        )
        emitted += 1
    return emitted


async def run_cryptopanic_poller(stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    if not settings.cryptopanic_api_key:
        log.info("news.cryptopanic.disabled", reason="no api key")
        return

    r = redis.from_url(settings.redis_url, decode_responses=True)
    log.info("news.cryptopanic.started", interval_s=CRYPTOPANIC_INTERVAL_S)
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        while not (stop_event and stop_event.is_set()):
            try:
                n = await _poll_cryptopanic(client, r, settings.cryptopanic_api_key)
                log.debug("news.cryptopanic.polled", new_items=n)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("news.cryptopanic.error", err=str(e))
            await asyncio.sleep(CRYPTOPANIC_INTERVAL_S)
    await r.aclose()


# ---- RSS -------------------------------------------------------------------

def _entry_published(entry: Any) -> str | None:
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw).isoformat()
            except (TypeError, ValueError):
                continue
    return None


async def _poll_rss(r: redis.Redis) -> int:
    emitted = 0
    loop = asyncio.get_running_loop()
    for source, feed_url in RSS_FEEDS.items():
        try:
            # feedparser is blocking — run it in the default executor
            feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
            for entry in feed.entries[:30]:
                url = getattr(entry, "link", "") or ""
                title = getattr(entry, "title", "") or ""
                if not url or not title:
                    continue
                if await _already_seen(r, url):
                    continue
                summary = getattr(entry, "summary", None)
                if summary:
                    summary = re.sub(r"<[^>]+>", "", summary)[:500].strip()
                await _emit(
                    {
                        "title": title,
                        "url": url,
                        "source": source,
                        "published_at": _entry_published(entry),
                        "summary": summary,
                        "currencies": None,
                    }
                )
                emitted += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("news.rss.feed_error", source=source, err=str(e))
    return emitted


async def run_rss_poller(stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    r = redis.from_url(settings.redis_url, decode_responses=True)
    log.info("news.rss.started", feeds=list(RSS_FEEDS), interval_s=RSS_INTERVAL_S)
    while not (stop_event and stop_event.is_set()):
        try:
            n = await _poll_rss(r)
            log.debug("news.rss.polled", new_items=n)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("news.rss.error", err=str(e))
        await asyncio.sleep(RSS_INTERVAL_S)
    await r.aclose()


async def run_news_watcher(stop_event: asyncio.Event | None = None) -> None:
    """Run both pollers concurrently."""
    await asyncio.gather(
        run_cryptopanic_poller(stop_event),
        run_rss_poller(stop_event),
    )
