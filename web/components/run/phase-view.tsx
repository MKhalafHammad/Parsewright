"use client";

import { CornerUpLeft } from "lucide-react";
import Link from "next/link";

import { ActorAvatar, ActorChip, ActorName } from "@/components/actors/actor";
import { ToneIcon } from "@/components/ui/status";
import { actor } from "@/lib/actors";
import {
  arr,
  attemptsOf,
  checksOf,
  num,
  obj,
  proposalOf,
  said,
  STAGE_AGENT,
  STAGE_LABEL,
  str,
  type AttemptGroup,
  type Entry,
  type PhaseId,
} from "@/lib/events";
import { OWNER, STATE_TEXT, type Phase } from "@/lib/phases";
import { diffRows, proposalRows } from "@/lib/settings-diff";
import { cn } from "@/lib/utils";

import { CheckList, TechDetail } from "./checks";
import { ConfigView, SettingsDiff } from "./config-view";

function relTime(at: string): string {
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
}

/** One step of an attempt: who did it, one sentence, then what they produced. */
function Step({ e, prev, stanza }: { e: Entry; prev: Record<string, unknown> | null; stanza: string }) {
  const d = e.detail;
  let body: React.ReactNode = null;
  if (e.kind === "proposal" && d.settings) {
    const rows = proposalRows(obj(d.settings), stanza);
    body = (
      <div className="grid gap-3">
        {d.rationale ? <p className="text-sm text-muted">“{str(d.rationale)}”</p> : null}
        {prev ? (
          <SettingsDiff label="Changes from the previous attempt" changes={diffRows(proposalRows(prev, stanza), rows)} />
        ) : (
          <ConfigView rows={rows} />
        )}
        {prev && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted">All settings of this attempt</summary>
            <div className="pw-expand mt-2">
              <ConfigView rows={rows} />
            </div>
          </details>
        )}
      </div>
    );
  } else if (e.kind === "guardrail_block") {
    body = <p className="rounded-md bg-bad-bg px-3 py-2 text-sm whitespace-pre-wrap break-words">{str(d.reason)}</p>;
  } else if (e.kind === "deploy") {
    body = (
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-[13px]">
        {(["app", "version", "sourcetype", "sha256"] as const).map((k) =>
          d[k] ? (
            <div key={k} className="contents">
              <dt className="text-subtle">{k === "sha256" ? "SHA-256" : k[0]!.toUpperCase() + k.slice(1)}</dt>
              <dd className="min-w-0 break-all font-mono">{str(d[k])}</dd>
            </div>
          ) : null,
        )}
      </dl>
    );
  } else if (e.kind === "ingest" && arr(d.sets).length > 1) {
    body = (
      <ul className="text-[13px] text-muted">
        {arr(d.sets).map((s, i) => (
          <li key={i}>
            {str(obj(s).source)}: {num(obj(s).events)} events
          </li>
        ))}
      </ul>
    );
  } else if (checksOf(e)) {
    body = <CheckList checks={checksOf(e)!} />;
  } else if (e.kind === "evidence" && d.text) {
    body = (
      <details className="text-sm">
        <summary className="cursor-pointer text-muted">What the agent sees next</summary>
        <pre className="pw-expand mt-1 max-h-72 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-[12px] whitespace-pre-wrap break-all">{str(d.text)}</pre>
      </details>
    );
  } else if (e.kind === "evidence" && d.drift) {
    body = (
      <ul className="grid gap-2">
        {Object.entries(obj(d.drift)).map(([stage, text]) => (
          <li key={stage}>
            <p className="text-sm font-medium">{STAGE_LABEL[stage] ?? stage}</p>
            <pre className="mt-1 max-h-60 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-[12px] whitespace-pre-wrap break-all">{str(text)}</pre>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <li className="grid grid-cols-[auto_1fr] gap-x-3">
      <ActorAvatar id={e.actor} size="md" />
      <div className="grid min-w-0 gap-2 pb-4">
        <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
          <ActorName id={e.actor} />
          <ToneIcon tone={e.tone} className="self-center" label={e.tone === "good" ? "Pass" : e.tone === "bad" ? "Fail" : undefined} />
          <span>{said(e)}</span>
          <time dateTime={e.at} className="text-[12px] text-subtle">
            {relTime(e.at)}
          </time>
        </p>
        {body}
        <TechDetail entry={e} />
      </div>
    </li>
  );
}

function outcome(g: AttemptGroup): { tone: "good" | "bad" | "run"; text: string } {
  if (g.entries.some((e) => e.kind === "check_pass" && !e.detail.checks)) return { tone: "good", text: "Passed" };
  if (g.entries.some((e) => e.kind === "guardrail_block")) return { tone: "bad", text: "Blocked by the guardrail gate" };
  if (g.entries.some((e) => e.kind === "evidence" || e.kind === "check_fail")) return { tone: "bad", text: "Failed" };
  return { tone: "run", text: "In progress" };
}

function attemptLabel(g: AttemptGroup, visits: boolean) {
  return visits && g.visit && g.visit > 1 ? `Attempt ${g.n} (second pass, ${g.attempt})` : `Attempt ${g.n}`;
}

/** Backtracks into or out of this phase, said in plain words. */
function BacktrackNotes({ entries, phase }: { entries: Entry[]; phase: PhaseId }) {
  const notes = entries.filter((e) => e.kind === "backtrack" && (str(e.detail.to) === phase || str(e.detail.from) === phase));
  if (!notes.length) return null;
  return (
    <ul className="grid gap-2">
      {notes.map((e) => (
        <li key={e.id} className="flex gap-2 rounded-md border border-warn bg-warn-bg px-3 py-2 text-sm">
          <CornerUpLeft aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <span className="min-w-0">
            <span className="font-medium">Backtrack. </span>
            {str(e.detail.to) === phase
              ? `${STAGE_LABEL[str(e.detail.from)] ?? ""} sent this back to ${STAGE_LABEL[phase]} because: `
              : `${STAGE_LABEL[phase]} sent this back to ${STAGE_LABEL[str(e.detail.to)] ?? ""} because: `}
            <span className="whitespace-pre-wrap break-words">{str(e.detail.because).trim() || "it ran out of attempts"}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function AttemptTabs({ job, phase, attempts, selected, visits }: { job: string; phase: PhaseId; attempts: AttemptGroup[]; selected: number; visits: boolean }) {
  return (
    <nav aria-label="Attempts">
      <ul className="flex flex-wrap gap-2">
        {attempts.map((g) => {
          const o = outcome(g);
          const on = g.n === selected;
          return (
            <li key={g.n}>
              <Link
                href={`/runs/${job}?phase=${phase}&attempt=${g.n}`}
                scroll={false}
                aria-current={on ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm hover:bg-surface-2",
                  on ? "border-fg bg-surface-2 font-medium" : "border-line",
                )}
              >
                <ToneIcon tone={o.tone} label={o.text} className="h-3.5 w-3.5" />
                {attemptLabel(g, visits)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** A stage phase: its attempts, each with proposal → gate → deploy → checks → outcome. */
export function StagePhase({ job, phase, info, entries, attemptParam, stanza }: { job: string; phase: PhaseId; info: Phase; entries: Entry[]; attemptParam: number | null; stanza: string }) {
  const { attempts, phaseLevel } = attemptsOf(entries, phase);
  const selected = attempts.find((g) => g.n === attemptParam) ?? attempts[attempts.length - 1];
  const prev = selected ? attempts.slice(0, attempts.indexOf(selected)).reverse().find((g) => proposalOf(g)) : undefined;
  const visits = attempts.some((g) => (g.visit ?? 1) > 1);
  const owner = STAGE_AGENT[phase] ?? OWNER[phase];
  const other = phaseLevel.filter((e) => e.kind !== "backtrack");
  return (
    <div className="grid gap-4">
      <PhaseHead info={info} owner={owner} />
      <BacktrackNotes entries={entries} phase={phase} />
      {attempts.length > 0 && <AttemptTabs job={job} phase={phase} attempts={attempts} selected={selected?.n ?? 0} visits={visits} />}
      {selected && (
        <section aria-labelledby="attempt-title" className="grid gap-3">
          <h3 id="attempt-title" className="flex items-center gap-2 text-base font-semibold">
            {attemptLabel(selected, visits)}
            <span className={cn("flex items-center gap-1 text-sm font-normal", { good: "text-good", bad: "text-bad", run: "text-run" }[outcome(selected).tone])}>
              <ToneIcon tone={outcome(selected).tone} /> {outcome(selected).text}
            </span>
          </h3>
          <ol className="grid">
            {selected.entries
              .filter((e) => e.kind !== "start")
              .map((e) => (
                <Step key={e.id} e={e} prev={e.kind === "proposal" ? proposalOf(prev) : null} stanza={stanza} />
              ))}
          </ol>
        </section>
      )}
      {other.length > 0 && (
        <section aria-label={`${info.label}, phase events`} className="grid gap-2">
          {attempts.length > 0 && <h3 className="text-sm font-semibold text-muted">Phase events</h3>}
          <ol className="grid">
            {other.map((e) => (
              <Step key={e.id} e={e} prev={null} stanza={stanza} />
            ))}
          </ol>
        </section>
      )}
      {!attempts.length && !other.length && <p className="text-sm text-muted">{info.note ?? "Nothing has happened in this phase yet."}</p>}
    </div>
  );
}

export function PhaseHead({ info, owner }: { info: Phase; owner: string }) {
  const a = actor(owner);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
      <div>
        <h2 id="phase-title" className="text-lg font-semibold">
          {info.label}
        </h2>
        <p className="text-sm text-muted">
          {STATE_TEXT[info.state]}
          {info.note && info.note !== STATE_TEXT[info.state] ? ` · ${info.note}` : ""}
          {info.attempts > 0 && ` · ${info.attempts} ${info.attempts === 1 ? "attempt" : "attempts"}`}
        </p>
      </div>
      <ActorChip id={a.id} size="md" tagline />
    </div>
  );
}

/** Any other phase's events as steps (profile, promotion). */
export function EventSteps({ entries }: { entries: Entry[] }) {
  if (!entries.length) return null;
  return (
    <ol className="grid">
      {entries.map((e) => (
        <Step key={e.id} e={e} prev={null} stanza="" />
      ))}
    </ol>
  );
}
