-- TA registry (design "Parser updates"): every TA Parsewright promoted, with all its versions.
-- A version points at the job that built it: that job's samples and manifest (jobs.sample_path)
-- are the regression set for every later update, and its promoted package stays in the job's
-- runs folder for an exact rollback.

CREATE TABLE IF NOT EXISTS tas (
    app              text PRIMARY KEY
                     CHECK (app ~ '^TA-parsewright-[a-z0-9_:-]+-[a-z0-9_:-]+$'
                            AND app !~ '__test_'),
    sourcetype       text NOT NULL CHECK (sourcetype ~ '^[a-z0-9_:-]+$'),
    vendor           text NOT NULL,
    product          text NOT NULL,
    -- the job whose id prefixes the TA's transform and eventtype names (parsewright_<job>_...)
    owner_job        text NOT NULL REFERENCES jobs (id),
    current_version  text NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ta_versions (
    app         text NOT NULL REFERENCES tas (app),
    version     text NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    job_id      text NOT NULL REFERENCES jobs (id),
    sha256      text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (app, version)
);

-- Registry history: registrations, updates and rollbacks.
CREATE TABLE IF NOT EXISTS ta_events (
    id     bigserial PRIMARY KEY,
    app    text NOT NULL REFERENCES tas (app),
    at     timestamptz NOT NULL DEFAULT now(),
    event  text NOT NULL,
    data   jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Versions and history are append-only, like the ledger: a rollback reinstalls a version, it
-- never rewrites one.
DROP TRIGGER IF EXISTS ta_versions_no_update ON ta_versions;
CREATE TRIGGER ta_versions_no_update BEFORE UPDATE OR DELETE ON ta_versions
    FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS ta_versions_no_truncate ON ta_versions;
CREATE TRIGGER ta_versions_no_truncate BEFORE TRUNCATE ON ta_versions
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS ta_events_no_update ON ta_events;
CREATE TRIGGER ta_events_no_update BEFORE UPDATE OR DELETE ON ta_events
    FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS ta_events_no_truncate ON ta_events;
CREATE TRIGGER ta_events_no_truncate BEFORE TRUNCATE ON ta_events
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_append_only();

-- Backfill the TAs promoted before the registry existed (one per app: the latest).
INSERT INTO tas (app, sourcetype, vendor, product, owner_job, current_version)
SELECT DISTINCT ON (record->>'app')
       record->>'app', record->>'sourcetype', record->>'vendor', record->>'product', id, '1.0.0'
FROM jobs
WHERE status = 'done' AND record ? 'sha256_promoted' AND record ? 'app'
ORDER BY record->>'app', updated_at DESC
ON CONFLICT (app) DO NOTHING;
INSERT INTO ta_versions (app, version, job_id, sha256)
SELECT t.app, '1.0.0', t.owner_job, j.record->>'sha256_promoted'
FROM tas t JOIN jobs j ON j.id = t.owner_job
ON CONFLICT DO NOTHING;
INSERT INTO ta_events (app, event, data)
SELECT app, 'registered', jsonb_build_object('version', current_version, 'backfill', true)
FROM tas WHERE NOT EXISTS (SELECT 1 FROM ta_events e WHERE e.app = tas.app);

GRANT SELECT, INSERT ON tas TO parsewright_app;
GRANT UPDATE (current_version, updated_at) ON tas TO parsewright_app;
GRANT SELECT, INSERT ON ta_versions, ta_events TO parsewright_app;
GRANT USAGE ON SEQUENCE ta_events_id_seq TO parsewright_app;
