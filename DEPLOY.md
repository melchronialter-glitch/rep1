# Deploying CryptoBot

From zero to a running bot in roughly an hour. Tested path: Hetzner Cloud +
Ubuntu 24.04. Any VPS with 4+ GB RAM works the same way.

---

## 1. Get the server (~10 min)

1. Create an account at https://console.hetzner.com (needs a card or PayPal).
2. New Project → Add Server:
   - **Location**: Falkenstein or Nuremberg (EU) — closest to most crypto API
     edges; Ashburn if you prefer US.
   - **Image**: Ubuntu 24.04.
   - **Type**: **CPX21** (3 vCPU / 4 GB, ~€8/mo) is enough to start.
     **CX32** (4 vCPU / 8 GB, ~€15/mo) gives Postgres/TimescaleDB headroom
     once weeks of data accumulate. Resizing later is a 2-minute reboot.
   - **SSH key**: paste your public key (`cat ~/.ssh/id_ed25519.pub`;
     generate with `ssh-keygen -t ed25519` if you don't have one).
     Don't use password login.
3. Note the server IP. Log in: `ssh root@<IP>`.

Budget reality check: the server is €8–15/mo. The meaningful monthly cost is
Anthropic API usage (typically $10–40/mo at this alert volume — Haiku does
the high-frequency work) and optional paid data tiers later.

## 2. Prepare the box (~10 min)

```bash
# as root on the server
apt update && apt upgrade -y
apt install -y git curl ufw

# firewall: SSH only (the web UI stays tunneled — see §7)
ufw allow OpenSSH
ufw enable

# Docker (official convenience script)
curl -fsSL https://get.docker.com | sh

# Python 3.11+ is already on Ubuntu 24.04
apt install -y python3-venv python3-pip
```

## 3. Install CryptoBot (~5 min)

```bash
git clone <your-repo-url> /opt/cryptobot
cd /opt/cryptobot
docker compose up -d          # Postgres (Timescale+pgvector) + Redis
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## 4. Fill in `.env` (~20 min)

Open `.env` and work top to bottom. What each key costs and where to get it:

| Key | Where | Cost |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com | **required**, pay-per-use |
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram | free |
| `TELEGRAM_CHAT_*` (5 IDs) | create 4 groups + note your DM; IDs via @userinfobot | free |
| `TELEGRAM_USER_API_ID/HASH` | https://my.telegram.org (use the throwaway account) | free |
| `HELIUS_API_KEY` | helius.dev | free tier |
| `ALCHEMY_API_KEY` | alchemy.com | free tier |
| `BSC_WS_URL` | quicknode.com free endpoint, or skip | free |
| `CRYPTOPANIC_API_KEY` | cryptopanic.com/developers | free |
| `NEWS_API_KEY` | newsapi.org | free (100 req/day) |
| `APIFY_API_TOKEN` | apify.com | free tier to start |
| `COINGLASS_API_KEY` | coinglass.com | optional, paid — skip at first |

Needs **no key at all**: pump.fun stream, Reddit, DexScreener, GoPlus,
RugCheck, GeckoTerminal, Fear & Greed, Forex Factory calendar, Messari
events, Yahoo quotes.

Everything you leave blank simply self-disables with a log line — the
process always starts.

## 5. First run (~10 min)

```bash
source .venv/bin/activate
cryptobot migrate          # applies migrations 001–008
cryptobot health           # postgres/redis/telegram must say ok
cryptobot tg-login         # one-time: Telegram sends a code to the phone
python -m cryptobot.main   # run in the foreground first — watch the logs
```

In another terminal, prove the pipe end-to-end:

```bash
cryptobot demo --channel firehose    # → message lands in your firehose group
```

Then bootstrap the rug-classifier dataset (free, ~10 min of polite API calls):

```bash
cryptobot backfill-rugs --network solana
cryptobot backfill-rugs --network base
cryptobot backfill-rugs --network eth
```

This ingests decided survivors immediately and seeds fresh pools; the
outcome tracker labels the seeded ones from their on-chain fate over the
next 6–72 h and trains the model automatically once it has ≥20 labels with
both classes. Check progress any time with `cryptobot risk` and
`SELECT label, count(*) FROM rug_labels GROUP BY 1;`.

## 6. Keep it running: systemd

```bash
cat > /etc/systemd/system/cryptobot.service <<'EOF'
[Unit]
Description=CryptoBot market intelligence
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/cryptobot
ExecStart=/opt/cryptobot/.venv/bin/python -m cryptobot.main
Restart=always
RestartSec=10
Environment=LOG_JSON=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now cryptobot
journalctl -u cryptobot -f        # tail the logs
```

## 7. Web UI — keep it private

Don't open the port publicly. Tunnel it when you want to look:

```bash
# on your local machine (WSL2):
ssh -L 8080:localhost:8080 root@<IP>
# on the server (or add a second systemd unit):
cryptobot web --host 127.0.0.1
# then browse http://localhost:8080
```

## 8. What "working" looks like in the first 48 h

- **Minute 1**: pump.fun mints stream into `cryptobot tokens`; firehose
  group starts ticking.
- **Hour 1**: price/news alerts route through triage to the tiered groups;
  `/analyze btc` answers in DM.
- **Hour 6+**: outcome tracker's first cycles label confirmed LP pulls from
  the backfill seeds; `chain.lp_event` alerts appear.
- **Day 1–3**: enough labels accumulate → the classifier trains itself
  (look for `ml.train.done` in the logs) and `ml_rug_probability` starts
  appearing on new-pair alerts.
- **Daily 07:00 UTC**: digest in your DM (+ email if SMTP configured).

Expect to tune thresholds (`PRICE_MOVE_THRESHOLD_PCT`,
`PUMPFUN_MIN_INITIAL_BUY_SOL`, `NARRATIVE_SPIKE_THRESHOLD`) after the first
few days — the defaults are deliberately chatty so you can see everything,
then dial down.

## 9. Maintenance

```bash
# update
cd /opt/cryptobot && git pull && .venv/bin/pip install -e . \
  && .venv/bin/cryptobot migrate && systemctl restart cryptobot

# nightly DB backup (add to crontab -e)
0 3 * * * docker exec cryptobot-postgres pg_dump -U cryptobot cryptobot | gzip > /root/backup_$(date +\%u).sql.gz
```
