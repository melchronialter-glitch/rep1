"""
Base analyzer using the Anthropic SDK.

Key design decisions:
- Uses claude-sonnet-4-6 (per project spec)
- Applies prompt caching on the static system prompt portion
- Requests structured JSON output via output_config
- Returns structured analysis dicts; callers decide how to format
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# The model to use for all analysis
ANALYSIS_MODEL = "claude-sonnet-4-6"

# Maximum tokens for analysis responses
MAX_TOKENS = 4096


class BaseAnalyzer:
    """
    Base class for Claude-powered analyzers.

    Subclasses define:
      - SYSTEM_PROMPT : str  – the static system context (gets cached)
      - analyze()            – builds the user message and calls Claude
    """

    SYSTEM_PROMPT: str = "You are a helpful assistant."

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)

    def _call_claude(
        self,
        user_message: str,
        *,
        max_tokens: int = MAX_TOKENS,
        require_json: bool = True,
    ) -> dict[str, Any] | str:
        """
        Send a message to Claude with the class system prompt (cached) and
        return structured JSON if require_json=True, else raw text.

        Prompt caching is applied to the system prompt via cache_control.
        """
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": self.SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        try:
            if require_json:
                response = self._client.messages.create(
                    model=ANALYSIS_MODEL,
                    max_tokens=max_tokens,
                    system=system_blocks,  # type: ignore[arg-type]
                    messages=[{"role": "user", "content": user_message}],
                    output_config={
                        "format": {
                            "type": "json_object",
                        }
                    },
                )
            else:
                response = self._client.messages.create(
                    model=ANALYSIS_MODEL,
                    max_tokens=max_tokens,
                    system=system_blocks,  # type: ignore[arg-type]
                    messages=[{"role": "user", "content": user_message}],
                )

            # Log cache usage for monitoring
            usage = response.usage
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
            logger.debug(
                "Claude usage – input: %d, output: %d, cache_read: %d, cache_write: %d",
                usage.input_tokens,
                usage.output_tokens,
                cache_read,
                cache_write,
            )

            text_block = next(
                (b for b in response.content if b.type == "text"), None
            )
            if text_block is None:
                logger.error("Claude returned no text block")
                return {} if require_json else ""

            raw_text = text_block.text.strip()

            if require_json:
                try:
                    return json.loads(raw_text)
                except json.JSONDecodeError as exc:
                    logger.error("Claude returned invalid JSON: %s\nRaw: %s", exc, raw_text[:500])
                    # Attempt to extract JSON from markdown code block
                    if "```json" in raw_text:
                        try:
                            inner = raw_text.split("```json")[1].split("```")[0].strip()
                            return json.loads(inner)
                        except Exception:
                            pass
                    return {"raw_output": raw_text, "parse_error": str(exc)}

            return raw_text

        except anthropic.RateLimitError as exc:
            logger.warning("Anthropic rate limit hit: %s", exc)
            raise
        except anthropic.APIStatusError as exc:
            logger.error("Anthropic API error %s: %s", exc.status_code, exc.message)
            raise
        except Exception as exc:
            logger.error("Unexpected error calling Claude: %s", exc)
            raise

    async def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Override in subclasses. Accepts collected data, returns analysis dict.
        """
        raise NotImplementedError
