"""
Report formatter: converts analysis JSON into Telegram Markdown and HTML email.

Handles:
- Market analysis reports
- Macro analysis reports
- Daily digest (combines market + macro)
- Price alerts
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any


# ─── Emoji helpers ────────────────────────────────────────────────────────────

def _sentiment_emoji(sentiment: str) -> str:
    return {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪", "mixed": "🟡"}.get(
        sentiment.lower(), "⚪"
    )


def _risk_emoji(risk: str) -> str:
    return {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🚨"}.get(
        risk.lower(), "⚪"
    )


def _pct_emoji(pct: float) -> str:
    if pct >= 5:
        return "🚀"
    if pct >= 2:
        return "📈"
    if pct >= 0:
        return "▲"
    if pct >= -2:
        return "▼"
    if pct >= -5:
        return "📉"
    return "🔻"


# ─── Markdown (Telegram) ──────────────────────────────────────────────────────

def format_market_report_md(analysis: dict[str, Any], generated_at: datetime | None = None) -> str:
    """Format market analysis as Telegram-compatible MarkdownV2."""
    ts = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    sentiment = analysis.get("sentiment", {})
    overall = sentiment.get("overall", "neutral")
    confidence = sentiment.get("confidence", 0)
    s_emoji = _sentiment_emoji(overall)

    lines: list[str] = []

    lines.append(f"📊 *MARKET ANALYSIS* | {ts}")
    lines.append("")

    # Market summary
    summary = analysis.get("market_summary", "No summary available.")
    lines.append("*Market Overview*")
    lines.append(summary)
    lines.append("")

    # BTC / ETH
    if btc := analysis.get("btc_outlook"):
        lines.append("*₿ Bitcoin*")
        lines.append(btc)
        lines.append("")

    if eth := analysis.get("eth_outlook"):
        lines.append("*Ξ Ethereum*")
        lines.append(eth)
        lines.append("")

    # Top movers
    movers = analysis.get("top_movers", [])
    if movers:
        lines.append("*🏃 Top Movers*")
        for m in movers[:5]:
            coin = m.get("coin", "?")
            pct = m.get("change_pct", 0)
            commentary = m.get("commentary", "")
            emoji = _pct_emoji(pct)
            lines.append(f"  {emoji} *{coin}*: {pct:+.1f}% – {commentary}")
        lines.append("")

    # Sentiment
    lines.append(f"*{s_emoji} Sentiment*: {overall.upper()} ({confidence}% confidence)")
    if reasoning := sentiment.get("reasoning"):
        lines.append(f"_{reasoning}_")
    lines.append("")

    # Key themes
    themes = analysis.get("key_themes", [])
    if themes:
        lines.append("*🎯 Key Themes*")
        for t in themes:
            lines.append(f"  • {t}")
        lines.append("")

    # Risks
    risks = analysis.get("risk_factors", [])
    if risks:
        lines.append("*⚠️ Risk Factors*")
        for r in risks:
            lines.append(f"  • {r}")
        lines.append("")

    # Watch list
    watch = analysis.get("watch_list", [])
    if watch:
        lines.append("*👁 Watch List*")
        lines.append("  " + " | ".join(watch))

    return "\n".join(lines)


def format_macro_report_md(analysis: dict[str, Any], generated_at: datetime | None = None) -> str:
    """Format macro analysis as Telegram-compatible Markdown."""
    ts = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    risk = analysis.get("risk_level", "medium")
    r_emoji = _risk_emoji(risk)
    impact = analysis.get("crypto_impact", {})
    direction = impact.get("direction", "neutral")
    d_emoji = _sentiment_emoji(direction)

    lines: list[str] = []
    lines.append(f"🌍 *MACRO ANALYSIS* | {ts}")
    lines.append("")

    # Overview
    lines.append("*Macro Overview*")
    lines.append(analysis.get("macro_summary", "No summary available."))
    lines.append("")

    # Fed + Inflation
    fed = analysis.get("fed_stance", "uncertain")
    lines.append(f"*🏦 Fed Stance*: {fed.upper()}")
    if infl := analysis.get("inflation_outlook"):
        lines.append(f"*📈 Inflation*: {infl}")
    lines.append("")

    # Crypto impact
    lines.append("*Crypto Market Impact*")
    lines.append(f"  Direction: {d_emoji} {direction.upper()}")
    lines.append(f"  Magnitude: {impact.get('magnitude', 'medium').upper()}")
    if exp := impact.get("explanation"):
        lines.append(f"  _{exp}_")
    lines.append("")

    # Reddit sentiment
    reddit_sent = analysis.get("sentiment", {})
    reddit_overall = reddit_sent.get("reddit_overall", "mixed")
    lines.append(f"*💬 Reddit Pulse*: {_sentiment_emoji(reddit_overall)} {reddit_overall.upper()}")
    narratives = reddit_sent.get("notable_narratives", [])
    for n in narratives[:3]:
        lines.append(f"  • {n}")
    lines.append("")

    # Narrative shifts
    shifts = analysis.get("narrative_shifts", [])
    if shifts:
        lines.append("*🔄 Narrative Shifts*")
        for s in shifts[:3]:
            lines.append(f"  • {s}")
        lines.append("")

    # Risk level
    lines.append(f"*{r_emoji} Risk Level*: {risk.upper()}")

    # Upcoming events
    events = analysis.get("key_events_ahead", [])
    if events:
        lines.append("")
        lines.append("*📅 Events to Watch*")
        for e in events[:4]:
            lines.append(f"  • {e}")

    return "\n".join(lines)


def format_daily_digest_md(
    market_analysis: dict[str, Any],
    macro_analysis: dict[str, Any],
    generated_at: datetime | None = None,
) -> str:
    """Combine market and macro analyses into a daily digest (Markdown)."""
    ts = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []

    lines.append(f"🌅 *DAILY CRYPTO DIGEST* | {ts}")
    lines.append("=" * 35)
    lines.append("")

    # Section 1: Market
    lines.append("━━━ 📊 MARKET SNAPSHOT ━━━")
    lines.append("")
    market_section = format_market_report_md(market_analysis, generated_at)
    # Strip the header since we already have one
    market_lines = market_section.split("\n")[1:]
    lines.extend(market_lines)
    lines.append("")

    # Section 2: Macro
    lines.append("━━━ 🌍 MACRO ENVIRONMENT ━━━")
    lines.append("")
    macro_section = format_macro_report_md(macro_analysis, generated_at)
    macro_lines = macro_section.split("\n")[1:]
    lines.extend(macro_lines)

    lines.append("")
    lines.append("─" * 35)
    lines.append("_Powered by Claude AI | CryptoBot_")

    return "\n".join(lines)


def format_alert_md(alert: dict[str, Any]) -> str:
    """Format a price alert for Telegram."""
    coin = alert.get("coin_id", "?").upper()
    symbol = alert.get("symbol", "?").upper()
    price = alert.get("price_usd", 0)
    change_pct = alert.get("change_pct", 0)
    window = alert.get("window", "1h")
    reason = alert.get("reason", "")

    emoji = "🚀" if change_pct > 0 else "🔻"
    direction = "SURGE" if change_pct > 0 else "DUMP"

    lines = [
        f"{emoji} *PRICE ALERT: {symbol} {direction}*",
        "",
        f"*{coin}* moved *{change_pct:+.2f}%* in the last *{window}*",
        f"Current price: *${price:,.2f}*",
    ]
    if reason:
        lines.append(f"\n_{reason}_")

    return "\n".join(lines)


# ─── HTML (Email) ─────────────────────────────────────────────────────────────

_HTML_STYLE = """
<style>
  body { font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #333; }
  .header { background: #1a1a2e; color: #fff; padding: 20px; border-radius: 8px 8px 0 0; }
  .header h1 { margin: 0; font-size: 24px; }
  .header .ts { font-size: 13px; opacity: 0.7; margin-top: 4px; }
  .section { padding: 16px 20px; border-bottom: 1px solid #eee; }
  .section h2 { font-size: 16px; color: #1a1a2e; margin: 0 0 8px 0; }
  .section p { margin: 6px 0; font-size: 14px; line-height: 1.5; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; }
  .bullish { background: #d4edda; color: #155724; }
  .bearish { background: #f8d7da; color: #721c24; }
  .neutral { background: #e2e3e5; color: #383d41; }
  .mover-row { display: flex; gap: 8px; align-items: baseline; margin: 4px 0; }
  ul { margin: 6px 0; padding-left: 20px; font-size: 14px; }
  li { margin: 3px 0; }
  .footer { background: #f8f9fa; padding: 12px 20px; font-size: 12px; color: #666;
            border-radius: 0 0 8px 8px; text-align: center; }
</style>
"""


def _h(text: Any) -> str:
    """HTML-escape a value."""
    return html.escape(str(text))


def _sentiment_badge(sentiment: str) -> str:
    cls = sentiment.lower() if sentiment.lower() in ("bullish", "bearish", "neutral") else "neutral"
    return f'<span class="tag {cls}">{_h(sentiment.upper())}</span>'


def format_market_report_html(analysis: dict[str, Any], generated_at: datetime | None = None) -> str:
    """Format market analysis as HTML email."""
    ts = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    sentiment = analysis.get("sentiment", {})
    overall = sentiment.get("overall", "neutral")
    confidence = sentiment.get("confidence", 0)

    parts: list[str] = [f"<html><head>{_HTML_STYLE}</head><body>"]

    parts.append(
        f'<div class="header">'
        f'<h1>📊 Market Analysis</h1>'
        f'<div class="ts">{_h(ts)}</div>'
        f'</div>'
    )

    # Summary
    parts.append(
        f'<div class="section">'
        f'<h2>Market Overview</h2>'
        f'<p>{_h(analysis.get("market_summary", ""))}</p>'
        f'</div>'
    )

    # BTC / ETH
    if btc := analysis.get("btc_outlook"):
        parts.append(f'<div class="section"><h2>₿ Bitcoin</h2><p>{_h(btc)}</p></div>')
    if eth := analysis.get("eth_outlook"):
        parts.append(f'<div class="section"><h2>Ξ Ethereum</h2><p>{_h(eth)}</p></div>')

    # Top movers
    movers = analysis.get("top_movers", [])
    if movers:
        rows = "".join(
            f'<li><strong>{_h(m.get("coin","?"))}</strong>: '
            f'{m.get("change_pct", 0):+.1f}% – {_h(m.get("commentary",""))}</li>'
            for m in movers[:5]
        )
        parts.append(f'<div class="section"><h2>🏃 Top Movers</h2><ul>{rows}</ul></div>')

    # Sentiment
    badge = _sentiment_badge(overall)
    parts.append(
        f'<div class="section">'
        f'<h2>Sentiment</h2>'
        f'<p>{badge} {confidence}% confidence</p>'
        f'<p><em>{_h(sentiment.get("reasoning", ""))}</em></p>'
        f'</div>'
    )

    # Themes + risks
    themes = analysis.get("key_themes", [])
    if themes:
        items = "".join(f"<li>{_h(t)}</li>" for t in themes)
        parts.append(f'<div class="section"><h2>🎯 Key Themes</h2><ul>{items}</ul></div>')

    risks = analysis.get("risk_factors", [])
    if risks:
        items = "".join(f"<li>{_h(r)}</li>" for r in risks)
        parts.append(f'<div class="section"><h2>⚠️ Risk Factors</h2><ul>{items}</ul></div>')

    parts.append('<div class="footer">Powered by Claude AI | CryptoBot</div>')
    parts.append("</body></html>")
    return "".join(parts)


def format_macro_report_html(analysis: dict[str, Any], generated_at: datetime | None = None) -> str:
    """Format macro analysis as HTML email."""
    ts = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    impact = analysis.get("crypto_impact", {})
    direction = impact.get("direction", "neutral")

    parts: list[str] = [f"<html><head>{_HTML_STYLE}</head><body>"]

    parts.append(
        f'<div class="header">'
        f'<h1>🌍 Macro Analysis</h1>'
        f'<div class="ts">{_h(ts)}</div>'
        f'</div>'
    )

    parts.append(
        f'<div class="section">'
        f'<h2>Macro Overview</h2>'
        f'<p>{_h(analysis.get("macro_summary", ""))}</p>'
        f'</div>'
    )

    # Fed + Inflation
    fed = analysis.get("fed_stance", "uncertain")
    infl = analysis.get("inflation_outlook", "")
    parts.append(
        f'<div class="section">'
        f'<h2>🏦 Fed &amp; Inflation</h2>'
        f'<p><strong>Fed Stance:</strong> {_h(fed.upper())}</p>'
        f'<p><strong>Inflation:</strong> {_h(infl)}</p>'
        f'</div>'
    )

    # Crypto impact
    badge = _sentiment_badge(direction)
    parts.append(
        f'<div class="section">'
        f'<h2>Crypto Market Impact</h2>'
        f'<p>Direction: {badge} | Magnitude: <strong>{_h(impact.get("magnitude","").upper())}</strong></p>'
        f'<p>{_h(impact.get("explanation",""))}</p>'
        f'</div>'
    )

    # Narrative shifts
    shifts = analysis.get("narrative_shifts", [])
    if shifts:
        items = "".join(f"<li>{_h(s)}</li>" for s in shifts[:4])
        parts.append(f'<div class="section"><h2>🔄 Narrative Shifts</h2><ul>{items}</ul></div>')

    # Upcoming events
    events = analysis.get("key_events_ahead", [])
    if events:
        items = "".join(f"<li>{_h(e)}</li>" for e in events[:5])
        parts.append(f'<div class="section"><h2>📅 Upcoming Events</h2><ul>{items}</ul></div>')

    risk = analysis.get("risk_level", "medium")
    parts.append(
        f'<div class="section">'
        f'<p>Risk Level: {_sentiment_badge(risk)}</p>'
        f'</div>'
    )

    parts.append('<div class="footer">Powered by Claude AI | CryptoBot</div>')
    parts.append("</body></html>")
    return "".join(parts)


def format_daily_digest_html(
    market_analysis: dict[str, Any],
    macro_analysis: dict[str, Any],
    generated_at: datetime | None = None,
) -> str:
    """Combine market and macro into a single HTML daily digest email."""
    ts = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    market_section = format_market_report_html(market_analysis, generated_at)
    macro_section = format_macro_report_html(macro_analysis, generated_at)

    # Strip the outer html/body tags and combine into one document
    def _extract_body(full_html: str) -> str:
        start = full_html.find("<body>") + len("<body>")
        end = full_html.rfind("</body>")
        return full_html[start:end] if start > 0 and end > 0 else full_html

    parts: list[str] = [f"<html><head>{_HTML_STYLE}</head><body>"]
    parts.append(
        f'<div class="header">'
        f'<h1>🌅 Daily Crypto Digest</h1>'
        f'<div class="ts">{_h(ts)}</div>'
        f'</div>'
    )
    parts.append(_extract_body(market_section))
    parts.append(_extract_body(macro_section))
    parts.append('<div class="footer">Powered by Claude AI | CryptoBot – Daily Digest</div>')
    parts.append("</body></html>")
    return "".join(parts)


# ─── Message splitting ────────────────────────────────────────────────────────

def split_for_telegram(text: str, max_len: int = 4096) -> list[str]:
    """
    Split a long message into chunks that fit Telegram's 4096-char limit.
    Attempts to split on double-newlines (paragraph boundaries).
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        # Try to find a paragraph break before the limit
        split_idx = remaining.rfind("\n\n", 0, max_len)
        if split_idx < max_len // 2:
            # No good paragraph break; fall back to newline
            split_idx = remaining.rfind("\n", 0, max_len)
        if split_idx <= 0:
            split_idx = max_len

        chunks.append(remaining[:split_idx].rstrip())
        remaining = remaining[split_idx:].lstrip()

    if remaining:
        chunks.append(remaining)

    return chunks
