"""Reddit listener — polls subreddits via the public JSON API (no key needed).

Uses Reddit's ``/r/<subreddit>/new.json`` endpoint (no OAuth, just a
descriptive User-Agent). Posts are deduplicated via a Redis seen-set. Only
posts that contain a contract address or ``$TICKER`` mention are archived to
Postgres; all posts are published to the bus (with ``persist=False`` for
non-signal posts).

Configurable via:
  ``REDDIT_SUBREDDITS`` — comma-separated subreddit names (default: CryptoCurrency,solana,CryptoMoonShots)
  ``REDDIT_POLL_INTERVAL_S`` — poll cycle in seconds (default: 300)
"""

from __future__ import annotations

import asyncio

import httpx

from cryptobot.agents.tg_call_parser import TICKER_RE, find_addresses
from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger
from cryptobot.topics import SOCIAL_REDDIT_POST

log = get_logger(__name__)

_BASE = "https://www.reddit.com"
_UA = "CryptoBot/1.0 (market-intelligence; contact via GitHub)"
_SEEN_KEY = "cb:seen:reddit"
_SEEN_TTL_S = 7 * 24 * 3600
_LIMIT = 25


def _is_signal_post(text: str) -> bool:
    return bool(find_addresses(text) or TICKER_RE.search(text))


async def _persist_post(payload: dict) -> None:
    try:
        await execute(
            "INSERT INTO reddit_posts (id, subreddit, title, text, url, score, author) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING",
            payload["id"],
            payload["subreddit"],
            payload["title"],
            payload["text"],
            payload["url"],
            payload["score"],
            payload["author"],
        )
    except Exception:
        log.exception("reddit_listener.persist.failed", post_id=payload.get("id"))


async def _poll_subreddit(subreddit: str, client: httpx.AsyncClient) -> None:
    bus = get_bus()
    redis = bus._redis  # type: ignore[attr-defined]
    url = f"{_BASE}/r/{subreddit}/new.json"
    try:
        r = await client.get(url, params={"limit": _LIMIT})
        if r.status_code != 200:
            log.warning("reddit_listener.bad_response", subreddit=subreddit, status=r.status_code)
            return
        data = r.json()
        posts = (data.get("data") or {}).get("children") or []
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("reddit_listener.fetch.failed", subreddit=subreddit)
        return

    for child in posts:
        post = (child.get("data") or {})
        post_id = post.get("id") or post.get("name") or ""
        if not post_id:
            continue
        seen_key = f"{_SEEN_KEY}:{post_id}"
        if await redis.get(seen_key):
            continue
        await redis.setex(seen_key, _SEEN_TTL_S, "1")

        title = post.get("title") or ""
        selftext = (post.get("selftext") or "")[:1000]
        combined = f"{title} {selftext}"
        is_signal = _is_signal_post(combined)

        payload = {
            "id": post_id,
            "subreddit": subreddit,
            "title": title,
            "text": selftext,
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "score": int(post.get("score") or 0),
            "author": str(post.get("author") or ""),
        }

        if is_signal:
            await _persist_post(payload)

        await bus.publish(SOCIAL_REDDIT_POST, payload, source="reddit_listener", persist=is_signal)
        log.debug("reddit_listener.published", subreddit=subreddit, post_id=post_id, signal=is_signal)


async def run_reddit_listener(stop_event: asyncio.Event | None = None) -> None:
    """Main loop: poll configured subreddits at the configured interval."""
    settings = get_settings()
    subreddits = settings.reddit_subreddit_list
    if not subreddits:
        log.info("reddit_listener.disabled", reason="REDDIT_SUBREDDITS is empty")
        return

    poll_interval = settings.reddit_poll_interval_s
    log.info("reddit_listener.started", subreddits=subreddits, interval_s=poll_interval)

    headers = {"User-Agent": _UA}
    async with httpx.AsyncClient(
        headers=headers, timeout=20.0, follow_redirects=True
    ) as client:
        while not (stop_event and stop_event.is_set()):
            for sub in subreddits:
                if stop_event and stop_event.is_set():
                    break
                await _poll_subreddit(sub, client)

            try:
                await asyncio.wait_for(
                    asyncio.shield(stop_event.wait()) if stop_event else asyncio.sleep(poll_interval),
                    timeout=float(poll_interval),
                )
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                raise

    log.info("reddit_listener.stopped")
