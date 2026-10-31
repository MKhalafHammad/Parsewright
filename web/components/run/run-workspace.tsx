"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, type LedgerEvent, type RunDetail } from "@/lib/api";
import { obj, str, toEntry, type Entry, type PhaseId } from "@/lib/events";
import { budget, currentPhase, describeNow, isUpdate, phases as phasesOf, railOf } from "@/lib/phases";

import { ActivityFeed } from "./activity-feed";
import { ApprovalView, DecisionBar } from "./approval";
import { EventSteps, PhaseHead, StagePhase } from "./phase-view";
import { PhaseRail } from "./phase-rail";
import { ProfileFindings, ProfileReview } from "./profile-review";
import { NowBanner, RunHeader } from "./run-header";

const MAX_ROWS = 5000; // the workspace keeps the latest rows; the full ledger stays in the engine

function tzNoteOf(run: RunDetail): string | undefined {
  const p = run.profile;
  if (!p) return undefined;
  if (p.timezone_in_timestamp) return "The raw timestamp carries its own offset; _time is shown here in UTC.";
  const tz = p.timezone_hint || str(run.form.tz) || "UTC";
  return `The raw timestamp has no offset, so Splunk applied ${tz}. _time is shown in UTC and can differ from the raw text.`;
}

export function RunWorkspace({ id }: { id: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [error, setError] = useState("");
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const params = useSearchParams();

  const refresh = useCallback(() => {
    api<RunDetail>(`/runs/${id}`)
      .then(setRun)
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    refresh();
    // Live updates: the engine replays the ledger, then pushes each row as it is written.
    const source = new EventSource(`/api/engine/runs/${id}/stream`);
    source.addEventListener("ledger", (msg) => {
      let e: LedgerEvent;
      try {
        e = JSON.parse((msg as MessageEvent<string>).data) as LedgerEvent;
      } catch {
        return;
      }
      setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev, e].slice(-MAX_ROWS)));
      if (e.event !== "log" || ["human_wait", "check_pass", "budget"].includes(str(obj(e.data).kind))) {
        if (pending.current) clearTimeout(pending.current);
        pending.current = setTimeout(refresh, 200);
      }
    });
    return () => source.close();
  }, [id, refresh]);

  const entries = useMemo<Entry[]>(() => events.map(toEntry), [events]);

  if (error) return <p role="alert" className="text-bad">{error}</p>;
  if (!run) return <p>Loading…</p>;

  const update = isUpdate(run, entries);
  const rail = railOf(update, entries);
  const list = phasesOf(run, entries);
  const asked = params.get("phase") as PhaseId | null;
  const selected: PhaseId = asked && rail.includes(asked) ? asked : currentPhase(run.status, entries, rail);
  const attempt = Number(params.get("attempt")) || null;
  const info = list.find((p) => p.id === selected)!;
  const now = describeNow(run, entries);
  const report = run.record.report?.events ? run.record.report : null;
  const fieldOrder = run.profile?.fields.map((f) => f.name) ?? [];
  const stanza = run.profile?.sourcetype ? `${run.profile.sourcetype} (test copy)` : "this sourcetype";

  let view: React.ReactNode;
  if (selected === "profile_review" && run.status === "profile_review" && run.profile) {
    view = <ProfileReview job={run.job} profile={run.profile} onDone={refresh} />;
  } else if (selected === "profile" || selected === "profile_review") {
    const own = entries.filter((e) => e.phase === selected);
    view = (
      <div className="grid gap-4">
        <PhaseHead info={info} owner={info.owner} />
        {selected === "profile" && run.profile && <ProfileFindings profile={run.profile} />}
        <EventSteps entries={own} />
        {!own.length && !run.profile && <p className="text-sm text-muted">Nothing has happened in this phase yet.</p>}
      </div>
    );
  } else if (selected === "approval" || selected === "promoted") {
    const own = entries.filter((e) => e.phase === selected);
    view = (
      <div className="grid gap-4">
        <PhaseHead info={info} owner={info.owner} />
        {selected === "approval" && report ? (
          <ApprovalView run={run} report={report} phases={list} fieldOrder={fieldOrder} tzNote={tzNoteOf(run)} />
        ) : null}
        <EventSteps entries={own} />
        {!own.length && !report && (
          <p className="text-sm text-muted">{selected === "approval" ? "The approval report appears when every phase has passed." : "Promotion starts after you approve."}</p>
        )}
      </div>
    );
  } else {
    view = <StagePhase job={run.job} phase={selected} info={info} entries={entries} attemptParam={attempt} stanza={stanza} />;
  }

  return (
    <div className="grid gap-4">
      <RunHeader run={run} entries={entries} now={now} update={update} />
      <NowBanner now={now} startedAt={budget(entries).startedAt} />
      <PhaseRail job={run.job} phases={list} selected={selected} />
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_28rem]">
        <section aria-labelledby="phase-title" className="min-w-0 rounded-lg border border-line bg-surface p-4">
          {view}
        </section>
        <div className="xl:sticky xl:top-4">
          <ActivityFeed job={run.job} entries={entries} />
        </div>
      </div>
      {report && (run.status === "awaiting_approval" || selected === "approval") && <DecisionBar run={run} onDone={refresh} />}
    </div>
  );
}
