-- Phase H: learning loop tables

-- rug_labels: user-provided rug/notrug labels
CREATE TABLE IF NOT EXISTS rug_labels (
    address TEXT NOT NULL,
    chain TEXT,
    label TEXT NOT NULL CHECK (label IN ('rug', 'notrug')),
    labeled_by TEXT,  -- telegram user or 'cli'
    notes TEXT,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (address, label)
);

-- rug_forensics: Claude's post-mortem analysis
CREATE TABLE IF NOT EXISTS rug_forensics (
    id UUID PRIMARY KEY,
    address TEXT NOT NULL,
    chain TEXT,
    risk_score INT,
    callers JSONB,     -- [{sender_name, calls_count}, ...]
    flags JSONB,       -- safety flags present at launch
    pattern_summary TEXT,
    raw_report TEXT,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS rug_forensics_address_idx ON rug_forensics (address);

-- ml_features: feature vectors for xgboost training
CREATE TABLE IF NOT EXISTS ml_features (
    id UUID PRIMARY KEY,
    address TEXT NOT NULL,
    chain TEXT,
    label TEXT,  -- 'rug'|'notrug'|NULL (unlabeled)
    features JSONB NOT NULL,
    score_at_detection INT,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ml_features_label_idx ON ml_features (label, ts DESC);

INSERT INTO schema_migrations (version, name) VALUES (8, 'phase_h') ON CONFLICT (version) DO NOTHING;
