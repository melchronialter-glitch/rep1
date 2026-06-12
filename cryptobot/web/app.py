"""FastAPI web application for CryptoBot (Phase I).

Provides a minimal dark-theme dashboard with:
  GET /          — dashboard (last 20 alerts, last 10 risk scores, bus health)
  GET /alerts    — paginated alerts (JSON)
  GET /tokens    — recent tokens (JSON)
  GET /risk      — recent risk scores (JSON)
  GET /calls     — recent TG calls (JSON)
  GET /health    — {postgres: "ok", redis: "ok"} JSON
  Static files   — /static
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cryptobot.bus import get_bus
from cryptobot.db import fetch, fetchrow
from cryptobot.logging import get_logger

log = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def _row_to_dict(row: Any) -> dict:
    """Convert an asyncpg Record (or None) to a plain dict."""
    if row is None:
        return {}
    return dict(row)


def _rows_to_list(rows: list) -> list[dict]:
    return [_row_to_dict(r) for r in rows]


def create_app() -> FastAPI:
    """Factory — returns a configured FastAPI application."""

    app = FastAPI(
        title="CryptoBot Dashboard",
        description="Crypto market intelligence web UI",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ------------------------------------------------------------------
    # HTML routes
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        """Main dashboard page."""
        try:
            alerts = await fetch(
                "SELECT sent_at, channel, delivered, title FROM alerts "
                "ORDER BY sent_at DESC LIMIT 20"
            )
        except Exception:
            log.exception("web.dashboard.alerts_failed")
            alerts = []

        try:
            risk_scores = await fetch(
                "SELECT ts, chain, address, score, routed_to, liquidity_usd "
                "FROM risk_scores ORDER BY ts DESC LIMIT 10"
            )
        except Exception:
            log.exception("web.dashboard.risk_failed")
            risk_scores = []

        try:
            ev_count = await fetchrow(
                "SELECT COUNT(*) AS n FROM events WHERE ts > NOW() - INTERVAL '24 hours'"
            )
            alert_count = await fetchrow(
                "SELECT COUNT(*) AS n FROM alerts WHERE sent_at > NOW() - INTERVAL '24 hours'"
            )
            token_count = await fetchrow(
                "SELECT COUNT(*) AS n FROM tokens WHERE first_seen > NOW() - INTERVAL '24 hours'"
            )
            call_count = await fetchrow(
                "SELECT COUNT(*) AS n FROM tg_calls WHERE ts > NOW() - INTERVAL '24 hours'"
            )
        except Exception:
            log.exception("web.dashboard.stats_failed")
            ev_count = alert_count = token_count = call_count = None

        stats = {
            "events_24h": ev_count["n"] if ev_count else 0,
            "alerts_24h": alert_count["n"] if alert_count else 0,
            "tokens_24h": token_count["n"] if token_count else 0,
            "calls_24h": call_count["n"] if call_count else 0,
        }

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "alerts": _rows_to_list(alerts),
                "risk_scores": _rows_to_list(risk_scores),
                "stats": stats,
            },
        )

    @app.get("/risk-page", response_class=HTMLResponse)
    async def risk_page(request: Request) -> HTMLResponse:
        """Risk scores page."""
        try:
            rows = await fetch(
                "SELECT ts, chain, address, score, routed_to, liquidity_usd, reasons "
                "FROM risk_scores ORDER BY ts DESC LIMIT 50"
            )
        except Exception:
            log.exception("web.risk_page.failed")
            rows = []

        return templates.TemplateResponse(
            "risk.html",
            {"request": request, "risk_scores": _rows_to_list(rows)},
        )

    # ------------------------------------------------------------------
    # JSON API routes
    # ------------------------------------------------------------------

    @app.get("/alerts")
    async def get_alerts(
        limit: int = Query(default=20, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> JSONResponse:
        """Paginated alerts."""
        try:
            rows = await fetch(
                "SELECT sent_at, channel, delivered, title FROM alerts "
                "ORDER BY sent_at DESC LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
        except Exception as exc:
            log.exception("web.alerts.failed")
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse([_row_to_dict(r) for r in rows], default=str)

    @app.get("/tokens")
    async def get_tokens(
        chain: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=200),
    ) -> JSONResponse:
        """Recent tokens."""
        try:
            if chain:
                rows = await fetch(
                    "SELECT first_seen, chain, venue, symbol, name, address "
                    "FROM tokens WHERE chain = $1 ORDER BY first_seen DESC LIMIT $2",
                    chain,
                    limit,
                )
            else:
                rows = await fetch(
                    "SELECT first_seen, chain, venue, symbol, name, address "
                    "FROM tokens ORDER BY first_seen DESC LIMIT $1",
                    limit,
                )
        except Exception as exc:
            log.exception("web.tokens.failed")
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse([_row_to_dict(r) for r in rows], default=str)

    @app.get("/risk")
    async def get_risk(
        chain: str | None = Query(default=None),
        min_score: int = Query(default=0, ge=0, le=100),
        limit: int = Query(default=20, ge=1, le=200),
    ) -> JSONResponse:
        """Recent risk scores."""
        try:
            if chain:
                rows = await fetch(
                    "SELECT ts, chain, address, score, routed_to, liquidity_usd, reasons "
                    "FROM risk_scores WHERE chain = $1 AND score >= $2 "
                    "ORDER BY ts DESC LIMIT $3",
                    chain,
                    min_score,
                    limit,
                )
            else:
                rows = await fetch(
                    "SELECT ts, chain, address, score, routed_to, liquidity_usd, reasons "
                    "FROM risk_scores WHERE score >= $1 ORDER BY ts DESC LIMIT $2",
                    min_score,
                    limit,
                )
        except Exception as exc:
            log.exception("web.risk.failed")
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse([_row_to_dict(r) for r in rows], default=str)

    @app.get("/calls")
    async def get_calls(
        limit: int = Query(default=20, ge=1, le=200),
        address: str | None = Query(default=None),
    ) -> JSONResponse:
        """Recent TG calls."""
        try:
            if address:
                rows = await fetch(
                    "SELECT ts, chain_guess, address, tickers, chat_title, sender_name, buy_language "
                    "FROM tg_calls WHERE address = $1 ORDER BY ts DESC LIMIT $2",
                    address,
                    limit,
                )
            else:
                rows = await fetch(
                    "SELECT ts, chain_guess, address, tickers, chat_title, sender_name, buy_language "
                    "FROM tg_calls ORDER BY ts DESC LIMIT $1",
                    limit,
                )
        except Exception as exc:
            log.exception("web.calls.failed")
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse([_row_to_dict(r) for r in rows], default=str)

    @app.get("/health")
    async def health() -> JSONResponse:
        """Liveness check for Postgres and Redis."""
        result: dict[str, str] = {}

        try:
            row = await fetchrow("SELECT 1 AS ok")
            result["postgres"] = "ok" if row and row["ok"] == 1 else "fail"
        except Exception as exc:
            result["postgres"] = f"fail: {exc}"

        try:
            bus = get_bus()
            result["redis"] = "ok" if await bus.ping() else "fail"
        except Exception as exc:
            result["redis"] = f"fail: {exc}"

        status_code = 200 if all(v == "ok" for v in result.values()) else 503
        return JSONResponse(result, status_code=status_code)

    return app
