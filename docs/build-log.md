# Build log

One entry per completed phase, appended at the end of the phase (see CLAUDE.md, "Build log and demo moments"). Phases and status: [build-plan.md](build-plan.md).

## 2026-10-27 — Phase 0: Repository foundation

**Built**
- Project rules and docs: `CLAUDE.md` (root, `engine/`, `web/`), README, SECURITY.md, MIT LICENSE, `docs/design.md`, threat-model skeleton, six subagent definitions in `.claude/agents/`.
- Public-repo safety:
  - `.gitignore`;
  - `.env.example` with placeholders only;
  - `.claude/settings.json` with attribution off and deny rules;
  - pre-commit with gitleaks, file checks and ruff;
  - a commit-msg hook that rejects AI attribution (`scripts/check_commit_msg.py`).
- Tooling:
  - `Makefile` (`setup`, `up`, `down`, `logs`, `test`, `lint`, `security`);
  - `docker-compose.yml` with Splunk Enterprise 10.6.1 and PostgreSQL 17, where only Splunk Web is published, on 127.0.0.1;
  - CI on pull requests: lint, tests, bandit, semgrep, pip-audit, npm audit, gitleaks over full history.
- Empty package skeleton `engine/parsewright/`, one README per module.

**Test results**
- `make test`: 8/8 passed (commit-msg hook). `make lint`: all hooks passed.
- The hook was also tested end to end in a scratch repo:
  - `Co-Authored-By: Claude` was rejected and no commit was created;
  - an editor-style message with comment lines was accepted.
- CI:
  - the first two runs failed. `splunk-sdk>=3.0` needs Python 3.13, fixed in `42499d1`. Then semgrep blocked mutable GitHub Action tags, fixed by pinning to commit SHAs in `02a1261`.
  - run 4 passed on the final head;
  - merged as PR #1 (`915edcc`).

**Cut or deferred**
- `engine/` and `web/` Dockerfiles, and the Next.js scaffold: the services sit behind the Compose `app` profile until there is code to run.
- semgrep could not run in the build environment (network policy), so its first real run was in CI.
- Docker images pinned by tag, not digest; Python dependencies have lower bounds only, without hashes. Both are tracked as T9.3 and T9.6 in the threat model.
- CI triggers changed from every push to pull requests only (`54f3da4`).
