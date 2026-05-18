"""Postgres connection pool + migration runner."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import asyncpg

from cryptobot.config import get_settings
from cryptobot.logging import get_logger

log = get_logger(__name__)

_pool: asyncpg.Pool | None = None
MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Set up JSONB <-> dict codec on each new connection."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.postgres_dsn,
            min_size=1,
            max_size=10,
            init=_init_connection,
            command_timeout=30,
        )
        log.info("postgres.pool.opened", dsn_host=settings.postgres_host)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("postgres.pool.closed")


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    pool = await get_pool()
    return await pool.fetchrow(query, *args)


async def execute(query: str, *args: Any) -> str:
    pool = await get_pool()
    return await pool.execute(query, *args)


async def run_migrations() -> None:
    """Apply any pending .sql files from migrations/ in version order."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Bootstrap the migrations table if it doesn't exist yet
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied = {
            r["version"]
            for r in await conn.fetch("SELECT version FROM schema_migrations")
        }

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        try:
            version = int(path.stem.split("_", 1)[0])
        except ValueError:
            log.warning("migration.skip.bad_name", file=path.name)
            continue
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        log.info("migration.apply", version=version, file=path.name)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
        log.info("migration.applied", version=version)
