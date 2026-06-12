"""Process entry point. Runs the agents and reporters configured for this node.

Phase B: price watcher, news watcher, Claude triage, coin analyst, daily
digest, Telegram inbound commands, and Telegram outbound alerts. Every
optional component checks its own configuration and exits early with a log
line if unconfigured — the process always starts cleanly.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable

from cryptobot.agents.coin_analyst import run_coin_analyst
from cryptobot.agents.digest import run_digest
from cryptobot.agents.triage import run_triage
from cryptobot.bus import close_bus, get_bus
from cryptobot.config import get_settings
from cryptobot.db import close_pool, get_pool, run_migrations
from cryptobot.logging import get_logger
from cryptobot.reporters.telegram_in import run_telegram_in
from cryptobot.reporters.telegram_out import run_alert_sender
from cryptobot.watchers.macro_news import run_macro_news_watcher
from cryptobot.watchers.news import run_news_watcher
from cryptobot.watchers.prices import run_price_watcher

log = get_logger(__name__)


async def _guarded(
    name: str, runner: Callable[[asyncio.Event], Awaitable[None]], stop: asyncio.Event
) -> None:
    """Run a component; log and exit (don't kill the process) if it dies."""
    try:
        await runner(stop)
        log.info("task.exited", task=name)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("task.crashed", task=name)


async def amain() -> None:
    log.info("cryptobot.starting")
    settings = get_settings()

    # Connectivity preflight
    await get_pool()
    await run_migrations()
    bus = get_bus()
    if not await bus.ping():
        raise RuntimeError("Redis ping failed")

    stop = asyncio.Event()

    def _shutdown(*_):
        log.info("cryptobot.shutdown_requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            # Windows: signal handlers via loop aren't supported.
            signal.signal(sig, _shutdown)

    runners: list[tuple[str, Callable[[asyncio.Event], Awaitable[None]]]] = [
        ("price_watcher", run_price_watcher),
        ("news_watcher", run_news_watcher),
        ("macro_news_watcher", run_macro_news_watcher),
        ("triage", run_triage),
        ("coin_analyst", run_coin_analyst),
        ("digest", run_digest),
        ("telegram_in", run_telegram_in),
    ]
    if settings.telegram_bot_token:
        runners.append(("telegram_out", run_alert_sender))
    else:
        log.info("telegram_out.disabled", reason="no bot token")

    tasks = [
        asyncio.create_task(_guarded(name, runner, stop), name=name)
        for name, runner in runners
    ]

    log.info("cryptobot.running", tasks=[t.get_name() for t in tasks])

    await stop.wait()
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    await close_bus()
    await close_pool()
    log.info("cryptobot.stopped")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
