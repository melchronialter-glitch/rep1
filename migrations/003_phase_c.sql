-- =============================================================================
-- CryptoBot — Phase C schema (chain watchers: tokens, pairs)
-- =============================================================================

-- ---- Tokens -----------------------------------------------------------------
-- Every token we've ever seen on any chain. Written by the chain watchers
-- (pump.fun, Raydium, Uniswap, PancakeSwap) — including sub-threshold
-- pump.fun mints, kept for later pattern learning.
CREATE TABLE IF NOT EXISTS tokens (
    address     TEXT NOT NULL,
    chain       TEXT NOT NULL,
    symbol      TEXT,
    name        TEXT,
    venue       TEXT,
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB,
    PRIMARY KEY (chain, address)
);
CREATE INDEX IF NOT EXISTS tokens_first_seen_idx ON tokens (first_seen DESC);
CREATE INDEX IF NOT EXISTS tokens_chain_first_seen_idx ON tokens (chain, first_seen DESC);

-- ---- Pairs ------------------------------------------------------------------
-- Every LP pair / pool we've detected.
CREATE TABLE IF NOT EXISTS pairs (
    pair_address  TEXT NOT NULL,
    chain         TEXT NOT NULL,
    venue         TEXT,
    token0        TEXT,
    token1        TEXT,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chain, pair_address)
);
CREATE INDEX IF NOT EXISTS pairs_first_seen_idx ON pairs (first_seen DESC);

-- Record this migration
INSERT INTO schema_migrations (version, name)
VALUES (3, 'phase_c')
ON CONFLICT (version) DO NOTHING;
