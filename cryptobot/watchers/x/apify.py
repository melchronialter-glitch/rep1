"""Apify adapter for X (Twitter) scraping.

Uses the public Apify platform API with the ``apidojo/tweet-scraper`` actor.
The actor is started as a synchronous run (``waitForFinish``) so each call
blocks up to ``_RUN_TIMEOUT_S`` seconds — suitable for a polling loop.

Apify free plan: ~100 actor-compute-units / month.  Polling 5 handles every
2 minutes uses roughly 30–50 CU/month, well within the free tier.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from cryptobot.logging import get_logger
from cryptobot.watchers.x.base import XAdapter, XTweet

log = get_logger(__name__)

_APIFY_BASE = "https://api.apify.com/v2"
_ACTOR_ID = "apidojo~tweet-scraper"
_RUN_TIMEOUT_S = 90
_TWEET_LIMIT = 20


class ApifyAdapter(XAdapter):
    def __init__(self, api_token: str) -> None:
        self._token = api_token

    async def fetch_tweets(self, handle: str, limit: int = _TWEET_LIMIT) -> list[XTweet]:
        url = f"{_APIFY_BASE}/acts/{_ACTOR_ID}/run-sync-get-dataset-items"
        params = {"token": self._token, "waitForFinish": _RUN_TIMEOUT_S}
        body: dict[str, Any] = {
            "twitterHandles": [handle],
            "maxItems": limit,
            "tweetsDesired": limit,
        }
        try:
            async with httpx.AsyncClient(timeout=_RUN_TIMEOUT_S + 15) as client:
                r = await client.post(url, params=params, json=body)
            if r.status_code != 200:
                log.warning("apify.bad_response", handle=handle, status=r.status_code)
                return []
            items = r.json()
            return [_parse(item, handle) for item in items if isinstance(item, dict)]
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("apify.fetch.failed", handle=handle)
            return []


def _parse(item: dict[str, Any], handle: str) -> XTweet:
    text = item.get("fullText") or item.get("text") or ""
    author = (item.get("author") or {}).get("userName") or handle
    tweet_id = str(item.get("id") or item.get("tweetId") or "")
    url = item.get("url") or (f"https://twitter.com/{author}/status/{tweet_id}" if tweet_id else "")
    return XTweet(
        id=tweet_id,
        handle=author.lower(),
        text=text,
        likes=int(item.get("likeCount") or 0),
        retweets=int(item.get("retweetCount") or 0),
        url=url,
        created_at=str(item.get("createdAt") or ""),
    )
