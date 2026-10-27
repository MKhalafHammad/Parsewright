# Security policy

## Reporting a vulnerability

Please report vulnerabilities **privately**, not in a public issue, pull request or discussion.

1. Go to the repository's **Security** tab and choose **Report a vulnerability** (GitHub private vulnerability reporting).
2. Describe the issue, the affected component (engine, web, Docker setup, CI), steps to reproduce and the impact you expect.
3. Use synthetic data in your report. Do not include real secrets, real logs, real hostnames or IP addresses.

You can expect an acknowledgement within 5 working days and an update on the fix within 14 days. Please give us a reasonable time to fix the issue before disclosing it publicly.

## Supported versions

Parsewright is pre-1.0 and built during a hackathon. Only the latest commit on the `main` branch is supported; fixes are not backported.

| Version | Supported |
| --- | --- |
| `main` (latest) | Yes |
| Anything older | No |

## Never post secrets or real logs

- Never open a public issue, pull request or discussion containing API keys, Splunk tokens, passwords, `.env` contents, or real production logs.
- If you accidentally posted a secret, rotate it immediately, then report it privately as above so the content can be removed.
- Reproduce problems with the synthetic generator's logs, not with real data.

## How the project protects secrets

- `.env` is git-ignored; `.env.example` holds placeholders only.
- gitleaks runs on every commit (pre-commit) and over the full git history in CI.
- Runtime guardrails are described in [docs/design.md](docs/design.md), section "Guardrails and security", and the threat model in [docs/threat-model.md](docs/threat-model.md).
