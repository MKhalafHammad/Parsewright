# engine/tests

pytest suite for the `parsewright` package, mirroring its layout. Includes the adversarial regression suite in `adversarial/` (nullQueue, newline injection, path traversal, injected log lines, constant-value gaming, forbidden searches). PostgreSQL tests are skipped when the test database is unreachable. Synthetic data only.
