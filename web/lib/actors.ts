// The actor identity system, defined once and used on every screen. It keeps the design's
// principle visible: agents propose, code acts, Splunk judges, a human approves. The kind
// changes the avatar's shape and badge, not only its colour; the name always appears too.
import {
  Clock,
  FlaskConical,
  Network,
  Pickaxe,
  Radar,
  ScanSearch,
  ShieldCheck,
  Split,
  UserRound,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export type ActorId =
  | "profiler"
  | "router"
  | "index_time"
  | "extraction"
  | "cim_mapper"
  | "drift_analyst"
  | "gate"
  | "orchestrator"
  | "validator"
  | "human";

export type ActorKind = "ai" | "code" | "splunk" | "human";

export type Actor = {
  id: ActorId;
  name: string;
  kind: ActorKind;
  icon: LucideIcon;
  /** CSS variable holding the accent, light and dark (app/globals.css). */
  accent: string;
  tagline: string;
};

export const KIND_LABEL: Record<ActorKind, string> = {
  ai: "AI agent",
  code: "Code",
  splunk: "Splunk + fixed checks (no AI)",
  human: "Human",
};

export const ACTORS: Record<ActorId, Actor> = {
  profiler: { id: "profiler", name: "Profiler", kind: "ai", icon: ScanSearch, accent: "var(--a-profiler)", tagline: "Reads the samples and describes the log" },
  router: { id: "router", name: "Router", kind: "ai", icon: Split, accent: "var(--a-router)", tagline: "Splits a shared feed into sourcetypes" },
  index_time: { id: "index_time", name: "Index-time", kind: "ai", icon: Clock, accent: "var(--a-index-time)", tagline: "Splits events and finds timestamps" },
  extraction: { id: "extraction", name: "Extraction", kind: "ai", icon: Pickaxe, accent: "var(--a-extraction)", tagline: "Pulls the fields out" },
  cim_mapper: { id: "cim_mapper", name: "CIM mapper", kind: "ai", icon: Network, accent: "var(--a-cim-mapper)", tagline: "Maps fields to the CIM data model" },
  drift_analyst: { id: "drift_analyst", name: "Drift Analyst", kind: "ai", icon: Radar, accent: "var(--a-drift-analyst)", tagline: "Decides whether a detected format change is real" },
  gate: { id: "gate", name: "Guardrail gate", kind: "code", icon: ShieldCheck, accent: "var(--a-gate)", tagline: "Blocks unsafe or out-of-scope config" },
  orchestrator: { id: "orchestrator", name: "Orchestrator", kind: "code", icon: Workflow, accent: "var(--a-orchestrator)", tagline: "Deploys, reloads, ingests, retries" },
  validator: { id: "validator", name: "Validator", kind: "splunk", icon: FlaskConical, accent: "var(--a-validator)", tagline: "Runs the checks that decide pass or fail" },
  human: { id: "human", name: "You", kind: "human", icon: UserRound, accent: "var(--a-human)", tagline: "Reviews the profile, approves or rejects" },
};

export function actor(id: unknown): Actor {
  return typeof id === "string" && Object.hasOwn(ACTORS, id) ? ACTORS[id as ActorId] : ACTORS.orchestrator;
}
