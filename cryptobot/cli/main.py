"""cryptobot CLI."""

from __future__ import annotations

import asyncio
import json

import typer

from cryptobot.bus import close_bus, get_bus
from cryptobot.config import get_settings
from cryptobot.db import close_pool, fetch, fetchrow, run_migrations
from cryptobot.logging import get_logger
from cryptobot.reporters.telegram_out import TelegramOut

app = typer.Typer(no_args_is_help=True, help="CryptoBot operations CLI")
log = get_logger("cli")


@app.command()
def migrate() -> None:
    """Apply pending database migrations."""

    async def _run():
        await run_migrations()
        await close_pool()

    asyncio.run(_run())
    typer.echo("migrations: ok")


@app.command()
def health() -> None:
    """Ping Postgres, Redis, and the Telegram bot."""

    async def _run():
        settings = get_settings()
        results: dict[str, str] = {}
        # Postgres
        try:
            row = await fetchrow("SELECT 1 AS ok")
            results["postgres"] = "ok" if row and row["ok"] == 1 else "fail"
        except Exception as e:
            results["postgres"] = f"fail: {e}"
        # Redis
        try:
            bus = get_bus()
            results["redis"] = "ok" if await bus.ping() else "fail"
        except Exception as e:
            results["redis"] = f"fail: {e}"
        # Telegram
        if settings.telegram_bot_token:
            try:
                tg = TelegramOut()
                r = await tg._client.get("/getMe")
                results["telegram"] = (
                    f"ok ({r.json()['result']['username']})"
                    if r.status_code == 200
                    else f"fail: {r.status_code}"
                )
                await tg.close()
            except Exception as e:
                results["telegram"] = f"fail: {e}"
        else:
            results["telegram"] = "not configured"
        await close_bus()
        await close_pool()
        typer.echo(json.dumps(results, indent=2))

    asyncio.run(_run())


@app.command()
def publish(
    topic: str = typer.Argument(..., help="Topic name, e.g. demo.ping"),
    payload: str = typer.Option("{}", help="JSON payload"),
    source: str = typer.Option("cli", help="Source identifier"),
) -> None:
    """Publish an event to the bus."""

    async def _run():
        data = json.loads(payload)
        bus = get_bus()
        event = await bus.publish(topic, data, source=source)
        typer.echo(f"published {event.id} → {topic}")
        await close_bus()
        await close_pool()

    asyncio.run(_run())


@app.command()
def demo(
    channel: str = typer.Option("firehose", help="strict|medium|firehose|macro|dm"),
) -> None:
    """End-to-end Phase A demo: publish a fake event and let triage route it to Telegram."""

    async def _run():
        bus = get_bus()
        severity = "high" if channel == "strict" else "low"
        topic = "demo.ping"
        payload = {
            "title": "CryptoBot Phase A spine test",
            "summary": (
                "If you're reading this on Telegram, the bus + triage + outbound "
                "reporter are working end-to-end."
            ),
            "severity": severity,
        }
        event = await bus.publish(topic, payload, source="cli.demo")
        typer.echo(f"published demo event {event.id}")
        typer.echo("triage + telegram_out must be running: `python -m cryptobot.main`")
        await close_bus()
        await close_pool()

    asyncio.run(_run())


@app.command()
def events(
    topic: str | None = typer.Option(None, help="Filter by topic prefix"),
    limit: int = typer.Option(20),
) -> None:
    """Show recent events from the archive."""

    async def _run():
        if topic:
            rows = await fetch(
                "SELECT ts, topic, source, id FROM events "
                "WHERE topic LIKE $1 ORDER BY ts DESC LIMIT $2",
                f"{topic}%",
                limit,
            )
        else:
            rows = await fetch(
                "SELECT ts, topic, source, id FROM events ORDER BY ts DESC LIMIT $1",
                limit,
            )
        for r in rows:
            typer.echo(f"{r['ts'].isoformat()}  {r['topic']:<30}  {r['source']:<20}  {r['id']}")
        await close_pool()

    asyncio.run(_run())


@app.command()
def alerts(limit: int = typer.Option(20)) -> None:
    """Show recent alerts sent."""

    async def _run():
        rows = await fetch(
            "SELECT sent_at, channel, delivered, title FROM alerts "
            "ORDER BY sent_at DESC LIMIT $1",
            limit,
        )
        for r in rows:
            mark = "✓" if r["delivered"] else "✗"
            typer.echo(f"{r['sent_at'].isoformat()}  {mark}  {r['channel']:<10}  {r['title']}")
        await close_pool()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
