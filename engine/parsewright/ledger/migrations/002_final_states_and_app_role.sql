-- Duplicate detection: every final status frees the content hash and the source key
-- (smoke_failed and promotion_failed were missing, blocking re-uploads forever).
DROP INDEX IF EXISTS jobs_active_content;
DROP INDEX IF EXISTS jobs_active_source;
CREATE UNIQUE INDEX jobs_active_content ON jobs (content_sha256)
    WHERE status NOT IN ('rejected', 'stage_failed', 'error', 'smoke_failed', 'promotion_failed');
CREATE UNIQUE INDEX jobs_active_source ON jobs (source_key)
    WHERE status NOT IN ('rejected', 'stage_failed', 'error', 'done', 'smoke_failed',
                         'promotion_failed');

-- The engine's own role: no ownership, so it cannot disable the ledger's triggers, TRUNCATE,
-- or ALTER anything; the ledger is SELECT and INSERT only (append-only even against the engine).
-- Its password is set by `parsewright migrate` from POSTGRES_APP_PASSWORD.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'parsewright_app') THEN
        CREATE ROLE parsewright_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO parsewright_app;
GRANT SELECT, INSERT ON ledger TO parsewright_app;
GRANT USAGE ON SEQUENCE ledger_id_seq TO parsewright_app;
GRANT SELECT, INSERT, UPDATE ON jobs, usage, settings TO parsewright_app;
