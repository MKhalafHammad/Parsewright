// Typed ledger events. The engine labels every log event with its stage, attempt, visit,
// actor, kind and structured detail (orchestrator/events.py); this file only turns those
// labels into display data. It never parses the text line, which is kept for the CLI and
// shown verbatim in the technical detail. Everything in `detail` is untrusted (log-derived).
import { actor, type ActorId } from "@/lib/actors";
import type { LedgerEvent } from "@/lib/api";
import { STATUS_TEXT } from "@/lib/status";

export type Stage = "profile" | "index-time" | "extraction" | "cim" | "diagnose" | "regression" | "promotion";
export type Kind =
  | "start"
  | "proposal"
  | "guardrail_block"
  | "deploy"
  | "ingest"
  | "check_pass"
  | "check_fail"
  | "evidence"
  | "backtrack"
  | "human_wait"
  | "human_action"
  | "budget"
  | "info";
export type PhaseId =
  | "profile"
  | "profile_review"
  | "routing"
  | "diagnose"
  | "index-time"
  | "extraction"
  | "cim"
  | "regression"
  | "approval"
  | "promoted";
export type Tone = "good" | "bad" | "warn" | "run" | "neutral";

export type Entry = {
  id: number;
  at: string;
  stage: Stage | null;
  phase: PhaseId | null;
  attempt: number | null;
  visit: number | null;
  actor: ActorId;
  kind: Kind;
  tone: Tone;
  line: string;
  detail: Record<string, unknown>;
  sentence: string;
};

export type Check = { name: string; passed: boolean; expected: unknown; actual: unknown; examples: string[] };

const STAGES = new Set<string>(["profile", "index-time", "extraction", "cim", "diagnose", "regression", "promotion"]);
const KINDS = new Set<string>([
  "start", "proposal", "guardrail_block", "deploy", "ingest", "check_pass", "check_fail",
  "evidence", "backtrack", "human_wait", "human_action", "budget", "info",
]);

// No prototype: a stage name from data such as "constructor" finds nothing.
export const STAGE_LABEL: Record<string, string> = Object.assign(Object.create(null), {
  profile: "Profile",
  profile_review: "Profile review",
  routing: "Routing",
  diagnose: "Diagnose",
  "index-time": "Index-time",
  extraction: "Extraction",
  cim: "CIM mapping",
  regression: "Regression",
  approval: "Approval",
  promoted: "Promoted",
  promotion: "Promotion",
});

/** The AI agent that owns a build stage. */
export const STAGE_AGENT: Record<string, ActorId> = {
  profile: "profiler",
  "index-time": "index_time",
  extraction: "extraction",
  cim: "cim_mapper",
};

// --- small readers for untrusted JSON --------------------------------------------------

export const str = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v));
export const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
export const obj = (v: unknown): Record<string, unknown> =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
export const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const firstLine = (s: string) => s.trim().split("\n")[0] ?? "";
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The sentence for display next to the actor's name: "Extraction started…" -> "started…". */
export function said(e: Entry): string {
  const name = actor(e.actor).name;
  return e.sentence.startsWith(`${name} `) ? e.sentence.slice(name.length + 1) : e.sentence;
}

export function checksOf(e: Entry): Check[] | null {
  if (!Array.isArray(e.detail.checks)) return null;
  return e.detail.checks.map((c) => {
    const o = obj(c);
    return { name: str(o.name), passed: o.passed === true, expected: o.expected, actual: o.actual, examples: arr(o.examples).map(str).slice(0, 3) };
  });
}

/** Number of settings in a proposal, whatever its shape (flat props, or per-conf stanzas). */
function settingCount(settings: unknown): number {
  const s = obj(settings);
  let n = 0;
  for (const v of Object.values(s)) {
    if (v && typeof v === "object") n += settingCount(v) || 1;
    else n += 1;
  }
  return n;
}

function stageName(s: unknown): string {
  return STAGE_LABEL[str(s)] ?? str(s);
}

// --- one ledger row -> one display entry -------------------------------------------------

function sentence(e: Omit<Entry, "sentence" | "tone" | "phase">): string {
  const who = actor(e.actor).name;
  const d = e.detail;
  const stage = e.stage ? stageName(e.stage) : "";
  switch (e.kind) {
    case "start": {
      if (e.stage === null && d.file !== undefined)
        return `${d.job_type === "update" ? "Update job" : "Job"} started: ${str(d.file)}, ${num(d.events) ?? "?"} events`;
      if (e.stage === "diagnose") return "Orchestrator installed the production add-on as it is, to see what the new samples break (no AI)";
      if (e.stage === "regression") return "Orchestrator is testing the final package on every registered version's samples";
      if (e.attempt !== null) {
        const max = num(d.max_attempts);
        return `${who} started attempt ${e.attempt}${max ? ` of ${max}` : ""}`;
      }
      break;
    }
    case "proposal": {
      if (d.profile) {
        const p = obj(d.profile);
        return `Profiler described the log: ${str(p.format)} format, ${plural(arr(p.fields).length, "field")}, sourcetype ${str(p.sourcetype)}`;
      }
      return `${who} proposed ${plural(settingCount(d.settings), "setting")}; the guardrail gate let them through`;
    }
    case "guardrail_block":
      return d.type === "bad_output"
        ? `The agent's answer was unusable after retries: ${firstLine(str(d.reason))}`
        : `Guardrail gate blocked the proposal: ${firstLine(str(d.reason))}`;
    case "deploy":
      if (d.from_version !== undefined) return `Orchestrator rolled ${str(d.app)} back from ${str(d.from_version)} to ${str(d.version)}`;
      if (d.from_sha256 !== undefined) return `Orchestrator installed ${str(d.app)} ${str(d.version)} under its real name`;
      return `Orchestrator installed test build ${str(d.version)} in Splunk`;
    case "ingest": {
      const sets = arr(d.sets).map(obj);
      const total = sets.reduce((n, s) => n + (num(s.events) ?? 0), 0);
      return `Orchestrator sent ${plural(total, "sample event")} into Splunk${sets.length > 1 ? ` from ${sets.length} sample sets` : ""}`;
    }
    case "check_pass":
    case "check_fail": {
      const checks = checksOf(e as Entry);
      const set = d.sample_set ? ` on ${str(d.sample_set)}` : "";
      if (checks) {
        const failed = checks.filter((c) => !c.passed).length;
        return failed
          ? `Splunk checks: ${failed} of ${checks.length} failed${set}`
          : `Splunk checks: all ${checks.length} passed${set}`;
      }
      if (d.smoke !== undefined) return `Smoke test: ${firstLine(str(d.smoke))}`;
      if (e.stage === "regression") return e.kind === "check_pass" ? "Regression passed" : "The final package failed the regression checks";
      if (e.stage && e.attempt !== null) return `${stage} ${e.kind === "check_pass" ? "passed" : "failed"} on attempt ${e.attempt}`;
      if (e.stage && e.attempt === null && e.kind === "check_pass" && e.stage !== "diagnose")
        return `${stage} already passes on every sample set: not patched`;
      break;
    }
    case "evidence":
      if (d.to !== undefined) return `Orchestrator sent the results back to ${actor(STAGE_AGENT[str(d.to)]).name} for its next attempt`;
      if (Array.isArray(d.stages)) return `Drift report: ${d.stages.map(stageName).join(", ")} fail on the new samples`;
      break;
    case "backtrack":
      return `${stageName(d.from)} sent this back to ${stageName(d.to)} because: ${firstLine(str(d.because)) || "it ran out of attempts"}`;
    case "human_wait":
      return d.for === "approval" ? "Waiting for you to approve or reject the package" : "Waiting for you to review the profile";
    case "budget":
      return d.reason === "attempts" ? `${stage || "This phase"} ran out of attempts` : firstLine(e.line);
    case "info":
      if (d.score) {
        const s = obj(d.score);
        return `CIM ${str(s.model)}: ${num(s.passed) ?? 0} of ${num(s.in_source) ?? 0} required fields pass`;
      }
      if (d.learned_from !== undefined)
        return `Holdout: learned from ${num(d.learned_from)} lines, passed on the full file (${num(d.validated_on)} events)`;
      if (d.checked !== undefined) return `Validator checked ${stageName(d.checked)} on every sample set`;
      break;
  }
  return firstLine(e.line);
}

function toneOf(kind: Kind, detail: Record<string, unknown>): Tone {
  if (kind === "check_pass") return "good";
  if (kind === "check_fail" || kind === "guardrail_block" || kind === "budget") return "bad";
  if (kind === "backtrack" || kind === "human_wait") return "warn";
  if (kind === "info" && detail.score) {
    const s = obj(detail.score);
    return num(s.passed) === num(s.in_source) ? "good" : "bad";
  }
  return "neutral";
}

function phaseOf(stage: Stage | null, kind: Kind, actorId: ActorId, detail: Record<string, unknown>): PhaseId | null {
  if (stage === "profile") return actorId === "profiler" ? "profile" : "profile_review";
  if (stage === "promotion") return "promoted";
  if (stage) return stage;
  if (kind === "human_wait" && detail.for === "approval") return "approval";
  if (detail.score || detail.learned_from !== undefined) return "approval";
  if (actorId === "router") return "routing";
  return null;
}

/** Ledger rows that are not log lines: queue and state changes, written by the engine. */
function fromLedger(e: LedgerEvent): Pick<Entry, "actor" | "kind" | "stage" | "sentence" | "phase" | "tone"> {
  const d = e.data;
  const base = { stage: null, phase: null, tone: "neutral" as Tone };
  if (e.event === "queued") return { ...base, actor: "orchestrator", kind: "info", sentence: "Job queued" };
  if (e.event === "claimed") return { ...base, actor: "orchestrator", kind: "info", sentence: "A worker picked up the job" };
  if (e.event === "error")
    return { ...base, actor: "orchestrator", kind: "info", tone: "bad", sentence: `The worker stopped with an error: ${str(d.error)}` };
  if (e.event === "state") {
    const to = str(d.to);
    const from = arr(d.from).map(str);
    if (to === "approved") return { ...base, phase: "approval", actor: "human", kind: "human_action", tone: "good", sentence: "You approved the package" };
    if (to === "rejected") return { ...base, phase: "approval", actor: "human", kind: "human_action", tone: "bad", sentence: "You rejected the run" };
    if (from.includes("profile_review") && to === "queued")
      return { ...base, stage: "profile", phase: "profile_review", actor: "human", kind: "human_action", sentence: "You confirmed the profile" };
    return { ...base, actor: "orchestrator", kind: "info", sentence: `Status: ${STATUS_TEXT[to] ?? to}` };
  }
  return { ...base, actor: "orchestrator", kind: "info", sentence: e.event };
}

export function toEntry(e: LedgerEvent): Entry {
  const d = obj(e.data);
  const at = String(e.at);
  if (e.event !== "log") {
    return { id: e.id, at, attempt: null, visit: null, line: "", detail: d, ...fromLedger(e) };
  }
  // Events written before the labels existed have only a line: a run-level info entry.
  const stage = STAGES.has(str(d.stage)) ? (d.stage as Stage) : null;
  const kind = KINDS.has(str(d.kind)) ? (d.kind as Kind) : "info";
  const base = {
    id: e.id,
    at,
    stage,
    attempt: num(d.attempt),
    visit: num(d.visit),
    actor: actor(d.actor).id,
    kind,
    line: str(d.line),
    detail: obj(d.detail),
  };
  return { ...base, phase: phaseOf(stage, kind, base.actor, base.detail), tone: toneOf(kind, base.detail), sentence: sentence(base) };
}

// --- grouping (display only) -------------------------------------------------------------

export type AttemptGroup = { n: number; visit: number | null; attempt: number | null; entries: Entry[] };
export type FeedSection = { key: string; phase: PhaseId | null; visit: number | null; groups: AttemptGroup[] };

/** Consecutive entries of the same phase and visit form a section; inside, one group per attempt. */
export function feedSections(entries: Entry[]): FeedSection[] {
  const out: FeedSection[] = [];
  for (const e of entries) {
    let sec = out[out.length - 1];
    if (!sec || sec.phase !== e.phase || (e.visit !== null && sec.visit !== null && sec.visit !== e.visit)) {
      sec = { key: `s${e.id}`, phase: e.phase, visit: e.visit, groups: [] };
      out.push(sec);
    }
    if (sec.visit === null) sec.visit = e.visit;
    let g = sec.groups[sec.groups.length - 1];
    if (!g || g.attempt !== e.attempt) {
      g = { n: 0, visit: e.visit, attempt: e.attempt, entries: [] };
      sec.groups.push(g);
    }
    g.entries.push(e);
  }
  return out;
}

/** A phase's attempts in order, numbered 1..n across visits (the deep-link number). */
export function attemptsOf(entries: Entry[], phase: PhaseId): { attempts: AttemptGroup[]; phaseLevel: Entry[] } {
  const attempts: AttemptGroup[] = [];
  const phaseLevel: Entry[] = [];
  const index = new Map<string, AttemptGroup>();
  for (const e of entries) {
    if (e.phase !== phase) continue;
    if (e.attempt === null) {
      phaseLevel.push(e);
      continue;
    }
    const key = `${e.visit ?? 1}-${e.attempt}`;
    let g = index.get(key);
    if (!g) {
      g = { n: attempts.length + 1, visit: e.visit, attempt: e.attempt, entries: [] };
      index.set(key, g);
      attempts.push(g);
    }
    g.entries.push(e);
  }
  return { attempts, phaseLevel };
}

/** The settings each attempt proposed, for the attempt N-1 -> N diff. */
export function proposalOf(g: AttemptGroup | undefined): Record<string, unknown> | null {
  const p = g?.entries.find((e) => e.kind === "proposal");
  return p ? obj(p.detail.settings) : null;
}

export function jobStart(entries: Entry[]): Entry | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i]!;
    if (e.kind === "start" && e.stage === null && e.detail.file !== undefined) return e;
  }
  return undefined;
}
