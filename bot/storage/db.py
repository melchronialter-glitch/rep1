"""
SQLite persistence layer using aiosqlite.

Tables
------
prices        – snapshot of coin prices at a point in time
news_items    – crypto / macro news articles (deduplicated by URL)
reddit_posts  – top Reddit posts per subreddit
reports       – generated analysis reports
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS prices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    coin_id         TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    price_usd       REAL    NOT NULL,
    market_cap_usd  REAL,
    volume_24h_usd  REAL,
    change_1h_pct   REAL,
    change_24h_pct  REAL,
    change_7d_pct   REAL,
    collected_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prices_coin_collected
    ON prices (coin_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS news_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,           -- 'cryptopanic' | 'rss' | 'newsapi'
    url          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    body         TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    sentiment    TEXT,                    -- optional: positive / negative / neutral
    extra_json   TEXT                     -- source-specific fields as JSON
);

CREATE INDEX IF NOT EXISTS idx_news_collected
    ON news_items (collected_at DESC);

CREATE TABLE IF NOT EXISTS reddit_posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    subreddit      TEXT NOT NULL,
    post_id        TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    score          INTEGER,
    num_comments   INTEGER,
    url            TEXT,
    selftext       TEXT,
    collected_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reddit_collected
    ON reddit_posts (collected_at DESC);

CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type   TEXT NOT NULL,   -- 'market' | 'macro' | 'daily_digest' | 'alert'
    markdown_body TEXT NOT NULL,
    html_body     TEXT,
    created_at    TEXT NOT NULL,
    sent_telegram INTEGER NOT NULL DEFAULT 0,
    sent_email    INTEGER NOT NULL DEFAULT 0,
    meta_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_reports_created
    ON reports (created_at DESC);
"""


class Database:
    """Async SQLite wrapper."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("Database connected: %s", self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")

    @asynccontextmanager
    async def _cursor(self) -> AsyncIterator[aiosqlite.Cursor]:
        assert self._conn is not None, "Database not connected – call connect() first"
        async with self._conn.cursor() as cur:
            yield cur

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    async def insert_prices(self, prices: list[dict[str, Any]]) -> int:
        """Bulk-insert price snapshots. Returns number of rows inserted."""
        rows: list[tuple[Any, ...]] = []
        now = datetime.utcnow().isoformat()
        for p in prices:
            rows.append((
                p["id"],
                p.get("symbol", ""),
                p.get("name", ""),
                p.get("current_price", 0.0),
                p.get("market_cap"),
                p.get("total_volume"),
                p.get("price_change_percentage_1h_in_currency"),
                p.get("price_change_percentage_24h"),
                p.get("price_change_percentage_7d_in_currency"),
                now,
            ))
        async with self._cursor() as cur:
            await cur.executemany(
                """INSERT INTO prices
                   (coin_id, symbol, name, price_usd, market_cap_usd,
                    volume_24h_usd, change_1h_pct, change_24h_pct, change_7d_pct,
                    collected_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        await self._conn.commit()  # type: ignore[union-attr]
        return len(rows)

    async def get_latest_prices(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent price row per coin."""
        async with self._cursor() as cur:
            await cur.execute(
                """SELECT p.*
                   FROM prices p
                   INNER JOIN (
                       SELECT coin_id, MAX(collected_at) AS max_at
                       FROM prices
                       GROUP BY coin_id
                   ) latest ON p.coin_id = latest.coin_id
                          AND p.collected_at = latest.max_at
                   ORDER BY p.market_cap_usd DESC NULLS LAST
                   LIMIT ?""",
                (limit,),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # News
    # ------------------------------------------------------------------

    async def insert_news_items(self, items: list[dict[str, Any]]) -> int:
        """Upsert news items (ignore duplicates by URL). Returns inserted count."""
        inserted = 0
        now = datetime.utcnow().isoformat()
        async with self._cursor() as cur:
            for item in items:
                extra = {k: v for k, v in item.items()
                         if k not in ("source", "url", "title", "body",
                                      "published_at", "sentiment")}
                try:
                    await cur.execute(
                        """INSERT OR IGNORE INTO news_items
                           (source, url, title, body, published_at,
                            collected_at, sentiment, extra_json)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            item.get("source", "unknown"),
                            item["url"],
                            item.get("title", ""),
                            item.get("body"),
                            item.get("published_at"),
                            now,
                            item.get("sentiment"),
                            json.dumps(extra) if extra else None,
                        ),
                    )
                    if cur.rowcount:
                        inserted += 1
                except Exception as exc:
                    logger.warning("Failed to insert news item %s: %s",
                                   item.get("url"), exc)
        await self._conn.commit()  # type: ignore[union-attr]
        return inserted

    async def get_recent_news(
        self, source: str | None = None, hours: int = 8, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self._cursor() as cur:
            if source:
                await cur.execute(
                    """SELECT * FROM news_items
                       WHERE source = ?
                         AND collected_at >= datetime('now', ? || ' hours')
                       ORDER BY collected_at DESC LIMIT ?""",
                    (source, f"-{hours}", limit),
                )
            else:
                await cur.execute(
                    """SELECT * FROM news_items
                       WHERE collected_at >= datetime('now', ? || ' hours')
                       ORDER BY collected_at DESC LIMIT ?""",
                    (f"-{hours}", limit),
                )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Reddit
    # ------------------------------------------------------------------

    async def insert_reddit_posts(self, posts: list[dict[str, Any]]) -> int:
        inserted = 0
        now = datetime.utcnow().isoformat()
        async with self._cursor() as cur:
            for post in posts:
                try:
                    await cur.execute(
                        """INSERT OR IGNORE INTO reddit_posts
                           (subreddit, post_id, title, score, num_comments,
                            url, selftext, collected_at)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            post.get("subreddit", ""),
                            post["post_id"],
                            post.get("title", ""),
                            post.get("score"),
                            post.get("num_comments"),
                            post.get("url"),
                            post.get("selftext", "")[:2000],
                            now,
                        ),
                    )
                    if cur.rowcount:
                        inserted += 1
                except Exception as exc:
                    logger.warning("Failed to insert reddit post %s: %s",
                                   post.get("post_id"), exc)
        await self._conn.commit()  # type: ignore[union-attr]
        return inserted

    async def get_recent_reddit_posts(
        self, hours: int = 8, limit: int = 30
    ) -> list[dict[str, Any]]:
        async with self._cursor() as cur:
            await cur.execute(
                """SELECT * FROM reddit_posts
                   WHERE collected_at >= datetime('now', ? || ' hours')
                   ORDER BY score DESC LIMIT ?""",
                (f"-{hours}", limit),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    async def insert_report(
        self,
        report_type: str,
        markdown_body: str,
        html_body: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        now = datetime.utcnow().isoformat()
        async with self._cursor() as cur:
            await cur.execute(
                """INSERT INTO reports
                   (report_type, markdown_body, html_body, created_at, meta_json)
                   VALUES (?,?,?,?,?)""",
                (
                    report_type,
                    markdown_body,
                    html_body,
                    now,
                    json.dumps(meta) if meta else None,
                ),
            )
            report_id = cur.lastrowid
        await self._conn.commit()  # type: ignore[union-attr]
        return report_id  # type: ignore[return-value]

    async def mark_report_sent(
        self, report_id: int, channel: str
    ) -> None:
        """channel: 'telegram' | 'email'"""
        col = f"sent_{channel}"
        async with self._cursor() as cur:
            await cur.execute(
                f"UPDATE reports SET {col} = 1 WHERE id = ?",  # noqa: S608
                (report_id,),
            )
        await self._conn.commit()  # type: ignore[union-attr]

    async def get_recent_reports(
        self, report_type: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        async with self._cursor() as cur:
            if report_type:
                await cur.execute(
                    "SELECT * FROM reports WHERE report_type=? ORDER BY created_at DESC LIMIT ?",
                    (report_type, limit),
                )
            else:
                await cur.execute(
                    "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
