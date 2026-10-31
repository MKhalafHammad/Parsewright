# web/ conventions (Next.js + shadcn/ui)

Root rules in [../CLAUDE.md](../CLAUDE.md) apply. Design: [../docs/design.md](../docs/design.md), section "Platform and UI".

Status: built (Phase 6, redesigned Oct 30): runs board, run workspace (phase rail, attempts, live activity), profile review, approval report, TA registry; the /api/engine proxy and proxy.ts (Host allowlist, CSP nonce).

## Language and tooling
- TypeScript (strict), Next.js App Router, shadcn/ui components on Tailwind.
- Use shadcn/ui components before writing custom ones.
- ESLint and Prettier; `npm audit` runs in `make security` once `package-lock.json` exists.
- Commit `package-lock.json`; install with `npm ci`.

## Architecture
- The UI holds no business logic. It reads job state and ledger events from FastAPI (server-sent events) and sends only these actions: start run, confirm profile, approve, reject, correct a mapping.
- The engine URL comes from server-side environment variables. No secrets in client code or `NEXT_PUBLIC_*` variables.

## Safety conventions
- Log text is rendered only as escaped text. Highlights in the raw vs parsed view are built as React elements from offsets, never as HTML strings.
- Never use `dangerouslySetInnerHTML`, `eval` or raw HTML from logs or API responses.
- High-risk approvals (routing on shared stanzas) require a second confirmation.
- Accessible by default: labelled controls, keyboard navigation, visible focus.

## UI conventions
- Actors are defined once in `lib/actors.ts` and shown with `components/actors/actor.tsx`; never invent another icon or colour for an agent.
- The UI reads the engine's event labels (`stage`, `attempt`, `visit`, `actor`, `kind`, `detail`) through `lib/events.ts`; it never parses the text line.
- Colours come from the tokens in `app/globals.css`: one dark glass theme (`.glass` panels, `.bubble` pills, `.btn-primary`), every text and status pair at WCAG AA. Status is always icon + word + colour.
- Configuration is shown as the .conf file in an editor-style pane (line numbers, syntax colours, an "Explain settings" toggle); diffs stay as rows.
- Runs recorded before the event labels are read by `lib/legacy.ts` (display only); never extend it for new events, which carry their own labels.
- Diffs are rows (`components/run/config-view.tsx`): no `---`, `+++`, `@@` or leading `+`/`-`; `e2e/xss.spec.ts` asserts it.
