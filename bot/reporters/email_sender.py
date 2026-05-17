"""
Email report sender using smtplib (SMTP with STARTTLS).

Handles:
- HTML and plain-text multipart emails
- SMTP STARTTLS connection
- Retry on connection errors
- Graceful failure without crashing the scheduler
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class EmailSender:
    """SMTP email sender with async support (runs sync SMTP in executor)."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_pass: str,
        from_addr: str,
        to_addr: str,
    ) -> None:
        self._host = smtp_host
        self._port = smtp_port
        self._user = smtp_user
        self._pass = smtp_pass
        self._from = from_addr
        self._to = to_addr

    def _build_email(
        self,
        subject: str,
        html_body: str,
        plain_body: str,
    ) -> MIMEMultipart:
        """Construct a multipart/alternative MIME message."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = self._to
        msg["X-Mailer"] = "CryptoBot/1.0"

        # Plain text first (fallback for non-HTML clients)
        part_plain = MIMEText(plain_body, "plain", "utf-8")
        part_html = MIMEText(html_body, "html", "utf-8")

        msg.attach(part_plain)
        msg.attach(part_html)
        return msg

    def _send_sync(self, msg: MIMEMultipart) -> None:
        """
        Synchronous SMTP send with STARTTLS.
        Runs in an executor thread.
        """
        context = ssl.create_default_context()

        try:
            with smtplib.SMTP(self._host, self._port, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(self._user, self._pass)
                server.sendmail(
                    self._from,
                    [addr.strip() for addr in self._to.split(",")],
                    msg.as_string(),
                )
            logger.info("Email sent to %s via %s:%d", self._to, self._host, self._port)
        except smtplib.SMTPAuthenticationError as exc:
            logger.error("SMTP authentication failed: %s", exc)
            raise
        except smtplib.SMTPException as exc:
            logger.error("SMTP error: %s", exc)
            raise
        except OSError as exc:
            logger.error("SMTP connection error (host=%s port=%d): %s",
                         self._host, self._port, exc)
            raise

    async def send(
        self,
        subject: str,
        html_body: str,
        plain_body: str | None = None,
    ) -> bool:
        """
        Async email send. Returns True on success.

        If plain_body is None, a basic strip of the HTML is used.
        """
        if plain_body is None:
            # Very basic HTML → plain text stripping
            import re
            plain_body = re.sub(r"<[^>]+>", "", html_body)
            plain_body = re.sub(r"\n{3,}", "\n\n", plain_body).strip()

        msg = self._build_email(subject, html_body, plain_body)

        loop = asyncio.get_event_loop()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await loop.run_in_executor(None, self._send_sync, msg)
                return True
            except smtplib.SMTPAuthenticationError:
                # Auth errors are not retryable
                return False
            except Exception as exc:
                wait = 2 ** attempt
                if attempt < max_retries - 1:
                    logger.warning(
                        "Email send attempt %d/%d failed; retrying in %ds: %s",
                        attempt + 1, max_retries, wait, exc,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("Email send failed after %d attempts: %s", max_retries, exc)

        return False

    async def send_market_report(
        self,
        html_body: str,
        generated_at: datetime | None = None,
    ) -> bool:
        """Send a market analysis report."""
        ts = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
        subject = f"🟢 Crypto Market Analysis | {ts}"
        return await self.send(subject=subject, html_body=html_body)

    async def send_macro_report(
        self,
        html_body: str,
        generated_at: datetime | None = None,
    ) -> bool:
        """Send a macro analysis report."""
        ts = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
        subject = f"🌍 Crypto Macro Analysis | {ts}"
        return await self.send(subject=subject, html_body=html_body)

    async def send_daily_digest(
        self,
        html_body: str,
        generated_at: datetime | None = None,
    ) -> bool:
        """Send the daily digest."""
        date_str = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d")
        subject = f"📊 Daily Crypto Digest | {date_str}"
        return await self.send(subject=subject, html_body=html_body)

    async def send_alert(
        self,
        html_body: str,
        alert_summary: str = "",
    ) -> bool:
        """Send a price alert email."""
        subject = f"🚨 Crypto Price Alert | {alert_summary}"
        return await self.send(subject=subject, html_body=html_body)

    async def ping(self) -> bool:
        """Test SMTP connectivity."""
        loop = asyncio.get_event_loop()
        try:
            def _test() -> None:
                context = ssl.create_default_context()
                with smtplib.SMTP(self._host, self._port, timeout=10) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(self._user, self._pass)

            await loop.run_in_executor(None, _test)
            logger.info("SMTP connection test OK: %s:%d", self._host, self._port)
            return True
        except Exception as exc:
            logger.error("SMTP ping failed: %s", exc)
            return False
