"""X (Twitter) adapter base class and watcher runner.

Two adapters are supported:
- Apify (``APIFY_API_TOKEN``) — uses the Twitter Scraper actor; free tier is
  limited but sufficient for polling ~5 handles every 2 minutes.
- TwitterAPI.io (``TWITTERAPI_IO_KEY``) — dedicated endpoint, higher rate limit.

Both adapters implement the same interface.  The watcher tries Apify first; if
unconfigured it falls back to TwitterAPI.io; if neither is configured it
self-disables.  Each poll cycle yields ``XTweet`` dicts which the watcher
deduplicates via a Redis seen-set and publishes to ``social.x.tweet``.

Only tweets that contain a contract address or ``$TICKER`` mention are
archived to Postgres (``tweets`` table); the rest are published without
persistence.
"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from typing import Any, TypedDict

from cryptobot.agents.tg_call_parser import BUY_LANGUAGE_RE, TICKER_RE, find_addresses
from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.topics import SOCIAL_X_TWEET

log = get_logger(__name__)

SEEN_KEY = "cb:seen:tweets"
SEEN_TTL_S = 7 * 24 * 3600  # 7 days

_HANDLE_STRIP = re.compile(r"^@+")


def _normalise_handle(h: str) -> str:
    return _HANDLE_STRIP.sub("", h).strip().lower()


class XTweet(TypedDict, total=False):
    id: str
    handle: str
    text: str
    likes: int
    retweets: int
    url: str
    created_at: str


class XAdapter(ABC):
    """Abstract base — one method to implement."""

    @abstractmethod
    async def fetch_tweets(self, handle: str, limit: int = 20) -> list[XTweet]:
        """Return the latest tweets for *handle*. Never raises (degrade cleanly)."""


def _is_signal_tweet(text: str) -> bool:
    """True when the tweet contains an address, ticker, or buy-language — worth archiving."""
    if find_addresses(text):
        return True
    if TICKER_RE.search(text):
        return True
    if BUY_LANGUAGE_RE.search(text):
        return True
    return False


async def _persist_tweet(tweet: XTweet) -> None:
    try:
        await execute(
            "INSERT INTO tweets (id, handle, text, likes, retweets, url, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING",
            tweet.get("id", ""),
            tweet.get("handle", ""),
            tweet.get("text", ""),
            tweet.get("likes", 0),
            tweet.get("retweets", 0),
            tweet.get("url", ""),
            tweet.get("created_at", ""),
        )
    except Exception:
        log.exception("x_watcher.persist.failed", tweet_id=tweet.get("id"))


async def _poll_handle(
    adapter: XAdapter,
    handle: str,
) -> None:
    """Fetch latest tweets for one handle, deduplicate, and publish."""
    bus = get_bus()
    redis = bus._redis  # type: ignore[attr-defined]
    try:
        tweets = await adapter.fetch_tweets(handle)
    except Exception:
        log.exception("x_watcher.fetch.failed", handle=handle)
        return

    for tweet in tweets:
        tweet_id = tweet.get("id", "")
        if not tweet_id:
            continue
        seen_key = f"{SEEN_KEY}:{tweet_id}"
        if await redis.get(seen_key):
            continue
        await redis.setex(seen_key, SEEN_TTL_S, "1")

        text = tweet.get("text", "")
        is_signal = _is_signal_tweet(text)
        if is_signal:
            await _persist_tweet(tweet)

        await bus.publish(
            SOCIAL_X_TWEET,
            dict(tweet),
            source="x_watcher",
            persist=is_signal,
        )
        log.debug("x_watcher.published", handle=handle, tweet_id=tweet_id, signal=is_signal)


async def run_x_watcher(stop_event: asyncio.Event | None = None) -> None:
    """Poll configured X handles periodically using whichever adapter is available."""
    from cryptobot.watchers.x.apify import ApifyAdapter
    from cryptobot.watchers.x.twitterapi import TwitterAPIAdapter

    settings = get_settings()
    handles = [_normalise_handle(h) for h in settings.x_watch_handle_list if h.strip()]
    if not handles:
        log.info("x_watcher.disabled", reason="X_WATCH_HANDLES is empty")
        return

    adapter: XAdapter | None = None
    if settings.apify_api_token:
        adapter = ApifyAdapter(settings.apify_api_token)
        log.info("x_watcher.adapter", adapter="apify", handles=handles)
    elif settings.twitterapi_io_key:
        adapter = TwitterAPIAdapter(settings.twitterapi_io_key)
        log.info("x_watcher.adapter", adapter="twitterapi_io", handles=handles)
    else:
        log.info("x_watcher.disabled", reason="neither APIFY_API_TOKEN nor TWITTERAPI_IO_KEY set")
        return

    poll_interval = settings.x_poll_interval_s
    log.info("x_watcher.started", handles=handles, interval_s=poll_interval)

    while not (stop_event and stop_event.is_set()):
        for handle in handles:
            if stop_event and stop_event.is_set():
                break
            await _poll_handle(adapter, handle)

        if stop_event:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=float(poll_interval))
            except TimeoutError:
                pass
        else:
            await asyncio.sleep(poll_interval)

    log.info("x_watcher.stopped")
