"""
CryptoBot entry point.

Initialises config, database, and the APScheduler, then runs
the asyncio event loop indefinitely until interrupted.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

logger = logging.getLogger(__name__)


async def run() -> None:
    """Main coroutine: set up all components and run the scheduler."""
    from bot.config import Config
    from bot.storage.db import Database
    from bot.scheduler import CryptoBotScheduler

    # ── Config ────────────────────────────────────────────────────────────
    try:
        config = Config.from_env()
    except EnvironmentError as exc:
        logger.critical("Configuration error: %s", exc)
        sys.exit(1)

    # ── Database ──────────────────────────────────────────────────────────
    db = Database(config.db_path)
    await db.connect()

    # ── Scheduler ─────────────────────────────────────────────────────────
    scheduler = CryptoBotScheduler(config=config, db=db)
    scheduler.start()

    logger.info("CryptoBot started. Press Ctrl+C to stop.")
    logger.info("Scheduled jobs:")
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        logger.info("  %-30s next run: %s", job.name, next_run)

    # ── Shutdown handling ─────────────────────────────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down…")
        scheduler.stop()
        await db.close()
        logger.info("CryptoBot stopped cleanly.")


def main() -> None:
    """CLI entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
