-- Jobs (the queue and each run's state) and the append-only ledger.
-- State transitions are UPDATE ... WHERE status = '<expected>' with the row count checked.

CREATE TABLE IF NOT EXISTS jobs (
    id              text PRIMARY KEY CHECK (id ~ '^[a-z0-9]{4,16}$'),
    status          text NOT NULL,
    source_key      text NOT NULL,
    content_sha256  text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    sample_path     text NOT NULL,
    form            jsonb NOT NULL DEFAULT '{}'::jsonb,
    state           jsonb NOT NULL DEFAULT '{}'::jsonb,   -- checkpoint: profile, stage confs
    record          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- approval and promotion record
    worker_id       text,
    lease_until     timestamptz,
    tokens          bigint NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Duplicate prevention at intake: one active job per content hash and per source key.
CREATE UNIQUE INDEX IF NOT EXISTS jobs_active_content
    ON jobs (content_sha256) WHERE status NOT IN ('rejected', 'stage_failed', 'error');
CREATE UNIQUE INDEX IF NOT EXISTS jobs_active_source
    ON jobs (source_key) WHERE status NOT IN ('rejected', 'stage_failed', 'error', 'done');
CREATE INDEX IF NOT EXISTS jobs_claimable ON jobs (status, lease_until);

CREATE TABLE IF NOT EXISTS ledger (
    id      bigserial PRIMARY KEY,
    job_id  text NOT NULL REFERENCES jobs (id),
    at      timestamptz NOT NULL DEFAULT now(),
    event   text NOT NULL,
    data    jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ledger_job ON ledger (job_id, id);

-- Append-only: UPDATE, DELETE and TRUNCATE on the ledger are refused.
CREATE OR REPLACE FUNCTION ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'the ledger is append-only (% refused)', TG_OP;
END $$;
DROP TRIGGER IF EXISTS ledger_no_update ON ledger;
CREATE TRIGGER ledger_no_update BEFORE UPDATE OR DELETE ON ledger
    FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS ledger_no_truncate ON ledger;
CREATE TRIGGER ledger_no_truncate BEFORE TRUNCATE ON ledger
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_append_only();

-- Every new ledger row wakes the server-sent event stream.
CREATE OR REPLACE FUNCTION ledger_notify() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('ledger', NEW.job_id || ':' || NEW.id);
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ledger_notify ON ledger;
CREATE TRIGGER ledger_notify AFTER INSERT ON ledger
    FOR EACH ROW EXECUTE FUNCTION ledger_notify();

-- Daily model token use across all jobs, for the global daily budget.
CREATE TABLE IF NOT EXISTS usage (
    day     date PRIMARY KEY,
    tokens  bigint NOT NULL DEFAULT 0
);

-- Operator switches: the kill switch stops claims and model calls.
CREATE TABLE IF NOT EXISTS settings (
    key    text PRIMARY KEY,
    value  jsonb NOT NULL
);
INSERT INTO settings (key, value) VALUES ('kill_switch', 'false'::jsonb) ON CONFLICT DO NOTHING;
