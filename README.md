# CryptoBot

24/7 agentic crypto market intelligence.

> **Status: Phase C (chain watchers).** On top of the Phase A spine and the
> Phase B signals, the bot now watches every new token launch on Solana
> (pump.fun always-on, Raydium via Helius), Ethereum/Base/Arbitrum (Alchemy),
> and BSC (any WS RPC) — `chain.new_pair.*` flows onto the bus with
> DexScreener enrichment and lands on the firehose channel. Safety screening,
> social listeners, and the ML rug detector land in subsequent phases. See
> [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design and phase plan.

---

## What works today (Phase A + B + C)

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
- **Pump.fun watcher** (always on, no key needed): PumpPortal WebSocket →
  every new Solana mint on `chain.new_pair.sol`, persisted to the `tokens`
  table; sub-threshold creator buy-ins (`PUMPFUN_MIN_INITIAL_BUY_SOL`) are
  tier-hinted "ignore" so triage drops them
- **Raydium watcher** (opt-in via `HELIUS_API_KEY`): logsSubscribe on the
  Raydium AMM program, `initialize2` detection + getTransaction decode →
  new pools with `tier_hint: medium`
- **EVM pair watcher** (opt-in via `ALCHEMY_API_KEY`): Uniswap V2/V3 (+
  Aerodrome on Base) factory events on Ethereum, Base, Arbitrum — one
  resilient task per chain
- **BSC pair watcher** (opt-in via `BSC_WS_URL`): PancakeSwap V2 factory
- **New-pair triage**: DexScreener enrichment (liquidity/fdv/price), then a
  quick heuristic split — liquidity ≥ $50k → medium channel, else firehose
- CLI for ops (`migrate`, `health`, `publish`, `demo`, `events`, `alerts`, `analyze`, `news`, `tokens`)

## What does NOT work yet

No safety screening / rug detector ML (Phase D brings RugCheck/GoPlus/
honeypot checks and real tiering), no whale/LP watchers, no social listeners
(Telegram groups, X, Reddit, Discord), no narrative tracker, no smart-money
discovery, no web UI. They're scheduled across phases D–J in the
architecture doc.

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
│   ├── news.py           # CryptoPanic + RSS → news.* topics
│   ├── macro_news.py     # NewsAPI macro stories → news.macro.*
│   ├── chain_common.py   # dual publish + tokens/pairs persistence helpers
│   ├── solana/
│   │   ├── pumpfun.py    # PumpPortal WS → every new pump.fun mint
│   │   └── dex.py        # Helius logsSubscribe → new Raydium pools
│   ├── evm/
│   │   └── pairs.py      # Alchemy WS → Uniswap V2/V3 + Aerodrome pairs
│   └── bsc.py            # PancakeSwap V2 factory over BSC_WS_URL
├── agents/
│   ├── triage.py         # two-stage router: hard rules + Claude Haiku
│   ├── coin_analyst.py   # /analyze + /rugcheck deep-dives (Sonnet)
│   └── digest.py         # daily 07:00 UTC summary
├── intel/
│   ├── coin_intel.py     # CoinGecko + DexScreener + GoPlus gatherer
│   └── enrich.py         # DexScreener enrichment for new pairs
├── reporters/
│   ├── formatter.py      # render Event → Telegram message
│   ├── telegram_out.py   # outbound bot, 4 channels + DM, retries
│   ├── telegram_in.py    # inbound command listener (long polling)
│   └── email_out.py      # SMTP digest sender (stdlib, executor)
└── cli/
    └── main.py           # `cryptobot` CLI

migrations/
├── 001_initial.sql       # events + alerts tables
├── 002_phase_b.sql       # price_snapshots, news_items, analyses
└── 003_phase_c.sql       # tokens, pairs
```

---

## Next: Phase D

Safety + rug detection v1: `intel/safety/` adapters (RugCheck, GoPlus,
Honeypot.is), the first rug detector with hard rules + heuristic score, and
proper tiered alerts (strict / medium / firehose).

See `ARCHITECTURE.md` §11 for the full build order.
