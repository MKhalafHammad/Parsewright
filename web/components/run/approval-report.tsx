"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { postJson, type RunDetail } from "@/lib/api";

import { RawLine } from "./raw-line";

export function ApprovalReport({ run, onDone }: { run: RunDetail; onDone: () => void }) {
  const report = run.record.report?.events ? run.record.report : null; // older runs: no report
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!report) return null;
  const sha = run.record.sha256_test ?? "";
  const awaiting = run.status === "awaiting_approval";

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
    <Card>
      <CardHeader>
        <CardTitle>Approval report</CardTitle>
        <p className="text-sm text-slate-600">
          Learned from {report.holdout.learned_from} lines, passed on the full file ({report.holdout.validated_on} events).
          Every check below ran in Splunk.
        </p>
      </CardHeader>
      <CardContent className="grid gap-6">
        <section aria-labelledby="scores">
          <h3 id="scores" className="mb-2 text-sm font-semibold">
            CIM scores
          </h3>
          <ul className="grid gap-2 sm:grid-cols-2">
            {report.scores.map((s) => (
              <li key={s.model} className="rounded-md border border-slate-200 p-3 text-sm">
                <p className="font-semibold">{s.model}</p>
                <p>
                  Required fields: {s.passed}/{s.in_source} passed · mapped {s.mapped}/{s.in_source}
                </p>
                <p className="text-slate-500">
                  Not in source (no penalty): {s.not_in_source.length ? s.not_in_source.join(", ") : "none"}
                </p>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="raw-parsed">
          <h3 id="raw-parsed" className="mb-2 text-sm font-semibold">
            Raw vs parsed
          </h3>
          <ol className="grid gap-3">
            {report.events.map((e, i) => (
              <li key={`${i}-${e.time}`} className="grid gap-2 rounded-md border border-slate-200 p-3 lg:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs text-slate-500">
                    _time {new Date(e.time * 1000).toISOString().replace(".000Z", "Z")}
                  </p>
                  <RawLine raw={e.raw} highlights={e.highlights} />
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 font-mono text-xs">
                  {Object.entries(e.fields).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-slate-500">{k}</dt>
                      <dd className="break-all">{v}</dd>
                    </div>
                  ))}
                </dl>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="mapping">
          <h3 id="mapping" className="mb-2 text-sm font-semibold">
            Source field → CIM field
          </h3>
          <Table aria-labelledby="mapping">
            <THead>
              <Tr>
                <Th scope="col">CIM field</Th>
                <Th scope="col">How</Th>
                <Th scope="col">From</Th>
                <Th scope="col">Example value</Th>
              </Tr>
            </THead>
            <TBody>
              {report.mapping.map((m) => (
                <Tr key={m.cim_field}>
                  <Td className="font-mono text-xs">{m.cim_field}</Td>
                  <Td className="text-xs">{m.kind === "FIELDALIAS" ? "alias" : "eval"}</Td>
                  <Td className="font-mono text-xs break-all">{m.from}</Td>
                  <Td className="font-mono text-xs break-all">{m.example}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </section>

        <section aria-labelledby="confs">
          <h3 id="confs" className="mb-2 text-sm font-semibold">
            Configuration (as tested)
          </h3>
          {Object.entries(report.confs).map(([name, text]) => (
            <details key={name} className="mb-2 rounded-md border border-slate-200">
              <summary className="cursor-pointer px-3 py-2 font-mono text-xs">{name}</summary>
              <pre className="overflow-auto bg-slate-50 p-3 text-xs">{text}</pre>
            </details>
          ))}
        </section>

        <section aria-labelledby="decide" className="rounded-md border border-slate-300 p-3">
          <h3 id="decide" className="mb-1 text-sm font-semibold">
            Decision
          </h3>
          <p className="mb-3 break-all font-mono text-xs text-slate-600">Package SHA-256: {sha}</p>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <a href={`/api/engine/runs/${run.job}/package`}>Download .tgz</a>
            </Button>
            {awaiting && !confirming && (
              <>
                <Button onClick={() => setConfirming("approve")}>Approve…</Button>
                <Button variant="destructive" onClick={() => setConfirming("reject")}>
                  Reject…
                </Button>
              </>
            )}
          </div>
          {confirming && (
            <div role="alertdialog" aria-labelledby="confirm-title" className="mt-3 rounded-md bg-slate-100 p-3">
              <p id="confirm-title" className="mb-2 text-sm">
                {confirming === "approve"
                  ? `Approve exactly this package (${sha.slice(0, 12)}…)? A worker then installs it under its real name and runs a smoke test.`
                  : "Reject this run? Nothing is promoted."}
              </p>
              <div className="flex gap-2">
                <Button autoFocus disabled={busy} variant={confirming === "reject" ? "destructive" : "default"} onClick={() => act(confirming)}>
                  {confirming === "approve" ? "Yes, approve" : "Yes, reject"}
                </Button>
                <Button variant="outline" onClick={() => setConfirming(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
          {error && (
            <p role="alert" className="mt-2 text-sm text-red-700">
              {error}
            </p>
          )}
        </section>
      </CardContent>
    </Card>
  );
}
