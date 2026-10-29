// Client-side calls go only to this app's own /api/engine proxy. Every call carries the
// custom header the proxy and the engine require for state changes (CSRF, threat T8.3).
export const CSRF_HEADER = "X-Parsewright";

export type Job = {
  job: string;
  status: string;
  source_key: string;
  form: Record<string, unknown>;
  tokens: number;
  created_at: string;
  updated_at: string;
};

export type Highlight = { start: number; end: number; field: string };
export type ReportEvent = { time: number; raw: string; fields: Record<string, string>; highlights: Highlight[] };
export type Score = { model: string; passed: number; mapped: number; in_source: number; not_in_source: string[]; line: string };
export type UpdateReview = {
  app: string;
  version_from: string;
  version_to: string;
  patched: string[];
  diff: Record<string, string>;
  overrides: string[];
  notes: string[];
  old_event: ReportEvent | null;
  rollback: string;
};
export type Report = {
  events: ReportEvent[];
  mapping: { cim_field: string; kind: string; from: string; example: string }[];
  scores: Score[];
  confs: Record<string, string>;
  holdout: { learned_from: number; validated_on: number };
  update?: UpdateReview;
};
export type TA = { app: string; sourcetype: string; current_version: string; versions: string[] };
export type Profile = {
  format: string;
  vendor: string;
  product: string;
  sourcetype: string;
  timestamp_example: string;
  timezone_in_timestamp: boolean;
  timezone_hint: string | null;
  event_categories: string[];
  fields: { name: string; coverage: number }[];
  cim_targets: string[];
};
export type RunDetail = Job & {
  profile: Profile | null;
  stage_index: number | null;
  record: {
    app?: string;
    test_app?: string;
    sourcetype?: string;
    sha256_test?: string;
    approved_sha256?: string;
    sha256_promoted?: string;
    smoke?: string;
    report?: Report;
    kind?: string;
    update_of?: string;
    version_from?: string;
    version_to?: string;
    result?: string;
  };
};
export type LedgerEvent = { id: number; at: string; event: string; data: Record<string, unknown> };

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/engine${path}`, {
    ...init,
    headers: { ...(init.headers ?? {}), [CSRF_HEADER]: "1" },
    cache: "no-store",
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof body?.detail === "string" ? body.detail : `request failed (${res.status})`);
  }
  return body as T;
}

export const postJson = <T,>(path: string, data: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(data), headers: { "Content-Type": "application/json" } });
