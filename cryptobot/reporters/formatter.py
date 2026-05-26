"""Format event payloads into human-readable Telegram messages.

Phase A: a simple generic renderer for any alert payload. Later phases will
register topic-specific renderers via @register_formatter.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cryptobot.bus import Event

# Telegram MarkdownV2 reserved characters
_MD2_ESCAPE = r"_*[]()~`>#+-=|{}.!\\"


def md2_escape(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    return "".join("\\" + c if c in _MD2_ESCAPE else c for c in text)


_RENDERERS: dict[str, Callable[[Event], dict[str, str]]] = {}


def register_formatter(topic_prefix: str):
    def decorator(fn: Callable[[Event], dict[str, str]]):
        _RENDERERS[topic_prefix] = fn
        return fn

    return decorator


def render_alert(event: Event) -> dict[str, str]:
    """Return {"title": str, "body": str} ready for Telegram."""
    # Topic-specific renderer wins; longest matching prefix.
    for prefix in sorted(_RENDERERS.keys(), key=len, reverse=True):
        if event.topic.startswith(prefix):
            return _RENDERERS[prefix](event)
    return _generic_render(event)


def _generic_render(event: Event) -> dict[str, str]:
    p: dict[str, Any] = event.payload or {}
    title = p.get("title") or p.get("headline") or event.topic
    body_lines: list[str] = []
    if "summary" in p:
        body_lines.append(str(p["summary"]))
    if "url" in p:
        body_lines.append(f"\n{p['url']}")
    body = "\n".join(body_lines) if body_lines else _kv_dump(p)
    return {"title": str(title), "body": body}


def _kv_dump(payload: dict[str, Any], limit: int = 12) -> str:
    items = list(payload.items())[:limit]
    return "\n".join(f"• {k}: {v}" for k, v in items)


def to_markdown_v2(title: str, body: str) -> str:
    """Compose a Telegram MarkdownV2 message."""
    return f"*{md2_escape(title)}*\n\n{md2_escape(body)}"
