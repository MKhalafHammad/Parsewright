# web

The Next.js + shadcn/ui interface: the job board with upload, the live run view, profile review and the approval report. It only reads job state and the ledger (live, over server-sent events) and sends the allowed actions: upload, confirm profile, approve, reject. All logic lives in `engine/`. Conventions: [CLAUDE.md](CLAUDE.md).

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
npm run test:e2e            # Playwright: XSS, keyboard flow, live view, proxy and headers
npm audit --audit-level=moderate
```

The end-to-end tests need Playwright's Chromium (`npx playwright install chromium`) and its system libraries.
