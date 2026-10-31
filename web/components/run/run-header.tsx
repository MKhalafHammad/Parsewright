"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ActorAvatar, ActorName } from "@/components/actors/actor";
import { Meter, StatusBadge } from "@/components/ui/status";
import { actor, KIND_LABEL } from "@/lib/actors";
import type { RunDetail } from "@/lib/api";
import { STAGE_LABEL, type Entry } from "@/lib/events";
import { budget, type Now } from "@/lib/phases";

function useNowMs(live: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [live]);
  return now;
}

export function clock(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export function RunHeader({ run, entries, now, update }: { run: RunDetail; entries: Entry[]; now: Now; update: boolean }) {
  const b = budget(entries);
  const nowMs = useNowMs(now.live);
  const end = now.live ? nowMs : b.lastAt ? Date.parse(b.lastAt) : nowMs;
  const elapsed = b.startedAt ? Math.max(0, (end - Date.parse(b.startedAt)) / 1000) : 0;
  const attemptText = now.attempt ? `${now.attempt} of ${now.max ?? "?"}` : "–";
  return (
    <header className="grid gap-4 rounded-lg border border-line bg-surface p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,32rem)]">
      <div className="grid min-w-0 gap-1">
        <Link href="/" className="text-[13px] text-muted underline-offset-2 hover:underline">
          ← All runs
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-xl font-semibold">{run.job}</h1>
          <StatusBadge status={run.status} />
          {update && <span className="rounded-full border border-line px-2 py-0.5 text-[13px] text-muted">Parser update</span>}
        </div>
        <p className="text-sm text-muted">
          Source <span className="font-mono text-fg">{run.source_key}</span>
          {run.record.app && (
            <>
              {" "}· add-on <span className="font-mono text-fg">{run.record.app}</span>
            </>
          )}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3" aria-label="Budget">
        <Meter label={`Attempts (${STAGE_LABEL[now.phase] ?? now.phase})`} value={now.attempt ?? 0} max={now.max ?? 5} text={attemptText} tone={now.attempt && now.max && now.attempt >= now.max ? "warn" : "run"} />
        <Meter
          label="Tokens"
          value={run.tokens}
          max={b.ceiling ?? Math.max(run.tokens, 1)}
          text={b.ceiling ? `${run.tokens.toLocaleString()} of ${b.ceiling.toLocaleString()}` : run.tokens.toLocaleString()}
          tone={b.ceiling && run.tokens > b.ceiling * 0.8 ? "warn" : "run"}
        />
        <Meter label="Wall clock" value={elapsed} max={b.wallS} text={`${clock(elapsed)} of ${clock(b.wallS)}`} tone={elapsed > b.wallS * 0.8 ? "warn" : "run"} />
      </div>
    </header>
  );
}

/** Who is acting now, in one sentence. The only live region on the page besides alerts. */
export function NowBanner({ now, startedAt }: { now: Now; startedAt: string | null }) {
  const a = actor(now.actor);
  const nowMs = useNowMs(now.live);
  const since = startedAt && now.live ? clock(Math.max(0, (nowMs - Date.parse(startedAt)) / 1000)) : null;
  return (
    <section
      aria-label="Now"
      className="flex flex-wrap items-center gap-4 rounded-lg border-l-4 border border-line bg-surface p-4"
      style={{ borderLeftColor: a.accent }}
    >
      <ActorAvatar id={a.id} size="lg" active={now.live} />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-subtle">
          Now · {STAGE_LABEL[now.phase] ?? now.phase} · <ActorName id={a.id} className="text-fg" /> ({KIND_LABEL[a.kind]})
        </p>
        <p aria-live="polite" aria-atomic className="text-base font-medium">
          <span className="sr-only">{STAGE_LABEL[now.phase] ?? now.phase}: </span>
          {now.text}
        </p>
      </div>
      <dl className="flex gap-6 text-sm">
        {now.attempt !== null && (
          <div>
            <dt className="text-[13px] text-subtle">Attempt</dt>
            <dd className="font-medium tabular-nums">
              {now.attempt} of {now.max ?? "?"}
            </dd>
          </div>
        )}
        {since && (
          <div>
            <dt className="text-[13px] text-subtle">Elapsed</dt>
            <dd className="font-medium tabular-nums">{since}</dd>
          </div>
        )}
      </dl>
    </section>
  );
}
