-- =============================================================================
-- CryptoBot — initial schema (Phase A)
-- =============================================================================
-- Only the tables we actually need for Phase A live here. Later phases add
-- their own migration files (002_..., 003_...) so we never edit history.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---- Schema version tracking ----------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---- Event archive --------------------------------------------------------
-- Every event that flows through the bus is also persisted here. Lets us
-- replay, debug, and later use as training data.
CREATE TABLE IF NOT EXISTS events (
    id          UUID PRIMARY KEY,
    topic       TEXT NOT NULL,
    source      TEXT NOT NULL,
    payload     JSONB NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS events_topic_ts_idx ON events (topic, ts DESC);
CREATE INDEX IF NOT EXISTS events_ts_idx ON events (ts DESC);

-- Convert to hypertable for time-series performance
SELECT create_hypertable('events', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

-- ---- Alerts sent ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id              UUID PRIMARY KEY,
    event_id        UUID REFERENCES events(id),
    channel         TEXT NOT NULL,           -- strict|medium|firehose|macro|dm
    tier            TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered       BOOLEAN NOT NULL DEFAULT FALSE,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS alerts_sent_at_idx ON alerts (sent_at DESC);
CREATE INDEX IF NOT EXISTS alerts_channel_idx ON alerts (channel, sent_at DESC);

-- Record this migration
INSERT INTO schema_migrations (version, name)
VALUES (1, 'initial')
ON CONFLICT (version) DO NOTHING;
