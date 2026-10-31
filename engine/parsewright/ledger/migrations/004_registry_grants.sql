-- The engine role may only move a TA's current version, never repoint its owner job,
-- sourcetype or names (appsec Phase 7 L4). 003 now grants exactly this; this migration fixes
-- databases that applied the first version of 003.
REVOKE UPDATE ON tas FROM parsewright_app;
GRANT UPDATE (current_version, updated_at) ON tas TO parsewright_app;
