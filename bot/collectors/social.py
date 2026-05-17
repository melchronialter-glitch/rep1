"""
Reddit social sentiment collector using PRAW.

Scrapes top posts from r/CryptoCurrency, r/Bitcoin, and r/ethereum
to gauge retail sentiment and trending narratives.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

SUBREDDITS = ["CryptoCurrency", "Bitcoin", "ethereum"]
TOP_POSTS_LIMIT = 15  # per subreddit


def _fetch_reddit_sync(
    client_id: str,
    client_secret: str,
    user_agent: str,
    subreddits: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """
    Synchronous Reddit fetch (PRAW is sync-only).
    Runs in an executor thread to avoid blocking the event loop.
    """
    try:
        import praw  # type: ignore[import]
    except ImportError:
        logger.error("praw is not installed. Run: pip install praw")
        return []

    posts: list[dict[str, Any]] = []
    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            check_for_async=False,
        )
        for sub_name in subreddits:
            try:
                subreddit = reddit.subreddit(sub_name)
                for post in subreddit.hot(limit=limit):
                    # Skip stickied meta posts
                    if post.stickied:
                        continue
                    posts.append({
                        "subreddit": sub_name,
                        "post_id": post.id,
                        "title": post.title,
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "url": post.url,
                        "selftext": (post.selftext or "")[:2000],
                    })
            except Exception as exc:
                logger.warning("Reddit fetch failed for r/%s: %s", sub_name, exc)
    except Exception as exc:
        logger.error("Failed to initialise Reddit client: %s", exc)

    logger.info("Fetched %d Reddit posts from %d subreddits", len(posts), len(subreddits))
    return posts


async def fetch_reddit_posts(
    client_id: str,
    client_secret: str,
    user_agent: str,
    subreddits: list[str] | None = None,
    limit: int = TOP_POSTS_LIMIT,
) -> list[dict[str, Any]]:
    """
    Async wrapper around the PRAW synchronous API.
    Raises gracefully if credentials are missing.
    """
    if not client_id or not client_secret:
        logger.warning("Reddit credentials not set; skipping social fetch")
        return []

    subs = subreddits or SUBREDDITS
    loop = asyncio.get_event_loop()
    posts = await loop.run_in_executor(
        None,
        _fetch_reddit_sync,
        client_id,
        client_secret,
        user_agent,
        subs,
        limit,
    )
    return posts


def format_reddit_summary(posts: list[dict[str, Any]], max_posts: int = 20) -> str:
    """Build compact Reddit post summary for prompt injection."""
    if not posts:
        return "No recent Reddit posts available."

    lines = []
    for post in sorted(posts, key=lambda p: p.get("score", 0), reverse=True)[:max_posts]:
        score = post.get("score", 0)
        comments = post.get("num_comments", 0)
        sub = post.get("subreddit", "?")
        title = post.get("title", "").strip()
        lines.append(f"- [r/{sub}] ↑{score} 💬{comments} | {title}")

    return "\n".join(lines)
