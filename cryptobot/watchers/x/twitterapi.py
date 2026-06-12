"""TwitterAPI.io adapter for X (Twitter) scraping.

Uses the ``/twitter/user/last_tweets`` endpoint.  Requires ``TWITTERAPI_IO_KEY``.
Free tier: 500 requests / month — polling 5 handles every 2 minutes (720
req/handle/day) will exhaust the free tier in hours.  Use this adapter only
as the primary when you have a paid plan, or as fallback behind Apify.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from cryptobot.logging import get_logger
from cryptobot.watchers.x.base import XAdapter, XTweet

log = get_logger(__name__)

_BASE = "https://api.twitterapi.io"
_TIMEOUT = 30


class TwitterAPIAdapter(XAdapter):
    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def fetch_tweets(self, handle: str, limit: int = 20) -> list[XTweet]:
        url = f"{_BASE}/twitter/user/last_tweets"
        headers = {"X-API-Key": self._key}
        params = {"userName": handle, "count": min(limit, 20)}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.get(url, headers=headers, params=params)
            if r.status_code != 200:
                log.warning("twitterapi.bad_response", handle=handle, status=r.status_code)
                return []
            data = r.json()
            tweets = data.get("tweets") or data.get("data") or []
            return [_parse(t, handle) for t in tweets if isinstance(t, dict)]
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("twitterapi.fetch.failed", handle=handle)
            return []


def _parse(item: dict[str, Any], handle: str) -> XTweet:
    text = item.get("text") or item.get("full_text") or ""
    tweet_id = str(item.get("id") or item.get("id_str") or "")
    author = item.get("author", {}) or {}
    username = (author.get("userName") or author.get("screen_name") or handle).lower()
    url = (
        item.get("url")
        or (f"https://twitter.com/{username}/status/{tweet_id}" if tweet_id else "")
    )
    return XTweet(
        id=tweet_id,
        handle=username,
        text=text,
        likes=int(item.get("likeCount") or item.get("favorite_count") or 0),
        retweets=int(item.get("retweetCount") or item.get("retweet_count") or 0),
        url=url,
        created_at=str(item.get("createdAt") or item.get("created_at") or ""),
    )
