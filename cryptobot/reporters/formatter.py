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
    # Phase C: alerts carry the original payload through, so renderers key on
    # payload shape — token_address + chain means a new-pair card.
    if p.get("chain") and (p.get("token_address") or p.get("pair_address")):
        return _new_pair_render(p)
    title = p.get("title") or p.get("headline") or event.topic
    body_lines: list[str] = []
    if "summary" in p:
        body_lines.append(str(p["summary"]))
    if "url" in p:
        body_lines.append(f"\n{p['url']}")
    body = "\n".join(body_lines) if body_lines else _kv_dump(p)
    return {"title": str(title), "body": body}


def _new_pair_render(p: dict[str, Any]) -> dict[str, str]:
    """Render a chain.new_pair payload as a compact new-pair card."""
    chain = p.get("chain", "?")
    what = p.get("symbol") or p.get("token0") or p.get("token_address") or "?"
    title = f"New pair [{chain}] {what}"
    if p.get("token1"):
        title += f"/{p['token1']}"
    risk_score = p.get("risk_score")
    if risk_score is not None and int(risk_score) >= 70:
        title = f"⚠️ HIGH RISK {title}"

    body_lines: list[str] = []
    if p.get("venue"):
        body_lines.append(f"venue: {p['venue']}")
    if p.get("name"):
        body_lines.append(f"name: {p['name']}")
    if p.get("token_address"):
        body_lines.append(f"token: {p['token_address']}")
    if p.get("token0"):
        body_lines.append(f"token0: {p['token0']}")
    if p.get("token1"):
        body_lines.append(f"token1: {p['token1']}")
    if p.get("pair_address"):
        body_lines.append(f"pair: {p['pair_address']}")
    if risk_score is not None:
        reasons = [str(r) for r in (p.get("risk_reasons") or [])[:3]]
        line = f"risk: {int(risk_score)}/100"
        if reasons:
            line += f" ({', '.join(reasons)})"
        body_lines.append(line)
    if p.get("liquidity_usd") is not None:
        body_lines.append(f"liquidity: ${float(p['liquidity_usd']):,.0f}")
    if p.get("fdv") is not None:
        body_lines.append(f"fdv: ${float(p['fdv']):,.0f}")
    if p.get("price_usd") is not None:
        body_lines.append(f"price: ${p['price_usd']}")
    if p.get("warning"):
        body_lines.append(f"warning: {p['warning']}")
    if p.get("dexscreener_url"):
        body_lines.append(f"\n{p['dexscreener_url']}")
    return {"title": title, "body": "\n".join(body_lines) or _kv_dump(p)}


def _kv_dump(payload: dict[str, Any], limit: int = 12) -> str:
    items = list(payload.items())[:limit]
    return "\n".join(f"• {k}: {v}" for k, v in items)


def to_markdown_v2(title: str, body: str) -> str:
    """Compose a Telegram MarkdownV2 message."""
    return f"*{md2_escape(title)}*\n\n{md2_escape(body)}"
