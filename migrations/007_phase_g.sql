-- Phase G: market depth, technical indicators, vesting/launch radar, econ calendar
-- Run after 006_phase_f.sql

-- indicator_signals: persisted buy/sell signal events for ML training
CREATE TABLE IF NOT EXISTS indicator_signals (
    id UUID PRIMARY KEY,
    symbol TEXT NOT NULL,
    rsi DOUBLE PRECISION,
    macd DOUBLE PRECISION,
    macd_histogram DOUBLE PRECISION,
    bb_position DOUBLE PRECISION,  -- 0=at lower band, 1=at upper band
    volume_ratio DOUBLE PRECISION,
    signals JSONB,
    bias TEXT,
    price DOUBLE PRECISION,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS indicator_signals_symbol_ts_idx
    ON indicator_signals (symbol, ts DESC);

SELECT create_hypertable('indicator_signals', 'ts',
    if_not_exists => TRUE,
    migrate_data  => TRUE);

-- vesting_events: upcoming token unlocks and launches, and econ calendar seen-set
CREATE TABLE IF NOT EXISTS vesting_events (
    id TEXT PRIMARY KEY,       -- sha1-based dedupe key (also used for econ events)
    title TEXT,
    event_date TEXT,
    event_type TEXT,           -- 'unlock' | 'launch' | 'econ_event'
    coin TEXT,                 -- token symbol or currency code
    source TEXT,               -- 'messari' | 'forex_factory'
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Schema migration tracking
INSERT INTO schema_migrations (version, name)
VALUES (7, 'phase_g')
ON CONFLICT (version) DO NOTHING;
