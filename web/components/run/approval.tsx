"use client";

import { Download, ShieldAlert, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { ActorAvatar } from "@/components/actors/actor";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Meter, ToneIcon } from "@/components/ui/status";
import { postJson, type Report, type RunDetail, type UpdateReview } from "@/lib/api";
import { STAGE_LABEL } from "@/lib/events";
import type { Phase } from "@/lib/phases";
import { changesFromUnified, confRows } from "@/lib/settings-diff";

import { ConfigView, SettingsDiff } from "./config-view";
import { EventCompare } from "./event-compare";

export function ApprovalSummary({ report, phases }: { report: Report; phases: Phase[] }) {
  const worked = phases.filter((p) => p.attempts > 0);
  return (
    <section aria-labelledby="summary-title" className="grid gap-4">
      <h3 id="summary-title" className="text-base font-semibold">
        Summary
      </h3>
      <p className="text-sm">
        Learned from <strong>{report.holdout.learned_from}</strong> lines, passed on <strong>{report.holdout.validated_on}</strong> events (the full file). Every check ran in Splunk.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid content-start gap-3">
          <h4 className="text-[13px] font-semibold text-muted">CIM scores</h4>
          {report.scores.map((s) => (
            <div key={s.model} className="grid gap-1">
              <Meter
                label={s.model}
                value={s.passed}
                max={s.in_source || 1}
                text={`${s.passed} of ${s.in_source} required fields pass`}
                tone={s.passed === s.in_source ? "good" : "bad"}
              />
              <p className="text-[13px] text-subtle">
                Mapped {s.mapped} of {s.in_source} · not in this source (no penalty): {s.not_in_source.length ? s.not_in_source.join(", ") : "none"}
              </p>
            </div>
          ))}
        </div>
        <div className="grid content-start gap-2">
          <h4 className="text-[13px] font-semibold text-muted">Attempts per phase</h4>
          <ul className="grid gap-1.5">
            {worked.map((p) => (
              <li key={p.id} className="flex items-center gap-2 text-sm">
                <ActorAvatar id={p.owner} size="sm" />
                <span className="flex-1">{p.label}</span>
                <span className="tabular-nums">
                  {p.attempts} {p.attempts === 1 ? "attempt" : "attempts"}
                </span>
              </li>
            ))}
          </ul>
          <nav aria-label="Report sections" className="mt-2 flex flex-wrap gap-3 text-sm">
            <a href="#raw-parsed" className="underline underline-offset-2">
              Raw vs parsed
            </a>
            <a href="#config" className="underline underline-offset-2">
              Configuration as tested
            </a>
            {report.update && (
              <a href="#update" className="underline underline-offset-2">
                Changes against production
              </a>
            )}
          </nav>
        </div>
      </div>
    </section>
  );
}

export function UpdateNotes({ update }: { update: UpdateReview }) {
  return (
    <section aria-labelledby="update" className="grid gap-3">
      <h3 id="update" className="scroll-mt-4 text-base font-semibold">
        Parser update: {update.app} {update.version_from} → {update.version_to}
      </h3>
      <p className="text-sm text-muted">
        Patched: {update.patched.length ? update.patched.map((s) => STAGE_LABEL[s] ?? s).join(", ") : "nothing"}. Every check passed on the new samples and on every earlier version&apos;s samples. Promotion replaces default/ in place and keeps local/.
      </p>
      {update.overrides.length > 0 ? (
        <div role="alert" className="flex gap-2 rounded-md border border-warn bg-warn-bg p-3 text-sm">
          <ShieldAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <div>
            <p className="mb-1 font-semibold">Overrides that would hide this fix</p>
            <ul className="list-disc pl-5">
              {update.overrides.map((o, i) => (
                <li key={`${i}-${o}`} className="break-words">
                  {o}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <p className="flex items-center gap-2 text-sm text-muted">
          <ToneIcon tone="good" /> No local/ override touches the changed settings.
        </p>
      )}
      {update.notes.length > 0 && (
        <ul className="grid gap-1 text-sm">
          {update.notes.map((n, i) => (
            <li key={`${i}-${n}`} className="flex gap-2">
              <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
              {n}
            </li>
          ))}
        </ul>
      )}
      <h4 className="text-[13px] font-semibold text-muted">Changes against production</h4>
      {update.changes ? (
        <SettingsDiff label="Changes against production" changes={update.changes} />
      ) : Object.keys(update.diff ?? {}).length ? (
        <SettingsDiff label="Changes against production" changes={changesFromUnified(update.diff)} />
      ) : (
        <p className="text-sm text-muted">No changes were recorded for this update.</p>
      )}
      <p className="text-sm">
        To undo after promotion: <code className="rounded bg-surface-2 px-1 font-mono text-[13px]">{update.rollback}</code>
      </p>
    </section>
  );
}

export function ApprovalView({ run, report, phases, fieldOrder, tzNote }: { run: RunDetail; report: Report; phases: Phase[]; fieldOrder: string[]; tzNote?: string }) {
  return (
    <div className="grid gap-8">
      <ApprovalSummary report={report} phases={phases} />
      {report.update && <UpdateNotes update={report.update} />}
      <section aria-labelledby="raw-parsed" className="grid gap-3">
        <h3 id="raw-parsed" className="scroll-mt-4 text-base font-semibold">
          Raw vs parsed
        </h3>
        <EventCompare
          report={report}
          fieldOrder={fieldOrder}
          tzNote={tzNote}
          old={report.update?.old_event ? { label: `Old format (${report.update.version_from} samples)`, event: report.update.old_event } : undefined}
        />
      </section>
      <section aria-labelledby="config" className="grid gap-3">
        <h3 id="config" className="scroll-mt-4 text-base font-semibold">
          Configuration as tested
        </h3>
        <ConfigView rows={Object.entries(report.confs).flatMap(([file, text]) => confRows(file, text))} />
      </section>
      {run.status === "done" && (
        <p role="status" className="flex items-center gap-2 rounded-md bg-good-bg p-3 text-sm">
          <ToneIcon tone="good" /> Promoted as <span className="font-mono">{run.record.app}</span> · smoke test {run.record.smoke}
        </p>
      )}
    </div>
  );
}

/** Sticky decision bar: Approve (with the SHA-256 and a second confirmation), Reject, Download. */
export function DecisionBar({ run, onDone }: { run: RunDetail; onDone: () => void }) {
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sha = run.record.sha256_test ?? "";
  const update = run.record.report?.update;
  const awaiting = run.status === "awaiting_approval";
  const hashed = /^[0-9a-f]{64}$/.test(sha); // approve names exactly one package, or is not offered

  async function act(kind: "approve" | "reject") {
    setBusy(true);
    setError("");
    try {
      await postJson(`/runs/${run.job}/${kind}`, kind === "approve" ? { sha256: sha } : {});
      setConfirming(null);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="decide" className="glass-strong sticky bottom-3 z-20 rounded-2xl px-4 py-3 shadow-2xl">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h2 id="decide" className="text-sm font-semibold">
            {awaiting ? "Your decision" : "Package"}
          </h2>
          <p className="truncate font-mono text-[12px] text-muted" title={sha}>
            SHA-256 {sha}
          </p>
        </div>
        <Button asChild variant="outline">
          <a href={`/api/engine/runs/${run.job}/package`}>
            <Download aria-hidden className="h-4 w-4" /> Download .tgz
          </a>
        </Button>
        {awaiting && (
          <>
            <Button variant="destructive" onClick={() => setConfirming("reject")}>
              Reject…
            </Button>
            <Button disabled={!hashed} onClick={() => setConfirming("approve")}>
              Approve…
            </Button>
          </>
        )}
      </div>
      {error && !confirming && (
        <p role="alert" className="mt-2 text-sm text-bad">
          {error}
        </p>
      )}
      <Dialog
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        role="alertdialog"
        title={confirming === "approve" ? "Approve this package?" : "Reject this run?"}
      >
        <p className="text-sm">
          {confirming === "approve"
            ? update
              ? `Approve exactly this package (${sha.slice(0, 12)}…)? A worker then replaces ${update.app} ${update.version_from} in place with ${update.version_to} (local/ is kept) and runs a smoke test.`
              : `Approve exactly this package (${sha.slice(0, 12)}…)? A worker then installs it under its real name and runs a smoke test.`
            : "Reject this run? Nothing is promoted."}
        </p>
        {confirming === "approve" && <p className="break-all rounded bg-surface-2 p-2 font-mono text-[12px]">SHA-256 {sha}</p>}
        {update && confirming === "approve" && <p className="text-sm">To undo later: <code className="font-mono text-[13px]">{update.rollback}</code></p>}
        {error && (
          <p role="alert" className="text-sm text-bad">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button data-autofocus variant="outline" onClick={() => setConfirming(null)}>
            Cancel
          </Button>
          <Button disabled={busy} variant={confirming === "reject" ? "destructive" : "default"} onClick={() => confirming && act(confirming)}>
            {confirming === "approve" ? "Yes, approve" : "Yes, reject"}
          </Button>
        </div>
      </Dialog>
    </section>
  );
}
