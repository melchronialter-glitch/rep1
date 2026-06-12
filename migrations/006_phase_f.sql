-- Phase F: smart money wallets + narrative tracking tables

CREATE TABLE IF NOT EXISTS smart_wallets (
    wallet_address TEXT NOT NULL,
    chain TEXT NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    calls_count INT NOT NULL DEFAULT 0,
    profitable_calls INT NOT NULL DEFAULT 0,
    total_pnl_usd DOUBLE PRECISION,
    notes TEXT,
    PRIMARY KEY (wallet_address, chain)
);

CREATE TABLE IF NOT EXISTS narrative_snapshots (
    id UUID PRIMARY KEY,
    coin TEXT NOT NULL,
    address TEXT,
    mentions_1h INT NOT NULL DEFAULT 0,
    mentions_4h INT NOT NULL DEFAULT 0,
    mentions_24h INT NOT NULL DEFAULT 0,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS narrative_snapshots_coin_ts_idx ON narrative_snapshots (coin, ts DESC);
CREATE INDEX IF NOT EXISTS narrative_snapshots_ts_idx ON narrative_snapshots (ts DESC);

INSERT INTO schema_migrations (version, name) VALUES (6, 'phase_f') ON CONFLICT (version) DO NOTHING;
