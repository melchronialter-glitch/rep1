"""Discord listener — STUB.

Discord's Terms of Service prohibit automated user-account ("selfbot")
access.  The only compliant path is a verified bot with the ``MESSAGE_CONTENT``
privileged intent, which requires submitting the bot to Discord for review once
it is in 100+ servers.

Until we have a verified bot application the listener is intentionally a no-op.
The runner is wired into main.py so the slot is reserved; it just exits cleanly
with a log line.

Phase F / G will revisit this once a Discord application is registered.
"""

from __future__ import annotations

import asyncio

from cryptobot.logging import get_logger

log = get_logger(__name__)


async def run_discord_listener(stop_event: asyncio.Event | None = None) -> None:
    log.info(
        "discord_listener.disabled",
        reason=(
            "Discord selfbots violate ToS. Register a verified Discord bot application "
            "with the MESSAGE_CONTENT privileged intent, then implement here."
        ),
    )
