// Runs recorded before the engine labelled its events (before 2026-10-30) carry only a text
// line. This reads those known line shapes once, in order, to recover the stage, attempt,
// actor and kind, so older runs show the same phases and agents as new ones. Display only;
// new events always carry the engine's own labels and never come through here.
import type { ActorId } from "@/lib/actors";
import type { Kind, Stage } from "@/lib/events";

export type Labels = {
  stage: Stage | null;
  attempt: number | null;
  visit: number | null;
  actor: ActorId;
  kind: Kind;
  detail: Record<string, unknown>;
  sentence?: string;
  /** An indented example line: appended to the previous check instead of a new entry. */
  example?: string;
  /** A continuation line: appended to the previous entry's text. */
  continues?: boolean;
};

const AGENT: Record<string, ActorId> = { "index-time": "index_time", extraction: "extraction", cim: "cim_mapper" };
const STAGES = new Set(["index-time", "extraction", "cim"]);

// --- a small reader for Python literals (the old proposal lines print Python dicts) -----

function pyLiteral(text: string): unknown {
  let i = 0;
  const ws = () => {
    while (i < text.length && /\s/.test(text[i]!)) i++;
  };
  const value = (): unknown => {
    ws();
    const c = text[i];
    if (c === "{" || c === "[") {
      const close = c === "{" ? "}" : "]";
      const out: unknown[] = [];
      const obj: Record<string, unknown> = Object.create(null);
      i++;
      ws();
      while (text[i] !== close) {
        const k = value();
        ws();
        if (c === "{") {
          if (text[i++] !== ":") throw new Error("expected :");
          obj[String(k)] = value();
        } else out.push(k);
        ws();
        if (text[i] === ",") i++;
        ws();
        if (i >= text.length) throw new Error("unterminated");
      }
      i++;
      return c === "{" ? { ...obj } : out;
    }
    if (c === "'" || c === '"') {
      i++;
      let s = "";
      while (i < text.length && text[i] !== c) {
        if (text[i] === "\\") {
          const n = text[i + 1];
          s += n === "n" ? "\n" : n === "t" ? "\t" : n === "r" ? "\r" : (n ?? "");
          i += 2;
        } else s += text[i++];
      }
      if (text[i++] !== c) throw new Error("unterminated string");
      return s;
    }
    const m = /^(True|False|None|-?\d+(\.\d+)?)/.exec(text.slice(i));
    if (!m) throw new Error("unexpected");
    i += m[0].length;
    return m[0] === "True" ? true : m[0] === "False" ? false : m[0] === "None" ? null : Number(m[0]);
  };
  const v = value();
  return v;
}

function settingsOf(text: string): Record<string, unknown> | null {
  try {
    const v = pyLiteral(text);
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
  } catch {
    return null; // a line cut at the length cap: the raw line is still shown
  }
}

// --- the reader --------------------------------------------------------------------------

export class LegacyReader {
  private stage: Stage | null = null;
  private attempt: number | null = null;
  private visits: Record<string, number> = {};
  private sampleSet: string | null = null;
  private backtracked: string | null = null;

  private at(stage: Stage | null, attempt = this.attempt) {
    return { stage, attempt, visit: stage ? (this.visits[stage] ?? 1) : null };
  }

  read(line: string): Labels {
    const t = line.trim();
    const indent = line.length - line.trimStart().length;
    let m: RegExpExecArray | null;
    const here = this.at(this.stage);
    const agent = (AGENT[this.stage ?? ""] ?? "orchestrator") as ActorId;

    if ((m = /^(update )?job \w+: (.*)$/.exec(t))) {
      this.stage = null;
      this.attempt = null;
      return { ...this.at(null, null), actor: "orchestrator", kind: "start", detail: { job_type: m[1] ? "update" : "build" }, sentence: `${m[1] ? "Update job" : "Job"} started: ${m[2]}` };
    }
    if ((m = /^profile: (.*)$/.exec(t))) {
      this.stage = "profile";
      return { ...this.at("profile", null), actor: "profiler", kind: "proposal", detail: {}, sentence: `Profiler described the log: ${m[1]}` };
    }
    if (/^profile review: auto-approved/.test(t)) return { ...this.at("profile", null), actor: "orchestrator", kind: "info", detail: {}, sentence: "Profile review skipped: auto-approved" };
    if (/^profile review: waiting/.test(t)) return { ...this.at("profile", null), actor: "human", kind: "human_wait", detail: { for: "profile_review" } };
    if ((m = /^(patch )?(index-time|extraction|cim) attempt (\d+)/.exec(t))) {
      const stage = m[2] as Stage;
      const n = Number(m[3]);
      if (this.backtracked === stage) this.backtracked = null; // the backtrack already opened this visit
      else if (n === 1 || !this.visits[stage]) this.visits[stage] = (this.visits[stage] ?? 0) + 1;
      this.stage = stage;
      this.attempt = n;
      this.sampleSet = null;
      return { ...this.at(stage), actor: AGENT[stage]!, kind: "start", detail: {} };
    }
    if ((m = /^proposal: (\{.*)$/.exec(t)))
      return { ...here, actor: agent, kind: "proposal", detail: { settings: settingsOf(m[1]!.replace(/\s*\(sourcetype [^)]*\)$/, "")) ?? {} } };
    if ((m = /^guardrail block: (.*)$/.exec(t))) return { ...here, actor: "gate", kind: "guardrail_block", detail: { reason: m[1] } };
    if ((m = /^bad output after retries: (.*)$/.exec(t))) return { ...here, actor: "gate", kind: "guardrail_block", detail: { reason: m[1], type: "bad_output" } };
    if (/^evidence for the next attempt/.test(t)) return { ...here, actor: "orchestrator", kind: "evidence", detail: { to: this.stage } };
    if (/^deploy: /.test(t)) return { ...here, actor: "orchestrator", kind: "deploy", detail: {}, sentence: `Orchestrator installed the test build: ${t.slice(8)}` };
    if (/^ingest: /.test(t)) return { ...here, actor: "orchestrator", kind: "ingest", detail: {}, sentence: `Orchestrator sent ${t.slice(8)}` };
    if ((m = /^\[(.+)\] (PASS|FAIL)$/.exec(t))) {
      this.sampleSet = m[1]!;
      return { ...here, actor: "validator", kind: m[2] === "PASS" ? "check_pass" : "check_fail", detail: { sample_set: m[1], checks: [] }, sentence: `Splunk checks ${m[2] === "PASS" ? "passed" : "failed"} on ${m[1]}` };
    }
    if ((m = /^(PASS|FAIL) (.+?): expected (.*), actual (.*)$/.exec(t)) && indent >= 2 && indent < 4) {
      const passed = m[1] === "PASS";
      return { ...here, actor: "validator", kind: passed ? "check_pass" : "check_fail", detail: { sample_set: this.sampleSet, checks: [{ name: m[2], passed, expected: m[3], actual: m[4], examples: [] }] } };
    }
    if (indent >= 4 && this.stage) return { ...here, actor: "validator", kind: "info", detail: {}, example: t };
    if ((m = /^(index-time|extraction|cim): (patched, )?PASS/.exec(t))) return { ...this.at(m[1] as Stage), actor: "validator", kind: "check_pass", detail: {} };
    if ((m = /^(index-time|extraction|cim): passes as it is/.exec(t))) {
      const stage = m[1] as Stage;
      this.stage = stage;
      return { stage, attempt: null, visit: null, actor: "validator", kind: "check_pass", detail: {} };
    }
    if ((m = /^(index-time|extraction|cim): FAIL after/.exec(t))) return { ...this.at(m[1] as Stage, null), actor: "orchestrator", kind: "budget", detail: { reason: "attempts" } };
    if ((m = /^backtrack: re-running (\S+) once with (\S+?)'s evidence/.exec(t))) {
      const to = m[1]!;
      if (STAGES.has(to)) {
        this.visits[to] = (this.visits[to] ?? 1) + 1;
        this.backtracked = to;
      }
      return { ...this.at(STAGES.has(to) ? (to as Stage) : null, null), actor: "orchestrator", kind: "backtrack", detail: { from: m[2], to } };
    }
    if (/^diagnose: .*already parses/.test(t)) return { ...this.at("diagnose", null), actor: "validator", kind: "check_pass", detail: {}, sentence: t };
    if (/^diagnose: /.test(t)) {
      this.stage = "diagnose";
      this.attempt = null;
      return { ...this.at("diagnose", null), actor: "orchestrator", kind: "start", detail: {} };
    }
    if ((m = /^diagnose (index-time|extraction|cim):$/.exec(t))) {
      this.stage = "diagnose";
      this.sampleSet = null;
      return { ...this.at("diagnose", null), actor: "validator", kind: "info", detail: { checked: m[1] } };
    }
    if ((m = /^drift report: (.*) fail on the new samples/.exec(t)))
      return { ...this.at("diagnose", null), actor: "orchestrator", kind: "evidence", detail: { stages: m[1]!.split(", ") } };
    if (/^regression: the final/.test(t)) {
      this.stage = "regression";
      this.attempt = null;
      return { ...this.at("regression", null), actor: "orchestrator", kind: "start", detail: {} };
    }
    if (/^regression: FAIL/.test(t)) return { ...this.at("regression", null), actor: "validator", kind: "check_fail", detail: {} };
    if ((m = /^holdout: learned from (\d+) lines.*\((\d+) events\)/.exec(t))) {
      this.stage = null;
      return { ...this.at(null, null), actor: "validator", kind: "info", detail: { learned_from: Number(m[1]), validated_on: Number(m[2]) } };
    }
    if ((m = /^CIM (\S+): required fields (\d+)\/(\d+) passed/.exec(t)))
      return { ...this.at(null, null), actor: "validator", kind: "info", detail: { score: { model: m[1], passed: Number(m[2]), in_source: Number(m[3]) } } };
    if (/^awaiting approval/.test(t)) return { ...this.at(null, null), actor: "human", kind: "human_wait", detail: { for: "approval" } };
    if (/^(installed|rolled back) /.test(t)) {
      this.stage = "promotion";
      return { ...this.at("promotion", null), actor: "orchestrator", kind: "deploy", detail: {}, sentence: `Orchestrator ${t}` };
    }
    if (/^derived from approved/.test(t)) return { ...this.at(this.stage, null), actor: "orchestrator", kind: "info", detail: {}, continues: true };
    if ((m = /^smoke test: (.*)$/.exec(t))) return { ...this.at("promotion", null), actor: "validator", kind: /^PASS/.test(m[1]!) ? "check_pass" : "check_fail", detail: { smoke: m[1] } };
    return { ...this.at(null, null), actor: "orchestrator", kind: "info", detail: {} };
  }
}
