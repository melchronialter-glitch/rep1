# CryptoBot

24/7 agentic crypto market intelligence.

> **Status: Phase B (first real signals).** On top of the Phase A spine, the
> bot now watches Binance prices and crypto news, triages everything with
> Claude, answers `/analyze` and `/rugcheck` over Telegram, and sends a daily
> digest. Chain watchers, social listeners, and the ML rug detector land in
> subsequent phases. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full
> design and phase plan.

---

## What works today (Phase A + B)

- Redis Streams event bus with Postgres archive
- Postgres + TimescaleDB + pgvector via Docker
- Schema migrations (`cryptobot migrate`)
- Anthropic / Claude wrapper with prompt caching
- Telegram outbound to 4 channels (`strict`, `medium`, `firehose`, `macro`) + DM, with message splitting, retries, MarkdownV2 fallback
- **Price watcher**: Binance WebSocket miniTickers for a configurable symbol list → `market.price_move.*` alerts (threshold + cooldown) and `market.volume_spike.*`, with 60s snapshots to Postgres
- **News watcher**: CryptoPanic (if API key set) + RSS (CoinDesk, Cointelegraph, Decrypt, The Block), URL-deduped via Redis, macro keyword classifier → `news.crypto` / `news.macro` / `news.macro.high_impact`
- **Claude triage**: hard rules route macro and price events instantly; crypto news is batched (10 items / 60s) through Haiku and scored ignore/firehose/medium/strict — falls back to firehose on any LLM failure
- **`/analyze <symbol|address>` and `/rugcheck <address>`** via Telegram DM: gathers CoinGecko + DexScreener + GoPlus security data, runs a Sonnet assessment, replies in-chat
- **Telegram inbound**: long-polling command listener (`/analyze`, `/rugcheck`, `/status`, `/help`), restricted to your configured chat IDs
- **Daily digest** at 07:00 UTC: 24h alert/event summary written by Sonnet, delivered to Telegram DM + email (if SMTP configured)
- CLI for ops (`migrate`, `health`, `publish`, `demo`, `events`, `alerts`, `analyze`, `news`)

## What does NOT work yet

No chain watchers (new pairs, whales, LP events), no social listeners
(Telegram groups, X, Reddit, Discord), no rug detector ML, no narrative
tracker, no smart-money discovery, no web UI. They're scheduled across phases
C–J in the architecture doc.

---

## Quick start

### 1. Bring up infra

```bash
docker compose up -d
```

This starts Postgres (with TimescaleDB + pgvector) on `:5432` and Redis on
`:6379`.

### 2. Install

```bash
pip install -e .
```

### 3. Configure

```bash
cp .env.example .env
```

For Phase A you only need:

- `ANTHROPIC_API_KEY` (not strictly required for the demo, but required for any analysis)
- `TELEGRAM_BOT_TOKEN`
- At least one of `TELEGRAM_CHAT_STRICT|MEDIUM|FIREHOSE|MACRO|DM`

Create a bot via [@BotFather](https://t.me/BotFather). Create one Telegram
group/channel per tier, add the bot as admin, then grab each chat ID with
[@userinfobot](https://t.me/userinfobot) (channels are negative numbers).

### 4. Migrate the database

```bash
cryptobot migrate
```

### 5. Health check

```bash
cryptobot health
```

Should print `ok` for postgres, redis, and telegram.

### 6. Run the bot

```bash
python -m cryptobot.main
```

### 7. Fire the demo event

In another terminal:

```bash
cryptobot demo --channel firehose
# or:  cryptobot demo --channel strict
```

You should see a message land in the corresponding Telegram channel.

```bash
cryptobot events --limit 5
cryptobot alerts --limit 5
```

---

## Using /analyze

With the bot running (`python -m cryptobot.main`), DM your bot from any of
the configured chats:

```
/analyze btc                                        # by symbol
/analyze 0x6982508145454ce325ddbe47a25d4ec3d2311933 # by EVM contract address
/rugcheck 0x...                                     # safety-focused report
/status                                             # 24h event/alert counts
/help
```

The bot acks immediately ("working on it…") and replies in the same chat
with a markdown report: what the coin is, price action, liquidity/safety
read, risk score 1–10, and a verdict (avoid / watch / interesting).

The same analysis works from the CLI without the bot running (needs
`ANTHROPIC_API_KEY`):

```bash
cryptobot analyze pepe
cryptobot analyze 0x... --rugcheck
cryptobot news --limit 10          # recent collected news items
```

---

## Project layout

```
cryptobot/
├── config.py             # pydantic-settings, .env loading
├── logging.py            # structlog setup
├── db.py                 # asyncpg pool + migration runner
├── bus.py                # Redis Streams pub/sub + Postgres archive
├── topics.py             # canonical topic name constants
├── llm.py                # Anthropic wrapper with prompt caching
├── main.py               # process entry point
├── watchers/
│   ├── prices.py         # Binance WS → price moves + volume spikes
│   └── news.py           # CryptoPanic + RSS → news.* topics
├── agents/
│   ├── triage.py         # two-stage router: hard rules + Claude Haiku
│   ├── coin_analyst.py   # /analyze + /rugcheck deep-dives (Sonnet)
│   └── digest.py         # daily 07:00 UTC summary
├── intel/
│   └── coin_intel.py     # CoinGecko + DexScreener + GoPlus gatherer
├── reporters/
│   ├── formatter.py      # render Event → Telegram message
│   ├── telegram_out.py   # outbound bot, 4 channels + DM, retries
│   ├── telegram_in.py    # inbound command listener (long polling)
│   └── email_out.py      # SMTP digest sender (stdlib, executor)
└── cli/
    └── main.py           # `cryptobot` CLI

migrations/
├── 001_initial.sql       # events + alerts tables
└── 002_phase_b.sql       # price_snapshots, news_items, analyses
```

---

## Next: Phase C

Chain watchers: Helius webhooks + Pump.fun feed for Solana, Alchemy WS for
EVM new-pair events, BSC via QuickNode — `chain.new_pair.*` flows and the
firehose channel goes live.

See `ARCHITECTURE.md` §11 for the full build order.
