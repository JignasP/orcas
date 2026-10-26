CREATE TABLE IF NOT EXISTS runs (
    run_id UUID PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'escalated', 'failed')),
    payload JSONB NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    result JSONB,
    error TEXT
);

CREATE TABLE IF NOT EXISTS run_events (
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent TEXT NOT NULL,
    step TEXT NOT NULL,
    kind TEXT NOT NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    tokens JSONB NOT NULL DEFAULT '{}'::jsonb,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS quarantine (
    quarantine_id UUID PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_payload JSONB NOT NULL,
    reason TEXT NOT NULL,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS eval_scores (
    score_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS run_events_by_time ON run_events (run_id, ts);
CREATE INDEX IF NOT EXISTS quarantine_by_time ON quarantine (received_at DESC);
