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

export const sse = (events: object[]) =>
  events.map((e) => `id: ${(e as { id: number }).id}\nevent: ledger\ndata: ${JSON.stringify(e)}\n\n`).join("");

export async function mockRun(page: Page, body: object, stream: object[] = []) {
  await page.route("**/api/engine/runs/e2e00001", (r: Route) => r.fulfill({ json: body }));
  await page.route("**/api/engine/runs/e2e00001/stream", (r: Route) =>
    r.fulfill({ status: 200, contentType: "text/event-stream", body: sse(stream) }),
  );
}
