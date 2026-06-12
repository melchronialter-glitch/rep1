# CryptoBot

24/7 agentic crypto market intelligence.

> **Status: Phases A–I built.** All intelligence layers are in: chain +
> social + news + market watchers, the deterministic rug detector with an
> advisory ML classifier on top (train it with `cryptobot train-rug-model`
> once you've labeled coins via `/rug` / `/notrug`), technical-indicator
> buy/sell signal candidates (RSI/MACD/EMA/Bollinger), narrative tracking,
> smart-money scaffolding, macro impact analysis, and a FastAPI web UI
> (`cryptobot web`). Remaining: Phase J (the sniper interface — separate
> project) and items that need live data to mature (ML accuracy, caller
> performance scoring). See [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## What works today (Phase A + B + C + D + E)

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
- **Safety adapters** (`intel/safety/`): GoPlus token security +
  Honeypot.is simulation (EVM, fanned out concurrently), RugCheck summary
  (Solana) — all best-effort, a dead API degrades instead of failing
- **Rug detector** (replaces the Phase C new-pair triage heuristic):
  DexScreener enrichment → safety screen → deterministic 0–100 hard-rule
  risk score (honeypot, taxes, mint/proxy/selfdestruct flags, owner
  concentration, RugCheck risks, liquidity floor) → tiered routing:
  score ≥ 70 → firehose with a "⚠️ HIGH RISK" title; score < 30 and
  liquidity ≥ $50k → strict; score < 50 and liquidity ≥ $10k → medium;
  everything else → firehose. Fresh pump.fun mints are scored "unscreened"
  (the safety APIs don't know them yet) and stay in the firehose
- **`risk_scores` table**: every score persisted with reasons + the raw
  safety report — the Phase H ML training set
- **Richer `/rugcheck`**: the full safety fan-out plus the deterministic
  score is handed to Claude, which anchors its 1–10 rating on it
- **Telegram group listener** (opt-in via `TELEGRAM_USER_API_ID/HASH` +
  one-time `cryptobot tg-login`): Telethon user-account session listens to
  your groups (`TG_WATCH_CHATS` to narrow, empty = all); messages with a
  contract address are archived to `tg_messages`
- **TG call parser**: address + buy-language ("ape", "100x", "send it", …)
  or `$TICKER` = a call → persisted to `tg_calls`, caller history upserted
  in `tg_callers`, routed to medium (watched group) or firehose
- **X watcher** (opt-in via `APIFY_API_TOKEN` or `TWITTERAPI_IO_KEY`):
  polls `X_WATCH_HANDLES` every 2 min; tweets with an address/$ticker are
  archived to `tweets`
- **Reddit listener** (always on, no key): public JSON API on
  `REDDIT_SUBREDDITS`; signal posts archived to `reddit_posts`
- **Translator agent**: CJK / Hangul / Cyrillic detection → Claude Haiku
  translation back onto the same topic with a loop-guard flag
- **Discord**: intentionally a stub — selfbots violate Discord ToS; needs a
  verified bot application (revisited in a later phase)
- CLI for ops (`migrate`, `health`, `publish`, `demo`, `events`, `alerts`, `analyze`, `news`, `tokens`, `risk`, `calls`, `tg-login`)

## What does NOT work yet / honest limitations

- **The ML classifier ships untrained.** Routing stays on the deterministic
  hard-rule score until you label ≥20 coins with `/rug` / `/notrug` (or
  `cryptobot label`) and run `cryptobot train-rug-model`. Even then the
  model is advisory (`ml_rug_probability` on alerts) — it never overrides
  the hard rules.
- Pump.fun mints get no real safety screen (the APIs don't index them that
  early) — scored "unscreened", kept in the firehose.
- RugCheck/Honeypot.is/Messari/Forex-Factory are free endpoints with no
  SLA; when one is down the relevant signal silently degrades.
- Caller scoring is raw call volume; "did their calls actually pump?"
  performance scoring needs price-history joins that mature with live data.
- Smart-money discovery is scaffolding: the whale watcher reads wallets
  from `cb:watched_wallets:{chain}` Redis sets, but automatic discovery of
  *new* profitable wallets from on-chain history isn't built.
- No Discord listener (selfbots violate ToS — needs a verified bot app).
- No LP-lock checks or LP-event watcher (`chain.lp_event` is declared but
  nothing publishes it).
- Phase J (sniper interface) is intentionally not built — only the signal
  contract in `cryptobot/sniper_interface/README.md`.

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
│   ├── rug_detector.py   # safety screen + 0–100 risk score for new pairs
│   ├── coin_analyst.py   # /analyze + /rugcheck deep-dives (Sonnet)
│   └── digest.py         # daily 07:00 UTC summary
├── intel/
│   ├── coin_intel.py     # CoinGecko + DexScreener + GoPlus gatherer
│   ├── enrich.py         # DexScreener enrichment for new pairs
│   └── safety/           # Phase D safety fan-out
│       ├── __init__.py   # safety_report(chain, address)
│       ├── goplus.py     # GoPlus token security (EVM)
│       ├── honeypot.py   # Honeypot.is simulation (EVM)
│       └── rugcheck.py   # RugCheck summary (Solana)
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
├── 003_phase_c.sql       # tokens, pairs
└── 004_phase_d.sql       # risk_scores
```

---

## Next: Phase E

Social listeners: Telegram groups via Telethon, the TG call parser, X
(Apify/TwitterAPI adapters), Reddit, Discord, and the translator agent for
non-English sources.

See `ARCHITECTURE.md` §11 for the full build order.
