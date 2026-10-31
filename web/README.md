# web

The Next.js + shadcn/ui interface, built around the actors (agents propose, code acts, Splunk judges, you approve): the runs board with "Needs you" pinned and a "New run" sheet (a new TA, or an update of one Parsewright promoted); the run workspace with budget meters, a "Now" banner, a clickable phase rail, each attempt's proposal, gate verdict and Splunk checks, and the live activity grouped by phase and attempt; profile review; the approval report (raw vs parsed with one colour per field and a CIM view, configuration as readable rows, and for an update a row diff against production with `local/` override flags); and a read-only TA registry. It only reads job state and the ledger (live, over server-sent events) and sends the allowed actions: upload, confirm profile, approve, reject. All logic lives in `engine/`. Conventions: [CLAUDE.md](CLAUDE.md).

## Run it

Node 24 LTS. With the engine running (`.venv/bin/parsewright serve`):

```bash
npm ci
npm run build
ENGINE_URL=http://127.0.0.1:8080 npm start   # http://localhost:3000
```

| Variable | Default | What it is |
| --- | --- | --- |
| `ENGINE_URL` | `http://127.0.0.1:8080` | Engine API, server-side only (never sent to the browser) |
| `ALLOWED_HOSTS` | `localhost:3000,127.0.0.1:3000` | Host names the UI answers to (DNS-rebinding guard) |
| `WEB_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Origins allowed to send actions (CSRF guard) |

## Safety

- The browser talks only to this app. `/api/engine/*` forwards an allowlist of engine paths server-side, refuses unknown hosts, encoded separators and cross-site actions, and adds the engine's CSRF header.
- `proxy.ts` sets a per-request CSP nonce (no `'unsafe-inline'` scripts) and refuses unknown `Host` headers on every page.
- Log text is only ever rendered as React text nodes. ESLint fails on `dangerouslySetInnerHTML`, `innerHTML`, `insertAdjacentHTML`, `document.write`, `srcDoc`, `eval` and `new Function`.

## Checks

```bash
npm run lint && npm run typecheck
npm run test:e2e            # Playwright: XSS (feed, phase view, diffs, config, update review), no diff markers, keyboard flow, deep links and back/forward, phase rail keys, live view, proxy and headers
npm audit --audit-level=moderate
```

The end-to-end tests need Playwright's Chromium (`npx playwright install chromium`) and its system libraries.
