# web/ conventions (Next.js + shadcn/ui)

Root rules in [../CLAUDE.md](../CLAUDE.md) apply. Design: [../docs/design.md](../docs/design.md), section "Platform and UI".

Status: planned. The UI is built after the engine loop works end to end.

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
