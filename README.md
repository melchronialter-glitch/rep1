# CryptoBot

24/7 agentic crypto market intelligence.

> **Status: Phase A (spine).** The event bus, storage, Telegram outbound, and a
> stub triage agent are in place. Watchers (chain, social, news, market) and
> specialist agents (rug detector, narrative tracker, smart-money, etc.) land
> in subsequent phases. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full
> design and phase plan.

---

## What works today (Phase A)

- Redis Streams event bus with Postgres archive
- Postgres + TimescaleDB + pgvector via Docker
- Schema migrations (`cryptobot migrate`)
- Anthropic / Claude wrapper with prompt caching
- Telegram outbound to 4 channels (`strict`, `medium`, `firehose`, `macro`) + DM, with message splitting, retries, MarkdownV2 fallback
- End-to-end demo: CLI publishes an event → triage agent routes it → Telegram channel receives it
- CLI for ops (`migrate`, `health`, `publish`, `demo`, `events`, `alerts`)

## What does NOT work yet

Everything else. No chain watchers, no social listeners, no rug detector, no
on-demand `/analyze`, no web UI, no ML. They're scheduled across phases B–J in
the architecture doc.

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
├── agents/
│   └── triage.py         # Phase A stub triage agent
├── reporters/
│   ├── formatter.py      # render Event → Telegram message
│   └── telegram_out.py   # outbound bot, 4 channels, retries
└── cli/
    └── main.py           # `cryptobot` CLI

migrations/
└── 001_initial.sql       # events + alerts tables
```

---

## Next: Phase B

First real data flowing through the spine: price watcher (Binance WS),
news watcher (CryptoPanic + RSS), Claude-backed triage agent, and a
working `/analyze <coin>` command via Telegram DM.

See `ARCHITECTURE.md` §11 for the full build order.
