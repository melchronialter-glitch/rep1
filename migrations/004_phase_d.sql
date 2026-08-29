-- =============================================================================
-- CryptoBot — Phase D schema (rug detector: risk_scores)
-- =============================================================================

-- ---- Risk scores --------------------------------------------------------------
-- One row per scored chain.new_pair event. This is the Phase H ML training
-- set: deterministic hard-rule scores + the raw safety report, joinable to
-- tokens/pairs by (chain, address).
CREATE TABLE IF NOT EXISTS risk_scores (
    id             UUID PRIMARY KEY,
    chain          TEXT,
    address        TEXT,
    pair_address   TEXT,
    score          INT,
    reasons        JSONB,
    safety         JSONB,
    liquidity_usd  NUMERIC,
    routed_to      TEXT,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS risk_scores_chain_address_ts_idx
    ON risk_scores (chain, address, ts DESC);

-- Record this migration
INSERT INTO schema_migrations (version, name)
VALUES (4, 'phase_d')
ON CONFLICT (version) DO NOTHING;
