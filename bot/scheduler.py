"""
APScheduler setup with all job definitions.

Schedule:
  Every 4h  → collect prices + crypto news → market analysis → queue report
  Every 6h  → collect macro news + reddit → macro analysis
  Daily 07:00 UTC → send comprehensive daily digest
  Smart alert: if BTC/ETH >5% move detected → send immediate alert
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import Config
from bot.storage.db import Database
from bot.collectors import prices as price_collector
from bot.collectors import news as news_collector
from bot.collectors import macro as macro_collector
from bot.collectors import social as social_collector
from bot.analyzers.market import MarketAnalyzer
from bot.analyzers.macro import MacroAnalyzer
from bot.reporters.formatter import (
    format_market_report_md,
    format_market_report_html,
    format_macro_report_md,
    format_macro_report_html,
    format_daily_digest_md,
    format_daily_digest_html,
    format_alert_md,
)
from bot.reporters.telegram_sender import TelegramSender
from bot.reporters.email_sender import EmailSender

logger = logging.getLogger(__name__)


class CryptoBotScheduler:
    """
    Manages all scheduled jobs for the crypto intelligence bot.
    """

    def __init__(self, config: Config, db: Database) -> None:
        self._config = config
        self._db = db

        # Analysis engines
        self._market_analyzer = MarketAnalyzer(api_key=config.anthropic_api_key)
        self._macro_analyzer = MacroAnalyzer(api_key=config.anthropic_api_key)

        # Reporters
        self._telegram = TelegramSender(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        self._email = EmailSender(
            smtp_host=config.email_smtp_host,
            smtp_port=config.email_smtp_port,
            smtp_user=config.email_smtp_user,
            smtp_pass=config.email_smtp_pass,
            from_addr=config.email_from,
            to_addr=config.email_to,
        )

        # In-memory cache for latest analyses (used by daily digest)
        self._latest_market_analysis: dict[str, Any] = {}
        self._latest_macro_analysis: dict[str, Any] = {}

        # APScheduler
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._register_jobs()

    def _register_jobs(self) -> None:
        """Register all scheduled jobs."""
        # Every 4 hours: market data collection + analysis
        self._scheduler.add_job(
            self._job_market_cycle,
            trigger=IntervalTrigger(hours=4),
            id="market_cycle",
            name="Market data collection & analysis",
            next_run_time=datetime.utcnow(),  # run immediately on startup
            misfire_grace_time=600,
        )

        # Every 6 hours: macro + social collection
        self._scheduler.add_job(
            self._job_macro_cycle,
            trigger=IntervalTrigger(hours=6),
            id="macro_cycle",
            name="Macro news & Reddit collection",
            misfire_grace_time=600,
        )

        # Daily 07:00 UTC: comprehensive digest
        self._scheduler.add_job(
            self._job_daily_digest,
            trigger=CronTrigger(hour=7, minute=0),
            id="daily_digest",
            name="Daily comprehensive digest",
            misfire_grace_time=1800,
        )

        logger.info("Registered %d scheduled jobs", len(self._scheduler.get_jobs()))

    # ─── Job implementations ─────────────────────────────────────────────────

    async def _job_market_cycle(self) -> None:
        """Collect prices + crypto news, run market analysis, optionally alert."""
        logger.info("Starting market cycle job")
        now = datetime.utcnow()

        # 1. Collect data concurrently
        try:
            prices_task = asyncio.create_task(
                price_collector.fetch_prices(per_page=20)
            )
            news_task = asyncio.create_task(
                news_collector.collect_crypto_news(self._config.cryptopanic_api_key)
            )
            prices, news_items = await asyncio.gather(prices_task, news_task)
        except Exception as exc:
            logger.error("Market cycle: data collection failed: %s", exc)
            return

        # 2. Persist to DB
        if prices:
            n = await self._db.insert_prices(prices)
            logger.info("Stored %d price records", n)
        if news_items:
            n = await self._db.insert_news_items(news_items)
            logger.info("Stored %d news items", n)

        # 3. Check for major price moves before analysis
        moves = price_collector.detect_major_moves(
            prices,
            threshold_pct=self._config.price_alert_threshold,
            window="1h",
        )

        # 4. Run market analysis
        try:
            analysis = await self._market_analyzer.analyze({
                "prices": prices,
                "news": news_items,
                "alert_threshold": self._config.price_alert_threshold,
            })
            self._latest_market_analysis = analysis
        except Exception as exc:
            logger.error("Market cycle: analysis failed: %s", exc)
            analysis = {}

        # 5. Format and store the market report
        if analysis:
            md_body = format_market_report_md(analysis, generated_at=now)
            html_body = format_market_report_html(analysis, generated_at=now)

            report_id = await self._db.insert_report(
                report_type="market",
                markdown_body=md_body,
                html_body=html_body,
                meta={"generated_at": now.isoformat()},
            )

            # 6. Send regular market report via Telegram
            ok_tg = await self._telegram.send_report(md_body)
            ok_em = await self._email.send_market_report(html_body, generated_at=now)

            if ok_tg:
                await self._db.mark_report_sent(report_id, "telegram")
            if ok_em:
                await self._db.mark_report_sent(report_id, "email")

            # 7. Send immediate alert if warranted
            alert_worthy = analysis.get("alert_worthy", False)
            if alert_worthy or moves:
                await self._send_price_alert(analysis, moves, now)

        logger.info("Market cycle job complete")

    async def _job_macro_cycle(self) -> None:
        """Collect macro news + Reddit, run macro analysis."""
        logger.info("Starting macro cycle job")
        now = datetime.utcnow()

        # 1. Collect data concurrently
        try:
            macro_task = asyncio.create_task(
                macro_collector.fetch_macro_news(
                    api_key=self._config.news_api_key,
                    lookback_hours=8,
                )
            )
            reddit_task = asyncio.create_task(
                social_collector.fetch_reddit_posts(
                    client_id=self._config.reddit_client_id,
                    client_secret=self._config.reddit_client_secret,
                    user_agent=self._config.reddit_user_agent,
                )
            )
            macro_news, reddit_posts = await asyncio.gather(macro_task, reddit_task)
        except Exception as exc:
            logger.error("Macro cycle: data collection failed: %s", exc)
            return

        # 2. Persist
        if macro_news:
            n = await self._db.insert_news_items(macro_news)
            logger.info("Stored %d macro news items", n)
        if reddit_posts:
            n = await self._db.insert_reddit_posts(reddit_posts)
            logger.info("Stored %d Reddit posts", n)

        # 3. Run macro analysis
        try:
            analysis = await self._macro_analyzer.analyze({
                "macro_news": macro_news,
                "reddit_posts": reddit_posts,
            })
            self._latest_macro_analysis = analysis
        except Exception as exc:
            logger.error("Macro cycle: analysis failed: %s", exc)
            analysis = {}

        # 4. Format, store, and send macro report
        if analysis:
            md_body = format_macro_report_md(analysis, generated_at=now)
            html_body = format_macro_report_html(analysis, generated_at=now)

            report_id = await self._db.insert_report(
                report_type="macro",
                markdown_body=md_body,
                html_body=html_body,
                meta={"generated_at": now.isoformat()},
            )

            ok_tg = await self._telegram.send_report(md_body)
            ok_em = await self._email.send_macro_report(html_body, generated_at=now)

            if ok_tg:
                await self._db.mark_report_sent(report_id, "telegram")
            if ok_em:
                await self._db.mark_report_sent(report_id, "email")

        logger.info("Macro cycle job complete")

    async def _job_daily_digest(self) -> None:
        """Send a comprehensive daily digest combining market + macro insights."""
        logger.info("Starting daily digest job")
        now = datetime.utcnow()

        # Fetch latest stored data for the digest
        market_analysis = self._latest_market_analysis
        macro_analysis = self._latest_macro_analysis

        # If we have no in-memory analyses (e.g. bot just started),
        # fetch from the DB and re-run analysis
        if not market_analysis:
            logger.info("Daily digest: no in-memory market analysis; fetching from DB")
            try:
                prices = await self._db.get_latest_prices(limit=20)
                news_items = await self._db.get_recent_news(hours=24, limit=50)
                if prices:
                    market_analysis = await self._market_analyzer.analyze({
                        "prices": prices,
                        "news": news_items,
                        "alert_threshold": self._config.price_alert_threshold,
                    })
            except Exception as exc:
                logger.error("Daily digest: market re-analysis failed: %s", exc)
                market_analysis = {"market_summary": "Market data unavailable at digest time."}

        if not macro_analysis:
            logger.info("Daily digest: no in-memory macro analysis; using placeholder")
            macro_analysis = {"macro_summary": "Macro data unavailable at digest time."}

        # Format and send
        md_body = format_daily_digest_md(market_analysis, macro_analysis, generated_at=now)
        html_body = format_daily_digest_html(market_analysis, macro_analysis, generated_at=now)

        report_id = await self._db.insert_report(
            report_type="daily_digest",
            markdown_body=md_body,
            html_body=html_body,
            meta={"generated_at": now.isoformat()},
        )

        ok_tg = await self._telegram.send_report(md_body)
        ok_em = await self._email.send_daily_digest(html_body, generated_at=now)

        if ok_tg:
            await self._db.mark_report_sent(report_id, "telegram")
        if ok_em:
            await self._db.mark_report_sent(report_id, "email")

        logger.info("Daily digest job complete (tg=%s, email=%s)", ok_tg, ok_em)

    async def _send_price_alert(
        self,
        analysis: dict[str, Any],
        moves: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        """Send an immediate price alert via Telegram."""
        logger.info("Sending price alert (moves=%d, analysis_alert=%s)",
                    len(moves), analysis.get("alert_worthy", False))

        # Build alert message
        alert_parts: list[str] = []

        # If analysis flagged something specific
        if analysis.get("alert_worthy") and analysis.get("alert_reason"):
            alert_parts.append(f"🚨 *MARKET ALERT*\n\n{analysis['alert_reason']}")

        # Add individual coin move alerts
        for move in moves[:3]:
            alert_text = format_alert_md(move)
            alert_parts.append(alert_text)

        if not alert_parts:
            return

        full_alert = "\n\n---\n\n".join(alert_parts)

        # Store alert in DB
        report_id = await self._db.insert_report(
            report_type="alert",
            markdown_body=full_alert,
            html_body=f"<pre>{full_alert}</pre>",
            meta={
                "generated_at": now.isoformat(),
                "moves": moves,
                "analysis_alert": analysis.get("alert_reason"),
            },
        )

        ok_tg = await self._telegram.send_alert(full_alert)
        if ok_tg:
            await self._db.mark_report_sent(report_id, "telegram")

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the APScheduler."""
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        """Gracefully stop the scheduler."""
        self._scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")

    def get_jobs(self) -> list[Any]:
        return self._scheduler.get_jobs()
