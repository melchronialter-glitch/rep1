"""Process entry point. Runs the agents and reporters configured for this node.

Phase B: price watcher, news watcher, Claude triage, coin analyst, daily
digest, Telegram inbound commands, and Telegram outbound alerts.
Phase C: chain watchers — pump.fun (always on), Raydium via Helius, EVM
pairs via Alchemy, BSC via a configurable WS RPC.
Phase D: rug detector — safety screen + deterministic 0–100 risk score for
every new pair, tiered routing to strict/medium/firehose.
Phase E: social listeners — Telegram groups, X/Twitter, Reddit, call parser,
translator.
Phase F: whale watcher, smart money agent, narrative tracker, dev activity.
Phase G: indicator engine, orderbook, derivatives, sentiment, launch radar,
econ calendar, macro impact agent.
Phase H: rug forensic agent (learning loop scaffolding).
Every optional component checks its own configuration and exits early with a
log line if unconfigured — the process always starts cleanly.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable

from cryptobot.agents.coin_analyst import run_coin_analyst
from cryptobot.agents.digest import run_digest
from cryptobot.agents.indicator_engine import run_indicator_engine
from cryptobot.agents.macro_impact import run_macro_impact
from cryptobot.agents.narrative_tracker import run_narrative_tracker
from cryptobot.agents.rug_detector import run_rug_detector
from cryptobot.agents.rug_forensic import run_rug_forensic as run_rug_forensic_agent
from cryptobot.agents.smart_money_agent import run_smart_money_agent
from cryptobot.agents.tg_call_parser import run_tg_call_parser
from cryptobot.agents.translator import run_translator
from cryptobot.agents.triage import run_triage
from cryptobot.bus import close_bus, get_bus
from cryptobot.config import get_settings
from cryptobot.db import close_pool, get_pool, run_migrations
from cryptobot.logging import get_logger
from cryptobot.reporters.telegram_in import run_telegram_in
from cryptobot.reporters.telegram_out import run_alert_sender
from cryptobot.watchers.bsc import run_bsc_pair_watcher
from cryptobot.watchers.derivatives import run_derivatives
from cryptobot.watchers.dev_activity import run_dev_activity
from cryptobot.watchers.discord_listener import run_discord_listener
from cryptobot.watchers.econ_calendar import run_econ_calendar
from cryptobot.watchers.evm.pairs import run_evm_pair_watcher
from cryptobot.watchers.launch_radar import run_launch_radar
from cryptobot.watchers.macro_news import run_macro_news_watcher
from cryptobot.watchers.news import run_news_watcher
from cryptobot.watchers.orderbook import run_orderbook
from cryptobot.watchers.prices import run_price_watcher
from cryptobot.watchers.reddit_listener import run_reddit_listener
from cryptobot.watchers.sentiment_index import run_sentiment_index
from cryptobot.watchers.solana.dex import run_solana_dex_watcher
from cryptobot.watchers.solana.pumpfun import run_pumpfun_watcher
from cryptobot.watchers.telegram_listener import run_telegram_listener
from cryptobot.watchers.whale_watcher import run_whale_watcher
from cryptobot.watchers.x import run_x_watcher

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
            signal.signal(sig, _shutdown)

    runners: list[tuple[str, Callable[[asyncio.Event], Awaitable[None]]]] = [
        # Phase B
        ("price_watcher", run_price_watcher),
        ("news_watcher", run_news_watcher),
        ("macro_news_watcher", run_macro_news_watcher),
        # Phase C chain watchers — pump.fun always on; others self-disable
        ("pumpfun_watcher", run_pumpfun_watcher),
        ("solana_dex_watcher", run_solana_dex_watcher),
        ("evm_pair_watcher", run_evm_pair_watcher),
        ("bsc_pair_watcher", run_bsc_pair_watcher),
        # Phase D
        ("triage", run_triage),
        ("rug_detector", run_rug_detector),
        ("coin_analyst", run_coin_analyst),
        ("digest", run_digest),
        ("telegram_in", run_telegram_in),
        # Phase E
        ("telegram_listener", run_telegram_listener),
        ("tg_call_parser", run_tg_call_parser),
        ("x_watcher", run_x_watcher),
        ("reddit_listener", run_reddit_listener),
        ("discord_listener", run_discord_listener),
        ("translator", run_translator),
        # Phase F
        ("whale_watcher", run_whale_watcher),
        ("smart_money_agent", run_smart_money_agent),
        ("narrative_tracker", run_narrative_tracker),
        ("dev_activity_watcher", run_dev_activity),
        # Phase G
        ("indicator_engine", run_indicator_engine),
        ("orderbook_watcher", run_orderbook),
        ("derivatives_watcher", run_derivatives),
        ("sentiment_index_watcher", run_sentiment_index),
        ("launch_radar_watcher", run_launch_radar),
        ("econ_calendar_watcher", run_econ_calendar),
        ("macro_impact_agent", run_macro_impact),
        # Phase H
        ("rug_forensic_agent", run_rug_forensic_agent),
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
        # Phase C chain watchers. pump.fun needs no key — always on; the
        # others self-disable with a log line when unconfigured.
        ("pumpfun_watcher", run_pumpfun_watcher),
        ("solana_dex_watcher", run_solana_dex_watcher),
        ("evm_pair_watcher", run_evm_pair_watcher),
        ("bsc_pair_watcher", run_bsc_pair_watcher),
        ("triage", run_triage),
        # Phase D: deterministic safety screen + risk scoring for new pairs.
        ("rug_detector", run_rug_detector),
        ("coin_analyst", run_coin_analyst),
        ("digest", run_digest),
        ("telegram_in", run_telegram_in),
        # Phase E: social listeners.
        ("telegram_listener", run_telegram_listener),
        ("tg_call_parser", run_tg_call_parser),
        ("x_watcher", run_x_watcher),
        ("reddit_listener", run_reddit_listener),
        ("discord_listener", run_discord_listener),
        ("translator", run_translator),
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
