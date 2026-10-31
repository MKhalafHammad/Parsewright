import type { Page, Route } from "@playwright/test";

export const XSS = '<script>alert(1)</script><img src=x onerror="alert(2)">';

export function run(status: string, extra: Record<string, unknown> = {}) {
  const raw = `2026-10-20T08:00:46Z user=alice msg=${XSS}`;
  return {
    job: "e2e00001",
    status,
    source_key: "acme:vpn",
    form: {},
    tokens: 1234,
    created_at: "2026-10-28T10:00:00Z",
    updated_at: "2026-10-28T10:00:05Z",
    stage_index: 3,
    profile: {
      format: "kv", vendor: "acme", product: "vpn", sourcetype: "acme:vpn",
      timestamp_example: "2026-10-20T08:00:46Z", timezone_in_timestamp: true, timezone_hint: null,
      event_categories: ["auth"], fields: [{ name: "user", coverage: 1 }, { name: "msg", coverage: 1 }],
      cim_targets: ["Authentication"],
    },
    record: {
      sha256_test: "a".repeat(64),
      test_app: "TA-parsewright-acme-vpn__test_e2e00001",
      report: {
        events: [{
          time: 1792483246, raw,
          fields: { user: "alice", msg: XSS },
          highlights: [
            { start: raw.indexOf("alice"), end: raw.indexOf("alice") + 5, field: "user" },
            { start: raw.indexOf("<script>"), end: raw.length, field: "msg" },
          ],
        }],
        mapping: [{ cim_field: "user", kind: "FIELDALIAS", from: "user", example: "alice" }],
        scores: [{ model: "Authentication", passed: 4, mapped: 4, in_source: 4, not_in_source: ["app"], line: "" }],
        confs: { "default/props.conf": `[acme:vpn__test_e2e00001]\nKV_MODE = auto\n# ${XSS}` },
        holdout: { learned_from: 200, validated_on: 300 },
      },
    },
    ...extra,
  };
}

// A labelled ledger, as orchestrator/events.py writes it: synthetic, with log-derived text
// (the XSS string) in reasons, evidence, examples and proposals.
type Log = { stage?: string | null; attempt?: number | null; visit?: number | null; actor: string; kind: string; line?: string; detail?: Record<string, unknown> };
let at = 0;
const log = (id: number, d: Log) => ({
  id,
  at: new Date(Date.UTC(2026, 9, 28, 10, 0, at++)).toISOString(),
  event: "log",
  data: { stage: null, attempt: null, visit: null, line: `${d.kind} line ${id}`, detail: {}, ...d },
});
const att = (stage: string, attempt: number) => ({ stage, attempt, visit: 1 });
const pass = (name: string) => ({ checks: [{ name, passed: true, expected: 300, actual: 300, examples: [] }] });

export const LEDGER = [
  log(1, { actor: "orchestrator", kind: "start", detail: { job_type: "build", file: "acme_vpn.log", events: 300, max_attempts: 5, token_ceiling: 200000, wall_clock_s: 900 } }),
  log(2, { stage: "profile", actor: "profiler", kind: "proposal", detail: { profile: { format: "kv", sourcetype: "acme:vpn", fields: [{ name: "user" }, { name: "msg" }] } } }),
  log(3, { stage: "profile", actor: "human", kind: "human_wait", detail: { for: "profile_review" } }),
  { id: 4, at: "2026-10-28T10:00:04Z", event: "state", data: { from: ["profile_review"], to: "queued" } },
  log(5, { ...att("index-time", 1), actor: "index_time", kind: "start", line: "index-time attempt 1: sourcetype acme:vpn__test_e2e00001_a1", detail: { max_attempts: 5 } }),
  log(6, { ...att("index-time", 1), actor: "index_time", kind: "proposal", detail: { settings: { LINE_BREAKER: "([\\r\\n]+)", SHOULD_LINEMERGE: "false", TIME_FORMAT: "%Y-%m-%dT%H:%M:%SZ" } } }),
  log(7, { ...att("index-time", 1), actor: "orchestrator", kind: "deploy", detail: { app: "TA-parsewright-acme-vpn__test_e2e00001", version: "0.0.1", sourcetype: "acme:vpn__test_e2e00001_a1" } }),
  log(8, { ...att("index-time", 1), actor: "orchestrator", kind: "ingest", detail: { sets: [{ source: "acme_vpn.log", events: 300 }] } }),
  log(9, { ...att("index-time", 1), actor: "validator", kind: "check_pass", detail: pass("event count") }),
  log(10, { ...att("index-time", 1), actor: "validator", kind: "check_pass" }),
  log(11, { ...att("extraction", 1), actor: "extraction", kind: "start", detail: { max_attempts: 5 } }),
  log(12, { ...att("extraction", 1), actor: "extraction", kind: "proposal", detail: { settings: { props: { KV_MODE: "auto" } } } }),
  log(13, { ...att("extraction", 1), actor: "orchestrator", kind: "deploy", detail: { version: "0.0.2" } }),
  log(14, { ...att("extraction", 1), actor: "validator", kind: "check_fail", detail: { checks: [{ name: "field values: msg", passed: false, expected: "msg on every event", actual: "missing on 300", examples: [`msg=${XSS}`] }] } }),
  log(15, { ...att("extraction", 1), actor: "orchestrator", kind: "evidence", detail: { to: "extraction", text: `msg is missing: ${XSS}` } }),
  log(16, { ...att("extraction", 2), actor: "extraction", kind: "start", detail: { max_attempts: 5 } }),
  log(17, { ...att("extraction", 2), actor: "extraction", kind: "proposal", detail: { rationale: `KV_MODE misses ${XSS}`, settings: { props: { KV_MODE: "none", "EXTRACT-msg": "msg=(?<msg>.+)$" } } } }),
  log(18, { ...att("extraction", 2), actor: "orchestrator", kind: "deploy", detail: { version: "0.0.3" } }),
  log(19, { ...att("extraction", 2), actor: "validator", kind: "check_pass", detail: pass("field values: msg") }),
  log(20, { ...att("extraction", 2), actor: "validator", kind: "check_pass" }),
  log(21, { ...att("cim", 1), actor: "cim_mapper", kind: "start", detail: { max_attempts: 5 } }),
  log(22, { ...att("cim", 1), actor: "gate", kind: "guardrail_block", detail: { reason: `EVAL-action reads ${XSS}`, settings: {} } }),
  log(23, { ...att("cim", 1), actor: "orchestrator", kind: "evidence", detail: { to: "cim", text: "blocked" } }),
  log(24, { ...att("cim", 2), actor: "cim_mapper", kind: "start", detail: { max_attempts: 5 } }),
  log(25, { ...att("cim", 2), actor: "cim_mapper", kind: "proposal", detail: { settings: { props: { "FIELDALIAS-user": "user AS user" }, eventtypes: { acme_vpn_auth: { search: "sourcetype=acme:vpn" } } } } }),
  log(26, { ...att("cim", 2), actor: "orchestrator", kind: "deploy", detail: { version: "0.0.5" } }),
  log(27, { ...att("cim", 2), actor: "validator", kind: "check_pass", detail: pass("Authentication required fields") }),
  log(28, { ...att("cim", 2), actor: "validator", kind: "check_pass" }),
  log(29, { actor: "validator", kind: "info", detail: { learned_from: 200, validated_on: 300 } }),
  log(30, { actor: "validator", kind: "info", detail: { score: { model: "Authentication", passed: 4, in_source: 4 } } }),
  log(31, { actor: "human", kind: "human_wait", detail: { for: "approval", sha256: "a".repeat(64) } }),
];

export const sse = (events: object[]) =>
  events.map((e) => `id: ${(e as { id: number }).id}\nevent: ledger\ndata: ${JSON.stringify(e)}\n\n`).join("");

export async function mockRun(page: Page, body: object, stream: object[] = []) {
  await page.route("**/api/engine/runs/e2e00001", (r: Route) => r.fulfill({ json: body }));
  await page.route("**/api/engine/runs/e2e00001/stream", (r: Route) =>
    r.fulfill({ status: 200, contentType: "text/event-stream", body: sse(stream) }),
  );
}

/** No unified-diff markers anywhere in a diff view's text. */
export const DIFF_MARKERS = /(^|\n)\s*(\+|-)|---|\+\+\+|@@/;
