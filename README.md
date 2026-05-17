# CryptoBot – AI-Powered Crypto Market Intelligence

A 24/7 agentic crypto market intelligence bot that collects data from multiple
sources, analyzes it with Claude (Anthropic), and sends reports to Telegram and
email on a configurable schedule.

---

## Features

- **Price data** every 4 hours via CoinGecko free API (top 20 coins by market cap)
- **Crypto news** via CryptoPanic API and RSS feeds (CoinDesk, CoinTelegraph, Decrypt)
- **Macro news** via NewsAPI.org (Fed, inflation, tariffs, GDP)
- **Social sentiment** via Reddit PRAW (r/CryptoCurrency, r/Bitcoin, r/ethereum)
- **Claude-powered analysis** with prompt caching for cost efficiency
- **Smart alerts** for major price moves (>5% in 1h by default)
- **Telegram** reports with markdown formatting and automatic message splitting
- **Email** HTML reports via SMTP
- **SQLite** storage for collected data and report history

---

## Project Structure

```
bot/
├── main.py              # Entry point, asyncio event loop
├── config.py            # Environment variable loading & validation
├── scheduler.py         # APScheduler job definitions
├── collectors/
│   ├── prices.py        # CoinGecko price fetching
│   ├── news.py          # CryptoPanic + RSS feeds
│   ├── macro.py         # NewsAPI macro-economic news
│   └── social.py        # Reddit PRAW sentiment
├── analyzers/
│   ├── base.py          # Claude API base analyzer (with prompt caching)
│   ├── market.py        # BTC/ETH/altcoin market analysis
│   ├── macro.py         # Macro events impact analysis
│   └── altcoin.py       # Altcoin sector analysis (Phase 2)
├── reporters/
│   ├── formatter.py     # Markdown + HTML report formatting
│   ├── telegram_sender.py
│   └── email_sender.py
└── storage/
    └── db.py            # SQLite async CRUD
```

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo>
cd rep1
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in all required values
```

Required variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key (https://console.anthropic.com) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Target chat/channel ID (negative for channels) |
| `EMAIL_SMTP_HOST` | SMTP server hostname |
| `EMAIL_SMTP_PORT` | SMTP port (default: 587) |
| `EMAIL_SMTP_USER` | SMTP username |
| `EMAIL_SMTP_PASS` | SMTP password / app password |
| `EMAIL_FROM` | From address |
| `EMAIL_TO` | Recipient address |
| `CRYPTOPANIC_API_KEY` | CryptoPanic free API key |
| `NEWS_API_KEY` | NewsAPI.org free API key |
| `REDDIT_CLIENT_ID` | Reddit app client ID |
| `REDDIT_CLIENT_SECRET` | Reddit app client secret |

### 3. Get API keys

- **Anthropic**: https://console.anthropic.com/
- **Telegram bot**: Message @BotFather on Telegram
- **CryptoPanic**: https://cryptopanic.com/developers/api/
- **NewsAPI**: https://newsapi.org/ (free tier: 100 req/day)
- **Reddit**: https://www.reddit.com/prefs/apps → Create app (script type)

### 4. Run the bot

```bash
python -m bot.main
```

Or directly:

```bash
python bot/main.py
```

---

## Schedule

| Job | Frequency | Actions |
|---|---|---|
| Market cycle | Every 4 hours | Fetch prices + crypto news → Claude analysis → send Telegram/email |
| Macro cycle | Every 6 hours | Fetch macro news + Reddit → Claude analysis → send Telegram/email |
| Daily digest | 07:00 UTC daily | Combined market + macro digest |
| Price alert | Triggered | Immediate alert if any coin moves >5% in 1h |

---

## Optional Configuration

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `DB_PATH` | `data/crypto_bot.db` | SQLite database file path |
| `PRICE_ALERT_THRESHOLD` | `5.0` | Percentage move to trigger immediate alert |

---

## Architecture Notes

### Claude API usage
- Model: `claude-sonnet-4-6` (configurable in `analyzers/base.py`)
- Prompt caching on the static system prompts reduces costs by ~90% on repeated calls
- Structured JSON output via `output_config.format`
- Each analyzer has a focused system prompt with domain expertise

### Data persistence
- All collected data is stored in SQLite via aiosqlite
- News items are deduplicated by URL
- Reports are stored with sent status for each channel

### Error handling
- All jobs log and continue on errors (never crash the scheduler)
- Individual API failures return empty data (not exceptions)
- Telegram retries 3 times with exponential backoff
- SMTP retries 3 times with exponential backoff

---

## Development

```bash
# Run with debug logging
LOG_LEVEL=DEBUG python -m bot.main

# Check database
sqlite3 data/crypto_bot.db ".tables"
sqlite3 data/crypto_bot.db "SELECT * FROM reports ORDER BY created_at DESC LIMIT 5;"
```
