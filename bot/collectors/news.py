"""
Crypto news collector.

Sources:
  1. CryptoPanic API (free tier) – structured crypto news with sentiment
  2. RSS feeds (CoinDesk, CoinTelegraph) – as fallback / supplement
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

try:
    import feedparser  # type: ignore[import]
    _FEEDPARSER_AVAILABLE = True
except ImportError:
    feedparser = None  # type: ignore[assignment]
    _FEEDPARSER_AVAILABLE = False

logger = logging.getLogger(__name__)

CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1/posts/"

RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
]


async def fetch_cryptopanic(
    api_key: str,
    filter_type: str = "hot",
    limit: int = 30,
    timeout: int = 20,
) -> list[dict[str, Any]]:
    """
    Fetch posts from CryptoPanic.

    filter_type: 'hot' | 'rising' | 'bullish' | 'bearish' | 'important' | 'lol'
    """
    params: dict[str, Any] = {
        "auth_token": api_key,
        "filter": filter_type,
        "public": "true",
        "kind": "news",
    }
    logger.info("Fetching CryptoPanic news (filter=%s)…", filter_type)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                CRYPTOPANIC_BASE,
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except Exception as exc:
        logger.error("CryptoPanic request failed: %s", exc)
        return []

    items: list[dict[str, Any]] = []
    for post in (data.get("results") or [])[:limit]:
        currencies = [c.get("code", "") for c in (post.get("currencies") or [])]
        items.append({
            "source": "cryptopanic",
            "url": post.get("url") or post.get("source", {}).get("url", ""),
            "title": post.get("title", ""),
            "body": None,
            "published_at": post.get("published_at"),
            "sentiment": _map_sentiment(post.get("votes")),
            "currencies": currencies,
            "domain": post.get("domain", ""),
        })

    logger.info("Fetched %d items from CryptoPanic", len(items))
    return items


def _map_sentiment(votes: dict | None) -> str | None:
    if not votes:
        return None
    positive = votes.get("positive", 0) or 0
    negative = votes.get("negative", 0) or 0
    if positive > negative * 1.5:
        return "positive"
    if negative > positive * 1.5:
        return "negative"
    return "neutral"


async def fetch_rss_feeds(
    timeout: int = 20,
) -> list[dict[str, Any]]:
    """Parse RSS feeds and return normalised news items."""
    if not _FEEDPARSER_AVAILABLE:
        logger.warning("feedparser not installed; skipping RSS feeds. Run: pip install feedparser")
        return []

    items: list[dict[str, Any]] = []
    for feed_name, feed_url in RSS_FEEDS:
        try:
            # feedparser is synchronous; run in executor to not block
            import asyncio
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
            for entry in feed.entries[:15]:
                pub = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        pub = datetime(*entry.published_parsed[:6]).isoformat()
                    except Exception:
                        pass
                items.append({
                    "source": "rss",
                    "url": entry.get("link", ""),
                    "title": entry.get("title", ""),
                    "body": entry.get("summary", "")[:500] if entry.get("summary") else None,
                    "published_at": pub,
                    "feed_name": feed_name,
                })
        except Exception as exc:
            logger.warning("RSS feed %s failed: %s", feed_name, exc)

    logger.info("Fetched %d items from RSS feeds", len(items))
    return items


async def collect_crypto_news(
    cryptopanic_api_key: str,
) -> list[dict[str, Any]]:
    """Aggregate all crypto news sources."""
    import asyncio
    results = await asyncio.gather(
        fetch_cryptopanic(cryptopanic_api_key),
        fetch_rss_feeds(),
        return_exceptions=True,
    )
    combined: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, list):
            combined.extend(r)
        else:
            logger.error("News collection error: %s", r)
    return combined


def format_news_summary(items: list[dict[str, Any]], max_items: int = 20) -> str:
    """Build compact news text for prompt injection."""
    lines = []
    for item in items[:max_items]:
        sentiment_tag = f" [{item.get('sentiment', '')}]" if item.get("sentiment") else ""
        source = item.get("feed_name") or item.get("source", "unknown")
        lines.append(f"- [{source}]{sentiment_tag} {item.get('title', '')}")
    return "\n".join(lines) if lines else "No recent crypto news available."
