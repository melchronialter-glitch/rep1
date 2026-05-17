"""
Macro news collector using NewsAPI.org.

Searches for macro-economic topics: Fed policy, inflation, tariffs, GDP,
recession signals, and global economic events.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

NEWSAPI_BASE = "https://newsapi.org/v2/everything"

# Keywords for macro-economic relevance
MACRO_QUERIES = [
    "federal reserve interest rates",
    "inflation CPI",
    "tariff trade war",
    "recession GDP",
    "FOMC monetary policy",
    "unemployment jobs report",
]

# Sources known for quality economic coverage
PREFERRED_SOURCES = [
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "cnbc.com",
    "marketwatch.com",
]


async def fetch_macro_news(
    api_key: str,
    lookback_hours: int = 8,
    max_results: int = 30,
    timeout: int = 20,
) -> list[dict[str, Any]]:
    """
    Fetch macro-economic news from NewsAPI.

    Combines multiple query terms and deduplicates by URL.
    """
    if not api_key:
        logger.warning("NEWS_API_KEY not set; skipping macro news fetch")
        return []

    from_date = (datetime.utcnow() - timedelta(hours=lookback_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    seen_urls: set[str] = set()
    all_items: list[dict[str, Any]] = []

    async with aiohttp.ClientSession() as session:
        for query in MACRO_QUERIES:
            if len(all_items) >= max_results:
                break
            params: dict[str, Any] = {
                "q": query,
                "from": from_date,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": min(10, max_results - len(all_items)),
                "apiKey": api_key,
            }
            try:
                async with session.get(
                    NEWSAPI_BASE,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 401:
                        logger.error("NewsAPI: invalid API key")
                        return all_items
                    if resp.status == 429:
                        logger.warning("NewsAPI: rate limited")
                        break
                    resp.raise_for_status()
                    data = await resp.json()
            except aiohttp.ClientResponseError as exc:
                logger.warning("NewsAPI HTTP error %s for query '%s': %s",
                               exc.status, query, exc.message)
                continue
            except Exception as exc:
                logger.warning("NewsAPI request failed for query '%s': %s", query, exc)
                continue

            for article in data.get("articles") or []:
                url = article.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Parse published date
                pub_at = None
                raw_pub = article.get("publishedAt")
                if raw_pub:
                    try:
                        pub_at = datetime.strptime(raw_pub, "%Y-%m-%dT%H:%M:%SZ").isoformat()
                    except ValueError:
                        pub_at = raw_pub

                source_name = (article.get("source") or {}).get("name", "newsapi")
                description = article.get("description") or ""
                content_snippet = article.get("content") or ""
                # NewsAPI free tier truncates content at 200 chars; use description
                body = description[:500] if description else content_snippet[:500]

                all_items.append({
                    "source": "newsapi",
                    "url": url,
                    "title": article.get("title", ""),
                    "body": body or None,
                    "published_at": pub_at,
                    "sentiment": None,
                    "feed_name": source_name,
                    "query": query,
                })

    logger.info("Fetched %d macro news items from NewsAPI", len(all_items))
    return all_items


def format_macro_summary(items: list[dict[str, Any]], max_items: int = 15) -> str:
    """Build compact macro news text for prompt injection."""
    if not items:
        return "No recent macro-economic news available."

    lines = []
    for item in items[:max_items]:
        source = item.get("feed_name") or "unknown"
        title = item.get("title", "").strip()
        query_tag = item.get("query", "")
        # Group by query theme
        lines.append(f"- [{source}] ({query_tag}) {title}")

    return "\n".join(lines)
