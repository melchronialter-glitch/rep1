-- =============================================================================
-- CryptoBot — Phase B schema (price snapshots, news items, analyses)
-- =============================================================================

-- ---- Price snapshots --------------------------------------------------------
-- One row per symbol per ~60s, written by the Binance price watcher.
CREATE TABLE IF NOT EXISTS price_snapshots (
    symbol      TEXT NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    volume_24h  DOUBLE PRECISION,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS price_snapshots_symbol_ts_idx
    ON price_snapshots (symbol, ts DESC);

SELECT create_hypertable('price_snapshots', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

-- ---- News items -------------------------------------------------------------
-- Every deduped news item from CryptoPanic / RSS.
CREATE TABLE IF NOT EXISTS news_items (
    id            UUID PRIMARY KEY,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,
    source        TEXT NOT NULL,
    published_at  TIMESTAMPTZ,
    is_macro      BOOLEAN NOT NULL DEFAULT FALSE,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS news_items_ts_idx ON news_items (ts DESC);
CREATE INDEX IF NOT EXISTS news_items_macro_idx ON news_items (is_macro, ts DESC);

-- ---- On-demand analyses -------------------------------------------------------
-- Results of /analyze and /rugcheck queries (and CLI analyze).
CREATE TABLE IF NOT EXISTS analyses (
    id          UUID PRIMARY KEY,
    query       TEXT NOT NULL,
    query_type  TEXT NOT NULL,           -- analyze|rugcheck
    result_md   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS analyses_created_at_idx ON analyses (created_at DESC);

-- Record this migration
INSERT INTO schema_migrations (version, name)
VALUES (2, 'phase_b')
ON CONFLICT (version) DO NOTHING;
