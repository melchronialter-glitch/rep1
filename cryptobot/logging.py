"""Structured logging setup."""

from __future__ import annotations

import logging
import sys

import structlog

from cryptobot.config import get_settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")
    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    setup_logging()
    return structlog.get_logger(name) if name else structlog.get_logger()
