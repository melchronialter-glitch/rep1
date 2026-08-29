"""Outbound email reporter (stdlib smtplib, run in an executor).

Used by the digest agent for daily summaries. Sends multipart messages with a
plain-text part and a simple HTML part rendered from the markdown body — no
extra dependencies, just paragraph and bold/italic conversion. Retries up to
three times with backoff. Skips silently if SMTP isn't configured.
"""

from __future__ import annotations

import asyncio
import html
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from cryptobot.config import get_settings
from cryptobot.logging import get_logger

log = get_logger(__name__)

RETRIES = 3


def markdown_to_html(md: str) -> str:
    """Very small markdown→HTML converter: paragraphs, bold, italic, bullets.

    Good enough for digest emails; intentionally not a full parser.
    """
    out_blocks: list[str] = []
    for block in md.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        escaped = html.escape(block)
        # **bold** then *bold* (Telegram-style), then _italic_
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        escaped = re.sub(r"\*(.+?)\*", r"<b>\1</b>", escaped)
        escaped = re.sub(r"_(.+?)_", r"<i>\1</i>", escaped)
        lines = escaped.split("\n")
        if all(line.lstrip().startswith(("- ", "• ")) for line in lines):
            items = "".join(f"<li>{line.lstrip()[2:].strip()}</li>" for line in lines)
            out_blocks.append(f"<ul>{items}</ul>")
        elif block.startswith("#"):
            text = escaped.lstrip("#").strip()
            out_blocks.append(f"<h3>{text}</h3>")
        else:
            out_blocks.append(f"<p>{escaped.replace(chr(10), '<br>')}</p>")
    return (
        "<html><body style=\"font-family:sans-serif;max-width:720px\">"
        + "\n".join(out_blocks)
        + "</body></html>"
    )


def _send_sync(subject: str, body_md: str) -> None:
    """Blocking SMTP send — always called via run_in_executor."""
    settings = get_settings()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = settings.email_to
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(markdown_to_html(body_md), "html", "utf-8"))

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        try:
            smtp.starttls()
            smtp.ehlo()
        except smtplib.SMTPNotSupportedError:
            log.debug("email.starttls_unavailable")
        if settings.email_smtp_user:
            smtp.login(settings.email_smtp_user, settings.email_smtp_pass)
        smtp.sendmail(
            settings.email_from,
            [a.strip() for a in settings.email_to.split(",") if a.strip()],
            msg.as_string(),
        )


async def send_email(subject: str, body_md: str) -> bool:
    """Send an email with up to three retries. Returns delivery success."""
    settings = get_settings()
    if not settings.email_configured:
        log.debug("email.skipped", reason="smtp not configured")
        return False

    loop = asyncio.get_running_loop()
    for attempt in range(RETRIES):
        try:
            await loop.run_in_executor(None, _send_sync, subject, body_md)
            log.info("email.sent", subject=subject, to=settings.email_to)
            return True
        except Exception as e:
            log.warning("email.send_failed", attempt=attempt, err=str(e))
            await asyncio.sleep(2**attempt)
    log.error("email.gave_up", subject=subject)
    return False
