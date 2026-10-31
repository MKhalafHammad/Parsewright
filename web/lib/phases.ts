// The phase rail and the "Now" banner, read from the job status and the labelled events.
// Display only: the engine's state machine decides; this just says where the run is.
import type { ActorId } from "@/lib/actors";
import type { RunDetail } from "@/lib/api";
import { attemptsOf, jobStart, num, STAGE_AGENT, STAGE_LABEL, type Entry, type PhaseId } from "@/lib/events";

export type PhaseState = "done" | "current" | "failed" | "skipped" | "todo";
export type Phase = { id: PhaseId; label: string; owner: ActorId; state: PhaseState; attempts: number; note?: string };

const BUILD: PhaseId[] = ["profile", "profile_review", "index-time", "extraction", "cim", "approval", "promoted"];
const UPDATE: PhaseId[] = ["diagnose", "index-time", "extraction", "cim", "regression", "approval", "promoted"];
const STAGE_PHASES = new Set<PhaseId>(["diagnose", "index-time", "extraction", "cim", "regression"]);

export const OWNER: Record<PhaseId, ActorId> = {
  profile: "profiler",
  profile_review: "human",
  routing: "router",
  diagnose: "validator",
  "index-time": "index_time",
  extraction: "extraction",
  cim: "cim_mapper",
  regression: "validator",
  approval: "human",
  promoted: "orchestrator",
};

export const STATE_TEXT: Record<PhaseState, string> = {
  done: "Done",
  current: "In progress",
  failed: "Failed",
  skipped: "Skipped",
  todo: "Not started",
};

const RUNNING = new Set(["queued", "running"]);
const AFTER_APPROVAL = new Set(["approved", "promoting", "done", "smoke_failed", "promotion_failed"]);

export function isUpdate(run: Pick<RunDetail, "form"> & { record?: RunDetail["record"] }, entries: Entry[]): boolean {
  return Boolean(run.form?.update_of) || run.record?.kind === "update" || jobStart(entries)?.detail.job_type === "update";
}

export function railOf(update: boolean, entries: Entry[]): PhaseId[] {
  if (update) return UPDATE;
  return entries.some((e) => e.phase === "routing") ? ["profile", "profile_review", "routing", ...BUILD.slice(2)] : BUILD;
}

/** The phase the run is in now: the default view when no ?phase= is given. */
export function currentPhase(status: string, entries: Entry[], rail: PhaseId[]): PhaseId {
  if (status === "profile_review") return "profile_review";
  if (status === "awaiting_approval" || status === "rejected") return "approval";
  if (AFTER_APPROVAL.has(status)) return "promoted";
  for (let i = entries.length - 1; i >= 0; i--) {
    const p = entries[i]!.phase;
    if (p && rail.includes(p) && p !== "approval") return p;
  }
  return rail[0]!;
}

function lastVisit(es: Entry[]): Entry[] {
  const v = Math.max(0, ...es.map((e) => e.visit ?? 0));
  return v ? es.filter((e) => e.visit === null || e.visit === v) : es;
}

const isStagePass = (e: Entry) => e.kind === "check_pass" && !Array.isArray(e.detail.checks) && e.detail.smoke === undefined;

export function phases(run: RunDetail, entries: Entry[]): Phase[] {
  const rail = railOf(isUpdate(run, entries), entries);
  const now = currentPhase(run.status, entries, rail);
  const failedRun = ["stage_failed", "error"].includes(run.status);
  const later = (id: PhaseId) => rail.slice(rail.indexOf(id) + 1).some((p) => entries.some((e) => e.phase === p));

  return rail.map((id): Phase => {
    const es = entries.filter((e) => e.phase === id);
    const attempts = attemptsOf(entries, id).attempts.length;
    const base = { id, label: STAGE_LABEL[id] ?? id, owner: OWNER[id], attempts };
    if (id === "approval") {
      if (run.status === "awaiting_approval") return { ...base, state: "current" };
      if (run.status === "rejected") return { ...base, state: "failed", note: "Rejected" };
      return { ...base, state: AFTER_APPROVAL.has(run.status) ? "done" : "todo" };
    }
    if (id === "promoted") {
      if (run.status === "done") return { ...base, state: "done" };
      if (run.status === "smoke_failed" || run.status === "promotion_failed") return { ...base, state: "failed" };
      return { ...base, state: run.status === "approved" || run.status === "promoting" ? "current" : "todo" };
    }
    if (id === "profile_review") {
      if (run.status === "profile_review") return { ...base, state: "current" };
      if (es.some((e) => e.kind === "info")) return { ...base, state: "skipped", note: "Auto-approved" };
      return { ...base, state: es.length || later(id) ? "done" : "todo" };
    }
    if (id === "profile") {
      if (es.some((e) => e.kind === "proposal") || later(id)) return { ...base, state: "done" };
      return { ...base, state: failedRun ? "failed" : RUNNING.has(run.status) ? "current" : "todo" };
    }
    if (!es.length) return { ...base, state: later(id) ? "skipped" : "todo", note: later(id) ? "Passed as is" : undefined };
    const v = lastVisit(es);
    if (STAGE_PHASES.has(id) && es.some((e) => isStagePass(e) && e.attempt === null && e.stage !== "diagnose" && e.stage !== "regression"))
      return { ...base, state: "skipped", note: "Passed as is" };
    if (v.some(isStagePass)) return { ...base, state: "done" };
    if (v.some((e) => e.kind === "budget" || (e.stage === "regression" && e.kind === "check_fail"))) return { ...base, state: "failed" };
    if (id === now) return { ...base, state: RUNNING.has(run.status) ? "current" : failedRun ? "failed" : "done" };
    return { ...base, state: "done" };
  });
}

// --- the "Now" banner and the budget meters -----------------------------------------------

export type Now = { actor: ActorId; text: string; phase: PhaseId; attempt: number | null; max: number | null; live: boolean };

export function maxAttempts(entries: Entry[]): number | null {
  for (let i = entries.length - 1; i >= 0; i--) {
    const m = num(entries[i]!.detail.max_attempts);
    if (m) return m;
  }
  return null;
}

/** Who is acting now, and what they are doing, in one plain sentence. */
export function describeNow(run: Pick<RunDetail, "status" | "form"> & { record?: RunDetail["record"] }, entries: Entry[]): Now {
  const rail = railOf(isUpdate(run, entries), entries);
  const phase = currentPhase(run.status, entries, rail);
  const last = [...entries].reverse().find((e) => e.phase === phase || e.phase === null);
  const attempt = last?.attempt ?? null;
  const max = maxAttempts(entries);
  const n = attempt ? `attempt ${attempt}` : "this phase";
  const agent = STAGE_AGENT[phase] ?? OWNER[phase];
  const stop = (a: ActorId, text: string): Now => ({ actor: a, text, phase, attempt, max, live: false });
  const go = (a: ActorId, text: string): Now => ({ actor: a, text, phase, attempt, max, live: true });

  switch (run.status) {
    case "profile_review":
      return stop("human", "Your turn: check what the Profiler found, correct anything wrong, then confirm.");
    case "awaiting_approval":
      return stop("human", "Your turn: review the report, then approve or reject the package.");
    case "approved":
    case "promoting":
      return go("orchestrator", "Orchestrator is installing the approved add-on under its real name, then the Validator runs a smoke test…");
    case "done":
      return stop("validator", "Promoted. The smoke test passed in Splunk.");
    case "rejected":
      return stop("human", "You rejected this run. Nothing was promoted.");
    case "smoke_failed":
      return stop("validator", "The smoke test failed after promotion.");
    case "promotion_failed":
      return stop("orchestrator", "Promotion failed. Nothing changed in production.");
    case "stage_failed":
      return stop("orchestrator", `The run stopped: ${STAGE_LABEL[phase] ?? phase} ran out of attempts.`);
    case "error":
      return stop("orchestrator", "The run stopped with an error. See the activity for details.");
    case "queued":
      if (!entries.some((e) => e.kind !== "info")) return go("orchestrator", "Waiting for a free worker…");
  }
  if (!last) return go(agent, `${STAGE_LABEL[phase]} is starting…`);
  const label = STAGE_LABEL[phase] ?? phase;
  switch (last.kind) {
    case "start":
      if (phase === "profile") return go("profiler", "Profiler is reading the samples…");
      if (phase === "diagnose" || phase === "regression") return go("validator", `Validator is running the ${label.toLowerCase()} checks in Splunk…`);
      return last.attempt ? go(agent, `${label} is writing ${n}'s settings…`) : go("orchestrator", "Orchestrator is starting the job…");
    case "proposal":
      if (phase === "profile") return go("orchestrator", "Orchestrator is saving the profile…");
      return go("orchestrator", `Orchestrator is installing ${n} in Splunk…`);
    case "deploy":
      return phase === "index-time" || phase === "diagnose"
        ? go("orchestrator", "Orchestrator is sending the samples into Splunk…")
        : go("validator", `Validator is testing ${n}'s settings in Splunk…`);
    case "ingest":
      return go("validator", `Validator is checking ${n} in Splunk…`);
    case "check_fail":
      return go("orchestrator", "Orchestrator is collecting the failures for the next attempt…");
    case "evidence":
    case "guardrail_block":
      return go(agent, `${label} is preparing its next attempt with the feedback…`);
    case "backtrack":
      return go(agent, `${label} is redoing its phase with a later phase's evidence…`);
    case "check_pass":
      return go("orchestrator", "Orchestrator is moving on to the next phase…");
  }
  return go(last.actor, last.sentence);
}

/** Budget: the latest run start carries the token ceiling and the per-run wall clock. */
export function budget(entries: Entry[]): { ceiling: number | null; wallS: number; startedAt: string | null; lastAt: string | null } {
  const start = jobStart(entries);
  return {
    ceiling: num(start?.detail.token_ceiling),
    wallS: num(start?.detail.wall_clock_s) ?? 900,
    startedAt: start?.at ?? null,
    lastAt: entries[entries.length - 1]?.at ?? null,
  };
}
