"use client";

import { Hand, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ActorAvatar, ActorName } from "@/components/actors/actor";
import { NewRunSheet } from "@/components/board/new-run-sheet";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, type Job, type LedgerEvent, type TA } from "@/lib/api";
import { STAGE_LABEL, toEntry, type Entry } from "@/lib/events";
import { describeNow } from "@/lib/phases";

const FINAL = new Set(["done", "rejected", "stage_failed", "error", "smoke_failed", "promotion_failed"]);
const NEEDS_YOU = new Set(["profile_review", "awaiting_approval"]);
const MAX_FOLLOWED = 30; // jobs whose ledger the board reads, newest first
const KEEP = 200; // the board only needs each job's latest rows

type Ledger = { after: number; entries: Entry[]; final: boolean };

export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tas, setTas] = useState<TA[]>([]);
  const [ledgers, setLedgers] = useState<Record<string, Ledger>>({});
  const known = useRef<Record<string, Ledger>>({});
  const busy = useRef(false); // one polling round at a time
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sheet, setSheet] = useState(false);

  const follow = useCallback(async (list: Job[]) => {
    // Each job's own ledger says which phase and agent it is on; only new rows are fetched.
    const next = { ...known.current };
    await Promise.all(
      list.slice(0, MAX_FOLLOWED).map(async (j) => {
        const have = next[j.job];
        if (have?.final) return;
        try {
          const rows = await api<LedgerEvent[]>(`/runs/${j.job}/events?after=${have?.after ?? 0}`);
          const entries = [...(have?.entries ?? []), ...rows.map(toEntry)].slice(-KEEP);
          next[j.job] = { after: rows.length ? rows[rows.length - 1]!.id : (have?.after ?? 0), entries, final: FINAL.has(j.status) };
        } catch {
          /* the board still shows the job's status */
        }
      }),
    );
    known.current = next;
    setLedgers(next);
  }, []);

  const refresh = useCallback(() => {
    if (busy.current || document.hidden) return; // never stack rounds; idle in a hidden tab
    busy.current = true;
    api<Job[]>("/runs")
      .then(async (list) => {
        setJobs(list);
        setError("");
        await follow(list);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => {
        busy.current = false;
      });
  }, [follow]);

  useEffect(() => {
    api<TA[]>("/tas")
      .then(setTas)
      .catch(() => setTas([])); // no registry yet: new builds only
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [refresh]);

  const needsYou = jobs.filter((j) => NEEDS_YOU.has(j.status));

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Runs</h1>
          <p className="text-sm text-muted">Updates every few seconds. Open a run to follow it live.</p>
        </div>
        <Button onClick={() => setSheet(true)}>
          <Plus aria-hidden className="h-4 w-4" /> New run
        </Button>
      </div>
      <p role="status" aria-live="polite" className="text-sm text-good empty:hidden">
        {message}
      </p>
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}

      {needsYou.length > 0 && (
        <section aria-labelledby="needs-you" className="grid gap-2">
          <h2 id="needs-you" className="flex items-center gap-2 text-base font-semibold">
            <Hand aria-hidden className="h-4 w-4 text-warn" /> Needs you
          </h2>
          <ul className="grid gap-2 md:grid-cols-2">
            {needsYou.map((j) => (
              <li key={j.job} className="flex flex-wrap items-center gap-3 rounded-lg border border-l-4 border-line border-l-warn bg-surface p-3">
                <ActorAvatar id="human" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    {j.status === "profile_review" ? "Review the profile" : "Approve or reject the package"}
                  </p>
                  <p className="truncate text-[13px] text-muted">
                    <span className="font-mono">{j.job}</span> · <span className="font-mono">{j.source_key}</span>
                  </p>
                </div>
                <Button asChild size="sm">
                  <Link href={`/runs/${j.job}`}>{j.status === "profile_review" ? "Review profile" : "Review and decide"}</Link>
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="all-runs" className="rounded-lg border border-line bg-surface">
        <h2 id="all-runs" className="border-b border-line px-4 py-3 text-base font-semibold">
          All runs
        </h2>
        {jobs.length === 0 ? (
          <p className="p-4 text-sm text-muted">No runs yet. Start one with “New run”.</p>
        ) : (
          <Table aria-label="Jobs">
            <THead>
              <Tr>
                <Th scope="col" className="pl-4">Job</Th>
                <Th scope="col">Source</Th>
                <Th scope="col">Phase</Th>
                <Th scope="col">Working now</Th>
                <Th scope="col">Attempt</Th>
                <Th scope="col">Tokens</Th>
                <Th scope="col">Status</Th>
                <Th scope="col">Updated</Th>
              </Tr>
            </THead>
            <TBody>
              {jobs.map((j) => {
                const entries = ledgers[j.job]?.entries ?? [];
                const now = describeNow(j, entries);
                return (
                  <Tr key={j.job}>
                    <Td className="pl-4">
                      <Link className="font-mono underline underline-offset-2" href={`/runs/${j.job}`}>
                        {j.job}
                      </Link>
                    </Td>
                    <Td className="font-mono text-[13px] break-all">{j.source_key}</Td>
                    <Td className="whitespace-nowrap">{STAGE_LABEL[now.phase] ?? now.phase}</Td>
                    <Td className="min-w-[16rem]">
                      <span className="flex items-start gap-2">
                        <ActorAvatar id={now.actor} size="sm" active={now.live} />
                        <span className="min-w-0 text-[13px]">
                          <ActorName id={now.actor} className="block text-sm" />
                          <span className="text-muted">{now.text}</span>
                        </span>
                      </span>
                    </Td>
                    <Td className="whitespace-nowrap tabular-nums">{now.attempt ? `${now.attempt}/${now.max ?? "?"}` : "–"}</Td>
                    <Td className="tabular-nums">{j.tokens.toLocaleString()}</Td>
                    <Td>
                      <StatusBadge status={j.status} />
                    </Td>
                    <Td className="whitespace-nowrap text-[13px] text-subtle">{new Date(j.updated_at).toLocaleTimeString()}</Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        )}
      </section>

      <NewRunSheet
        open={sheet}
        onClose={() => setSheet(false)}
        tas={tas}
        onQueued={(m) => {
          setMessage(m);
          refresh();
        }}
      />
    </div>
  );
}
