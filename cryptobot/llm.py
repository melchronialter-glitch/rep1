"""Anthropic / Claude wrapper with prompt caching baked in.

Every analysis call goes through here so we get consistent retries, caching,
and usage logging in one place.
"""

from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from cryptobot.config import get_settings
from cryptobot.logging import get_logger

log = get_logger(__name__)

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def analyze(
    *,
    system: str,
    user: str,
    model: str | None = None,
    fast: bool = False,
    max_tokens: int = 2048,
    temperature: float = 0.4,
    cache_system: bool = True,
    json_response: bool = False,
) -> dict[str, Any]:
    """Send a single analysis call.

    Returns ``{"text": str, "json": dict | None, "usage": {...}, "stop_reason": str}``.
    The static ``system`` prompt is cached with ``cache_control: ephemeral`` so
    repeated calls with the same system prompt only pay for input once per
    5-minute window.
    """
    settings = get_settings()
    client = get_client()
    chosen_model = model or (settings.anthropic_fast_model if fast else settings.anthropic_model)

    system_blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": system,
            **({"cache_control": {"type": "ephemeral"}} if cache_system else {}),
        }
    ]

    user_text = user
    if json_response:
        user_text = (
            user
            + "\n\nRespond ONLY with a single JSON object. No prose, no code fences."
        )

    messages: list[MessageParam] = [{"role": "user", "content": user_text}]

    resp = await client.messages.create(
        model=chosen_model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_blocks,
        messages=messages,
    )

    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = "".join(text_parts).strip()

    parsed_json: dict[str, Any] | None = None
    if json_response and text:
        try:
            parsed_json = json.loads(text)
        except json.JSONDecodeError:
            # Heuristic: pull the first {...} block out
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                try:
                    parsed_json = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    log.warning("llm.json.parse_failed", text_preview=text[:200])

    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_input_tokens": getattr(
            resp.usage, "cache_creation_input_tokens", 0
        ),
        "cache_read_input_tokens": getattr(
            resp.usage, "cache_read_input_tokens", 0
        ),
    }
    log.info(
        "llm.call",
        model=chosen_model,
        stop_reason=resp.stop_reason,
        **usage,
    )

    return {
        "text": text,
        "json": parsed_json,
        "usage": usage,
        "stop_reason": resp.stop_reason,
    }
