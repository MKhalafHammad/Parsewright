"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApprovalReport } from "@/components/run/approval-report";
import { ProfileReview } from "@/components/run/profile-review";
import { Stepper } from "@/components/run/stepper";
import { Timeline } from "@/components/run/timeline";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type LedgerEvent, type RunDetail } from "@/lib/api";
import { STATUS_TEXT, statusVariant } from "@/lib/status";

const JOB_ID = /^[a-z0-9]{4,16}$/;
const MAX_ROWS = 500; // the timeline keeps the latest rows; the full ledger stays in the engine

export default function RunPage() {
  const params = useParams<{ id: string }>();
  const id = JOB_ID.test(params.id) ? params.id : "";
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [error, setError] = useState("");
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(() => {
    if (!id) return;
    api<RunDetail>(`/runs/${id}`).then(setRun).catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    if (!id) return;
    refresh();
    // Live updates: the engine pushes each ledger row as it is written (server-sent events).
    const source = new EventSource(`/api/engine/runs/${id}/stream`);
    source.addEventListener("ledger", (msg) => {
      const e = JSON.parse((msg as MessageEvent<string>).data) as LedgerEvent;
      setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev, e].slice(-MAX_ROWS)));
      if (e.event !== "log") {
        if (pending.current) clearTimeout(pending.current);
        pending.current = setTimeout(refresh, 200);
      }
    });
    return () => source.close();
  }, [id, refresh]);

  if (!id) return <p role="alert" className="text-red-700">Not a job id.</p>;
  if (error) return <p role="alert" className="text-red-700">{error}</p>;
  if (!run) return <p>Loading…</p>;

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/" className="text-sm underline">
          ← Jobs
        </Link>
        <h1 className="font-mono text-lg font-semibold">{run.job}</h1>
        <Badge variant={statusVariant(run.status)}>{STATUS_TEXT[run.status] ?? run.status}</Badge>
        <span className="text-sm text-slate-500">{run.tokens.toLocaleString()} tokens</span>
      </div>
      <Stepper status={run.status} stageIndex={run.stage_index} hasProfile={Boolean(run.profile)} />

      {run.status === "profile_review" && run.profile && (
        <ProfileReview job={run.job} profile={run.profile} onDone={refresh} />
      )}
      {run.record.report?.events && <ApprovalReport run={run} onDone={refresh} />}
      {run.status === "done" && (
        <p role="status" className="rounded-md bg-green-50 p-3 text-sm text-green-900">
          Promoted as <span className="font-mono">{run.record.app}</span> · smoke test {run.record.smoke}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Live run</CardTitle>
          <p className="text-sm text-slate-600">Every attempt, proposal, check and piece of evidence, as it happens.</p>
        </CardHeader>
        <CardContent>
          <Timeline events={events} />
        </CardContent>
      </Card>
    </div>
  );
}
