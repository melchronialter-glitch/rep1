# CryptoBot — Architecture

> Living design document. Approve / amend before code is written.

---

## 1. What this system is

A 24/7 **agentic** crypto intelligence system. Not a cron job. The bot:

- **Listens** continuously to many real-world sources (chain, social, news, market)
- **Reacts** to events as they happen — not on a fixed schedule
- **Investigates** anything suspicious or promising with specialist agents
- **Learns** from every confirmed rug, pump, narrative — feeds it back into detection
- **Reports** to you via Telegram (3 tiers) + email + web UI + CLI
- **Answers** on-demand questions about any coin
- **Exposes** a clean signal interface that a future sniper/trading bot will subscribe to

---

## 2. Topology — two nodes, one brain

```
┌─────────────────────────────┐       ┌─────────────────────────────┐
│  CLOUD NODE (Hetzner CX22)  │       │  LOCAL NODE (WSL2 / Win)    │
│  Always on. Owns:           │       │  On when you are. Owns:     │
│                             │       │                             │
│  • All persistent listeners │◄─────►│  • Interactive web UI       │
│  • Postgres + TimescaleDB   │  bus  │  • CLI tools                │
│  • Redis (event bus + cache)│       │  • Heavy ML training jobs   │
│  • All real-time agents     │       │  • Backtesting / research   │
│  • Telegram bot replies     │       │  • Manual tagging UI        │
└─────────────────────────────┘       └─────────────────────────────┘
```

Both nodes connect to the **same Postgres + Redis on cloud**. The local node is a thick client — it can read everything, run heavy compute, and write back labels/configs. The cloud node never depends on local being up.

---

## 3. The event bus (the spine)

Everything is built around **Redis Streams** as a pub/sub event bus. Every watcher publishes events; every agent subscribes to topics it cares about.

### Topic taxonomy

```
chain.new_pair.{sol|eth|bsc|base|arb}        # new LP created
chain.whale_move.{chain}                      # tracked wallet activity
chain.lp_event.{chain}                        # lock/unlock/burn/pull
chain.large_transfer.{chain}                  # >$threshold transfers
chain.contract_deployed.{chain}               # new token contracts

social.tg.message                             # from monitored TG groups
social.tg.call                                # detected call/shill in TG
social.x.tweet                                # from watched X accounts
social.x.trending                             # narrative spike detected
social.discord.message
social.reddit.post

news.crypto                                   # CryptoPanic + RSS
news.macro                                    # NewsAPI + Fed calendar
news.macro.high_impact                        # CPI, NFP, FOMC, tariff news

market.price_move.{symbol}                    # >threshold % in window
market.funding_anomaly.{symbol}               # funding rate spike
market.liquidation_cluster.{symbol}           # liquidation cascade
market.volume_spike.{symbol}

signal.alert.strict                           # → main Telegram channel
signal.alert.medium                           # → research channel
signal.alert.firehose                         # → raw feed channel
signal.alert.macro                            # → macro channel

intel.user_query                              # /analyze, /rugcheck, etc.
intel.coin_labeled                            # manual tag from user
intel.rug_confirmed                           # auto or manual rug label
```

---

## 4. Watchers (publishers — all on cloud node)

| Watcher | Source | Publishes to | Notes |
|---|---|---|---|
| `solana_pumpfun_watcher` | Helius webhooks + Pump.fun WS | `chain.new_pair.sol` | every new launch |
| `solana_dex_watcher` | Helius + Raydium/Jupiter | `chain.new_pair.sol`, `chain.lp_event.sol` | post-bonding migrations |
| `evm_pair_watcher` | Alchemy WS + Uniswap V2/V3 factory | `chain.new_pair.{eth\|base\|arb}` | |
| `bsc_pair_watcher` | QuickNode + PancakeSwap factory | `chain.new_pair.bsc` | |
| `whale_watcher` | Helius (sol) + Alchemy (evm) | `chain.whale_move.*`, `chain.large_transfer.*` | dynamic watchlist |
| `lp_watcher` | Per-chain on-chain logs | `chain.lp_event.*` | adds/removes/locks |
| `telegram_listener` | Telethon (user account) | `social.tg.message`, `social.tg.call` | listens to all joined groups |
| `discord_listener` | discord.py (user account or bot) | `social.discord.message` | |
| `x_listener` | Apify or TwitterAPI.io adapter | `social.x.tweet` | polls every 30–120s |
| `reddit_listener` | PRAW streaming | `social.reddit.post` | |
| `news_watcher` | CryptoPanic + RSS + NewsAPI | `news.*` | macro events also publish `news.macro.high_impact` |
| `econ_calendar_watcher` | Trading-economics / investing.com scrape | `news.macro.high_impact` | scheduled events with countdown |
| `price_watcher` | Binance WS + CoinGecko | `market.price_move.*`, `market.volume_spike.*` | |
| `derivatives_watcher` | Coinglass / Binance futures | `market.funding_anomaly.*`, `market.liquidation_cluster.*` | |
| `indicator_engine` | computed from `prices_ts` OHLCV | `market.indicator_signal.{symbol}` | RSI, MACD, EMA crosses, Bollinger touches, volume profile — buy/sell signal candidates |
| `orderbook_watcher` | Binance depth WS | `market.orderbook_imbalance.{symbol}` | bid/ask wall detection, depth imbalance |
| `sentiment_index_watcher` | Fear & Greed (alternative.me), DXY/SPX/gold via free quotes | `market.sentiment_shift` | macro-correlation context for analysis |
| `launch_radar_watcher` | ICO/IDO calendars, vesting unlock trackers (token.unlocks-style scrape, CryptoRank/ICODrops) | `chain.upcoming_launch`, `chain.vesting_unlock` | presales, fair launches, vesting cliffs, private-round unlock schedules |
| `dev_activity_watcher` | GitHub API (free) | `social.dev_activity` | commit cadence on tracked project repos — real-project signal |

---

## 5. Agents (subscribers — do the thinking)

Each agent runs as its own async process. Subscribes to bus topics, processes events, may publish derived events, may call Claude.

### Core agents

**`triage_agent`** — universal first-pass router
- Subscribes: every chain/social event
- Decides: ignore / route to specialist / immediate alert
- Cheap heuristics first, Claude only when ambiguous
- Publishes to `signal.alert.*` for direct alerts

**`coin_analyst_agent`** — full coin deep-dive
- Subscribes: `intel.user_query` (when `/analyze` is called), or invoked by other agents
- Pulls: prices, holders, top-holder distribution, LP status, contract safety (GoPlus/RugCheck), socials, recent tweets, dev wallet history
- Runs Claude with structured output → analysis report
- Publishes report; sender picks it up

**`rug_forensic_agent`** — post-mortem learner
- Subscribes: `intel.rug_confirmed`
- Pulls full historical state of the rugged token from the moment it launched
- Extracts feature vector (contract age, top-holder concentration over time, LP behavior, dev wallet ops, social momentum, KOL touches, narrative cluster)
- Writes labeled row to `rugs` table → ML training set
- Asks Claude to summarize the *pattern* in plain English → knowledge base

**`rug_detector_agent`** — real-time risk scorer
- Subscribes: `chain.new_pair.*`, `chain.lp_event.*`
- Runs sklearn/xgboost model trained on `rugs` table → risk score 0–100
- Combined with hard-rule checks (mint authority, LP locked, top-1 holder %, honeypot test)
- Publishes to `signal.alert.{strict|medium|firehose}` based on tier rules

**`narrative_tracker_agent`** — what's the market talking about
- Subscribes: `social.x.tweet`, `social.tg.message`, `news.crypto`
- Clusters posts into narratives (AI agents, RWA, dog coins, political, gaming, L2, restaking, etc.) using embeddings + Claude
- Tracks lifecycle: emerging → trending → peaking → fading
- Detects narrative spikes → publishes `social.x.trending`
- Maintains `narratives` table

**`smart_money_agent`** — dynamic whale discovery
- Subscribes: `chain.large_transfer.*`, `chain.new_pair.*`
- Watches every wallet that bought a token early and exited profitably above a threshold
- Scores wallets by win rate, ROI, frequency
- Auto-promotes wallets to dynamic watchlist (top N by rolling score)
- Demotes wallets that go cold
- Publishes derived `chain.whale_move.*` events when watchlist wallets trade

**`macro_impact_agent`** — econ → crypto translator
- Subscribes: `news.macro.high_impact`
- Pre-event: posts countdown + consensus expectation
- Post-event: runs Claude to interpret actual vs expected → crypto impact direction + magnitude
- Publishes `signal.alert.macro`

**`tg_call_parser_agent`** — extract signals from Telegram groups
- Subscribes: `social.tg.message`
- Detects when a message is a "call" (mentions a contract address + buy language)
- Looks up the caller's historical performance (if seen before)
- Publishes `social.tg.call` with caller credibility score

**`digest_agent`** — periodic summaries
- Daily at 07:00 UTC: assembles top events from last 24h → digest report
- Weekly Sunday: assembles week summary + narrative shifts + best/worst-performing alerts
- Sends via Telegram + email

### Translation layer

For non-English social monitoring (Chinese, Korean, Russian):
- `translator_agent` subscribes to all `social.*` events, detects language, translates non-English → English using a cheap model (Haiku), republishes as `social.x.tweet.translated`
- All downstream agents consume the translated stream

---

## 6. The ML rug classifier (the "learning" part)

Three layers of intelligence about rugs, stacked:

1. **Hard rules** (fastest, deterministic) — mint authority not revoked, LP not locked, top holder >40%, honeypot test fails → instant high risk
2. **xgboost classifier** trained on labeled `rugs` table — produces probability score on ~60 features. Retrains weekly.
3. **Claude pattern memory** — `rug_forensic_agent` writes plain-English pattern summaries into a vector DB; new tokens get checked for similar patterns via embedding search

The classifier features (~60 total) span:
- Contract: age, mint/freeze auth, LP lock duration, top-N holder %, holder count trajectory, transfer tax
- Liquidity: initial LP size, LP add/remove pattern, LP-to-mcap ratio over time
- Dev: dev wallet age, dev wallet rug history, dev wallet fund source (CEX? mixer?)
- Social: KOL mentions, mention velocity, sentiment, narrative cluster
- Market: price action shape, volume pattern, buy/sell ratio

Labels come from:
- **Auto**: price drops >90% from ATH within 7d AND LP pulled OR top holder dumps >50% of supply
- **Manual**: user `/rug <address>` command via Telegram
- **Manual untag**: `/notrug <address>` (false positives are gold for training)

---

## 7. Output channels

### Telegram (4 channels, 1 bot)
- **Main alerts** (`strict`) — high-confidence, actionable. ~5–20/day.
- **Research feed** (`medium`) — interesting but riskier. ~50–150/day.
- **Firehose** (`firehose`) — every new pair with risk score. Hundreds/day, mute-able.
- **Macro channel** — macro events + market structure shifts.

Plus the **bot DM** for on-demand commands:
- `/analyze <address|symbol>` — full deep-dive
- `/rugcheck <address>` — safety report
- `/whales <address>` — holder + recent whale activity
- `/narrative <topic>` — narrative status
- `/watch <address>` — add to personal watchlist (alerts on any signal)
- `/unwatch <address>`
- `/rug <address>` — manually label as rug (trains model)
- `/notrug <address>` — unlabel
- `/calls <user>` — performance history of a TG caller
- `/digest` — on-demand summary

### Email
- Daily digest (07:00 UTC)
- Weekly digest (Sunday 09:00 UTC)
- Critical-only alerts (optional, configurable)

### Web UI (FastAPI + HTMX, runs on both nodes)
- Live event feed
- Coin browser with charts, holders, socials
- Narrative dashboard
- Rug pattern viewer
- Manual labeling interface
- Watchlist manager
- Config editor

### CLI (`cryptobot` command on local node)
- `cryptobot analyze <address>`
- `cryptobot watch <address>`
- `cryptobot narratives`
- `cryptobot rugs --since=7d`
- `cryptobot config get|set`
- `cryptobot backfill <chain>`

---

## 8. Storage

### Postgres (cloud, primary state)
- `tokens` — every token we've ever seen
- `pairs` — every LP pair
- `holders` — snapshot rows (token, wallet, balance, ts)
- `transfers` — large transfers + tracked wallet transfers
- `wallets` — wallet metadata + smart-money scores
- `tg_messages`, `tweets`, `discord_messages`, `reddit_posts`, `news_items`
- `narratives` + `narrative_membership`
- `rugs` — labeled training data
- `risk_scores` — historical scores over time
- `alerts` — every alert sent, with outcome tracking
- `watchlist_user` — your personal watch list
- `watchlist_dynamic` — auto-managed smart-money wallets
- `kb_patterns` — Claude-generated pattern summaries (with embeddings)

### TimescaleDB extension on Postgres
- `prices_ts` — OHLCV hypertable
- `funding_ts`, `oi_ts` — derivatives

### Redis (cloud)
- Event bus (Streams)
- Hot cache (current prices, recent tweets, computed features)
- Rate-limit counters

### Vector store
- Postgres `pgvector` extension for `kb_patterns` embeddings (no extra service needed)

---

## 9. Tech stack

- **Language**: Python 3.11+ everywhere
- **Async**: asyncio + aiohttp + asyncpg
- **Bus**: Redis Streams (via redis-py async)
- **DB**: Postgres 16 + TimescaleDB + pgvector
- **LLM**: Anthropic SDK; `claude-sonnet-4-6` for analysis, `claude-haiku-4-5` for translation/cheap triage. Prompt caching on every static system prompt.
- **ML**: scikit-learn + xgboost; feast or simple parquet for feature store
- **Telegram**: Telethon (listener, user account) + python-telegram-bot (outbound bot)
- **Discord**: discord.py
- **Web**: FastAPI + HTMX + Tailwind (no React, keep it light)
- **CLI**: Typer
- **Process supervision**: systemd on cloud, supervisord or just WSL on local
- **Containerization**: docker-compose for local dev parity
- **Secrets**: `.env` + sops or just `.env` for now

---

## 10. Project structure

```
rep1/
├── ARCHITECTURE.md
├── README.md
├── docker-compose.yml              # postgres, redis, the bot
├── pyproject.toml
├── .env.example
│
├── cryptobot/
│   ├── __init__.py
│   ├── config.py
│   ├── bus.py                      # Redis Streams pub/sub
│   ├── db.py                       # asyncpg pool + schema
│   ├── llm.py                      # Claude wrapper w/ caching
│   ├── translation.py
│   │
│   ├── watchers/
│   │   ├── solana/{pumpfun,dex,whales,lp}.py
│   │   ├── evm/{pairs,whales,lp}.py
│   │   ├── bsc/{pairs}.py
│   │   ├── telegram_listener.py
│   │   ├── discord_listener.py
│   │   ├── x/{base,apify,twitterapi}.py
│   │   ├── reddit_listener.py
│   │   ├── news.py
│   │   ├── econ_calendar.py
│   │   ├── prices.py
│   │   └── derivatives.py
│   │
│   ├── agents/
│   │   ├── triage.py
│   │   ├── coin_analyst.py
│   │   ├── rug_forensic.py
│   │   ├── rug_detector.py
│   │   ├── narrative_tracker.py
│   │   ├── smart_money.py
│   │   ├── macro_impact.py
│   │   ├── tg_call_parser.py
│   │   ├── digest.py
│   │   └── translator.py
│   │
│   ├── ml/
│   │   ├── features.py             # feature extraction
│   │   ├── rug_model.py            # train + predict
│   │   ├── train.py                # CLI: train new model
│   │   └── store/                  # versioned model artifacts
│   │
│   ├── reporters/
│   │   ├── telegram_out.py         # bot replies + alert channels
│   │   ├── email_out.py
│   │   └── formatter.py
│   │
│   ├── intel/
│   │   ├── coin_intel.py           # the "analyze any coin" library
│   │   ├── chain_clients/{sol,evm,bsc}.py
│   │   ├── safety/{rugcheck,goplus,honeypot}.py
│   │   └── socials/{x,tg,discord}.py
│   │
│   ├── web/
│   │   ├── app.py                  # FastAPI
│   │   ├── routes/
│   │   └── templates/
│   │
│   ├── cli/
│   │   └── main.py                 # Typer CLI
│   │
│   └── sniper_interface/           # PLACEHOLDER for phase 3
│       └── README.md               # docs the signal format
│
├── migrations/                     # postgres schema (alembic or raw SQL)
└── tests/
```

---

## 11. Build order (so we make progress, not big-bang)

We build in phases. Each phase ends with something **runnable and useful**.

### Phase A — Foundation (do first)
1. Postgres + Redis docker-compose
2. Schema migrations
3. `bus.py` event bus
4. `llm.py` Claude wrapper with caching
5. `db.py` asyncpg pool
6. `config.py`
7. Telegram outbound bot (alert channels work)
8. Reporter formatter
9. A "hello world" agent that publishes a fake event → triage → telegram

**End state**: events flow end-to-end. Nothing useful yet, but the spine works.

### Phase B — First real signals
1. `price_watcher` (Binance WS) → `market.price_move`
2. `news_watcher` (CryptoPanic + RSS)
3. `triage_agent` (basic rules + Claude)
4. `coin_analyst_agent` (working `/analyze` command)
5. `digest_agent` (daily digest)

**End state**: bot already useful — sends price alerts, news, daily summaries, answers `/analyze`.

### Phase C — Chain watchers
1. Solana: Helius webhooks + Pump.fun feed
2. EVM: Alchemy WS for new pair events
3. BSC: similar
4. `chain.new_pair.*` flows; `firehose` channel goes live
5. `launch_radar_watcher`: presales, fair-launch calendars, vesting unlock schedules

**End state**: every new launch on every chain visible in firehose, with basic enrichment.

### Phase D — Safety + rug detection v1
1. `intel/safety/` adapters (RugCheck, GoPlus, Honeypot.is)
2. `rug_detector_agent` v1: hard rules + simple heuristic score
3. Tiered alerts (`strict` / `medium` / `firehose`)
4. `/rugcheck` command

**End state**: usable rug filtering, tiered alert channels live.

### Phase E — Social listeners
1. `telegram_listener` (Telethon)
2. `tg_call_parser_agent`
3. `x_listener` (Apify + TwitterAPI adapter)
4. `reddit_listener`
5. `discord_listener`
6. `translator_agent` for non-English

**End state**: social signals flowing.

### Phase F — Smart money + narratives
1. `smart_money_agent` with dynamic watchlist
2. `narrative_tracker_agent` with embeddings
3. `whale_watcher` + `chain.whale_move`
4. `dev_activity_watcher` (GitHub commit cadence on tracked projects)

**End state**: agentic discovery working — bot finds whales and narratives on its own.

### Phase G — Macro, derivatives + technical indicators
1. `econ_calendar_watcher`
2. `derivatives_watcher` (Coinglass)
3. `macro_impact_agent`
4. `indicator_engine`: RSI, MACD, EMA crosses, Bollinger, volume profile computed from stored OHLCV → buy/sell signal candidates
5. `orderbook_watcher`: Binance depth — wall/imbalance detection
6. `sentiment_index_watcher`: Fear & Greed, DXY/SPX/gold correlation context

### Phase H — Learning loop
1. Auto-rug labeling
2. `/rug` and `/notrug` commands
3. `rug_forensic_agent` pattern extraction
4. ML feature pipeline
5. xgboost training pipeline
6. Inference integrated into `rug_detector_agent`

**End state**: bot is *learning*.

### Phase I — Web UI + CLI
1. FastAPI app
2. CLI tool
3. Dashboard pages

### Phase J — Sniper interface (later, separate project)
- Document signal contract
- Provide reference subscriber

---

## 12. Budget allocation ($200/mo cap)

| Item | Cost | Notes |
|---|---|---|
| Hetzner CX22 | €4.50 / ~$5 | 4GB VPS, plenty for v1 |
| Helius (Solana) Developer | $49 | webhooks, enhanced API, RPC |
| Alchemy Growth (EVM) | $49 | WS + archive |
| BSC: QuickNode free + public RPCs | $0 | upgrade if needed |
| Apify (X scraping) | ~$40 | usage-based |
| TwitterAPI.io | ~$15 | fallback adapter |
| Coinglass API | ~$30 | derivatives |
| Claude API | ~$30–50 | usage-based, with caching |
| **Total** | **~$220** | slightly over; trim Coinglass or X spend if needed |

Free tier suffices: CoinGecko, CryptoPanic, NewsAPI, Reddit, Telethon, Discord, RugCheck, GoPlus, Honeypot.is, DexScreener, Birdeye public, Pump.fun WS.

---

## 13. What we throw away from the previous build

The Phase-1 code I wrote yesterday (`bot/` directory) is the wrong shape. We keep:
- Nothing structurally
- Concepts only: the CoinGecko collector, the RSS reader, the email sender, the markdown formatter — we'll port these *into* the new `cryptobot/` package as library functions, not as the architectural backbone.

The `bot/` directory will be deleted in the first commit of Phase A.

---

## 14. Open questions for you

None blocking — every architectural decision has a default I'll make if you don't object. Things you might want to weigh in on later (not now):

- Specific TG groups, X handles, Discord servers you want monitored (you said you'll add over time — config file)
- Whether you want a separate "personal portfolio" watch tier with stricter alerts on coins you actually hold
- Whether the sniper interface should be a Telegram channel (so any sniper bot that reads TG can plug in) or a NATS/Webhook (so we don't depend on TG for execution)

---
