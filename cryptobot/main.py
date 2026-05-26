"""Process entry point. Runs the agents and reporters configured for this node.

Phase A: triage agent + telegram outbound. Nothing else.
Later phases register their watchers/agents here behind feature flags.
"""

from __future__ import annotations

import asyncio
import signal

from cryptobot.agents.triage import run_triage
from cryptobot.bus import close_bus, get_bus
from cryptobot.db import close_pool, get_pool, run_migrations
from cryptobot.logging import get_logger
from cryptobot.reporters.telegram_out import run_alert_sender

log = get_logger(__name__)


async def amain() -> None:
    log.info("cryptobot.starting")

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

    tasks = [
        asyncio.create_task(run_triage(stop), name="triage"),
        asyncio.create_task(run_alert_sender(stop), name="telegram_out"),
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
