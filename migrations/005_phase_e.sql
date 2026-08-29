-- =============================================================================
-- CryptoBot — Phase E schema (social listeners: telegram, X, callers)
-- =============================================================================

-- ---- Telegram messages ------------------------------------------------------
-- Only messages that contain a contract address are stored (the raw firehose
-- stays on the bus with persist=false). Addresses found in the text are kept
-- as a jsonb array for later joins against tokens/risk_scores.
CREATE TABLE IF NOT EXISTS tg_messages (
    id           UUID PRIMARY KEY,
    chat_id      TEXT,
    chat_title   TEXT,
    sender_id    TEXT,
    sender_name  TEXT,
    text         TEXT,
    addresses    JSONB,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---- Detected calls -----------------------------------------------------------
-- One row per call detected by the tg_call_parser agent. The (address, ts)
-- index supports "who called this coin and when" lookups for caller scoring.
CREATE TABLE IF NOT EXISTS tg_calls (
    id            UUID PRIMARY KEY,
    address       TEXT,
    chain_guess   TEXT,
    tickers       JSONB,
    chat_title    TEXT,
    sender_id     TEXT,
    sender_name   TEXT,
    buy_language  BOOLEAN,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS tg_calls_address_ts_idx
    ON tg_calls (address, ts DESC);

-- ---- Caller score book ----------------------------------------------------
-- Upserted on every detected call. calls_count is the raw shill volume; the
-- performance scoring (did their calls pump?) lands in a later phase.
CREATE TABLE IF NOT EXISTS tg_callers (
    sender_id    TEXT PRIMARY KEY,
    sender_name  TEXT,
    calls_count  INT NOT NULL DEFAULT 1,
    first_seen   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---- Tweets -----------------------------------------------------------------
-- Only tweets carrying a contract address or $ticker are stored. The PK is
-- the upstream tweet id (text), which doubles as a durable dedupe.
CREATE TABLE IF NOT EXISTS tweets (
    id          TEXT PRIMARY KEY,
    handle      TEXT,
    text        TEXT,
    likes       INT,
    retweets    INT,
    url         TEXT,
    created_at  TEXT,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---- Reddit posts -----------------------------------------------------------
-- Only posts carrying a contract address or $ticker are stored.
CREATE TABLE IF NOT EXISTS reddit_posts (
    id          TEXT PRIMARY KEY,
    subreddit   TEXT,
    title       TEXT,
    text        TEXT,
    url         TEXT,
    score       INT,
    author      TEXT,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Record this migration
INSERT INTO schema_migrations (version, name)
VALUES (5, 'phase_e')
ON CONFLICT (version) DO NOTHING;
