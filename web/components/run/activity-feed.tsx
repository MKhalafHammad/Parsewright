"use client";

import { ArrowDown } from "lucide-react";
import Link from "next/link";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ActorAvatar, ActorName } from "@/components/actors/actor";
import { ToneIcon } from "@/components/ui/status";
import { ACTORS, type ActorId } from "@/lib/actors";
import { feedSections, said, STAGE_LABEL, type Entry } from "@/lib/events";

import { TechDetail } from "./checks";

type KindFilter = "all" | "failures" | "checks" | "proposals" | "human";
const KIND_FILTERS: { id: KindFilter; label: string; test: (e: Entry) => boolean }[] = [
  { id: "all", label: "Everything", test: () => true },
  { id: "failures", label: "Only failures and blocks", test: (e) => e.tone === "bad" },
  { id: "checks", label: "Only Splunk checks", test: (e) => e.kind === "check_pass" || e.kind === "check_fail" },
  { id: "proposals", label: "Only proposals", test: (e) => e.kind === "proposal" || e.kind === "guardrail_block" },
  { id: "human", label: "Only your actions", test: (e) => e.kind === "human_wait" || e.kind === "human_action" },
];

function ago(at: string, now: number): string {
  const t = Date.parse(at);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return new Date(t).toLocaleTimeString();
}

function FeedEntry({ e, now }: { e: Entry; now: number }) {
  return (
    <li className="grid grid-cols-[auto_1fr] gap-x-2.5 py-1.5" data-kind={e.kind}>
      <ActorAvatar id={e.actor} size="sm" />
      <div className="min-w-0 text-sm">
        <p className="flex items-start gap-1.5">
          <ToneIcon tone={e.tone} className="mt-0.5" label={e.tone === "good" ? "Pass." : e.tone === "bad" ? "Fail." : e.tone === "warn" ? "Attention." : undefined} />
          <span className="min-w-0 break-words">
            <ActorName id={e.actor} colored /> {said(e)}{" "}
            <time dateTime={e.at} className="whitespace-nowrap text-[12px] text-subtle">
              {ago(e.at, now)}
            </time>
          </span>
        </p>
        <TechDetail entry={e} label="Details" />
      </div>
    </li>
  );
}

/** The live activity, grouped by phase and then by attempt. Not a live region itself: only
 *  the Now banner announces (so a screen reader is not read every line). */
export function ActivityFeed({ job, entries }: { job: string; entries: Entry[] }) {
  const [who, setWho] = useState<ActorId | "all">("all");
  const [kind, setKind] = useState<KindFilter>("all");
  const [follow, setFollow] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const box = useRef<HTMLDivElement>(null);
  const count = useRef(entries.length);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(t);
  }, []);

  const shown = useMemo(() => {
    const test = KIND_FILTERS.find((k) => k.id === kind)!.test;
    return entries.filter((e) => (who === "all" || e.actor === who) && test(e));
  }, [entries, who, kind]);
  const sections = useMemo(() => feedSections(shown), [shown]);
  const present = useMemo(() => new Set(entries.map((e) => e.actor)), [entries]);

  useLayoutEffect(() => {
    const added = entries.length - count.current;
    count.current = entries.length;
    const el = box.current;
    if (!el) return;
    if (follow) el.scrollTop = el.scrollHeight;
    else if (added > 0) setUnseen((n) => n + added);
  }, [entries.length, follow, shown.length]);

  function onScroll() {
    const el = box.current;
    if (!el) return;
    const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setFollow(atEnd);
    if (atEnd) setUnseen(0);
  }

  function jump() {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
    setFollow(true);
    setUnseen(0);
  }

  return (
    <section aria-labelledby="activity-title" className="glass flex min-h-0 flex-col overflow-hidden">
      <div className="grid gap-2 border-b border-line p-3">
        <h2 id="activity-title" className="text-base font-semibold">
          Activity
        </h2>
        <div className="grid grid-cols-2 gap-2">
          <label className="grid gap-0.5 text-[13px] text-muted">
            Actor
            <select value={who} onChange={(e) => setWho(e.target.value as ActorId | "all")} className="h-8 rounded-md border border-line-strong bg-surface-2 px-1.5 text-sm text-fg">
              <option value="all">Everyone</option>
              {Object.values(ACTORS)
                .filter((a) => present.has(a.id))
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
          <label className="grid gap-0.5 text-[13px] text-muted">
            Show
            <select value={kind} onChange={(e) => setKind(e.target.value as KindFilter)} className="h-8 rounded-md border border-line-strong bg-surface-2 px-1.5 text-sm text-fg">
              {KIND_FILTERS.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="relative min-h-0 flex-1">
        <div ref={box} onScroll={onScroll} aria-label="Run activity" tabIndex={0} className="h-full max-h-[70vh] overflow-y-auto px-3 pb-2 xl:max-h-[calc(100vh-14rem)]">
          {sections.length === 0 && <p className="py-4 text-sm text-muted">{entries.length ? "Nothing matches these filters." : "No activity yet."}</p>}
          {sections.map((s) => (
            <section key={s.key} className="border-b border-line py-2 last:border-b-0" aria-label={s.phase ? STAGE_LABEL[s.phase] : "Run"}>
              <h3 className="sticky top-0 z-20 -mx-3 border-b border-line bg-surface-solid px-3 py-1.5 text-[13px] font-semibold text-muted">
                {s.phase ? (
                  <Link href={`/runs/${job}?phase=${s.phase}`} scroll={false} className="hover:underline">
                    {STAGE_LABEL[s.phase]}
                    {s.visit && s.visit > 1 ? " (second pass)" : ""}
                  </Link>
                ) : (
                  "Run"
                )}
              </h3>
              {s.groups.map((g, i) => (
                <div key={`${g.attempt}-${i}`}>
                  {g.attempt !== null && <p className="mt-1 text-[12px] font-medium uppercase tracking-wide text-subtle">Attempt {g.attempt}</p>}
                  <ol>
                    {g.entries.map((e) => (
                      <FeedEntry key={e.id} e={e} now={now} />
                    ))}
                  </ol>
                </div>
              ))}
            </section>
          ))}
        </div>
        {!follow && (
          <button
            type="button"
            onClick={jump}
            className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full border border-line-strong bg-surface-2 px-3 py-1 text-sm shadow-md hover:bg-surface-2"
          >
            <ArrowDown aria-hidden className="h-4 w-4" /> Jump to latest{unseen > 0 ? ` (${unseen} new)` : ""}
          </button>
        )}
      </div>
    </section>
  );
}
