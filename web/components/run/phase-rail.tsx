"use client";

import { ChevronRight, Circle, CircleCheck, CircleDashed, CircleX, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useRef } from "react";

import { ActorAvatar } from "@/components/actors/actor";
import { actor } from "@/lib/actors";
import type { PhaseId } from "@/lib/events";
import { STATE_TEXT, type Phase, type PhaseState } from "@/lib/phases";
import { cn } from "@/lib/utils";

const STATE_ICON: Record<PhaseState, { icon: typeof Circle; cls: string }> = {
  done: { icon: CircleCheck, cls: "text-good" },
  current: { icon: LoaderCircle, cls: "text-run motion-safe:animate-spin" },
  failed: { icon: CircleX, cls: "text-bad" },
  skipped: { icon: CircleDashed, cls: "text-subtle" },
  todo: { icon: Circle, cls: "text-subtle" },
};

/** The clickable phase rail. Arrow keys, Home and End move along it; Enter opens a phase. */
export function PhaseRail({ job, phases, selected }: { job: string; phases: Phase[]; selected: PhaseId }) {
  const list = useRef<HTMLOListElement>(null);
  function onKey(e: React.KeyboardEvent) {
    const links = [...(list.current?.querySelectorAll<HTMLAnchorElement>("a[data-phase]") ?? [])];
    const i = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (i < 0) return;
    const next = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: links.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    links[(next + links.length) % links.length]?.focus();
  }
  return (
    <nav aria-label="Phases" className="overflow-x-auto rounded-lg border border-line bg-surface">
      <ol ref={list} onKeyDown={onKey} className="flex min-w-max items-stretch">
        {phases.map((p, i) => {
          const s = STATE_ICON[p.state];
          const Icon = s.icon;
          const on = p.id === selected;
          return (
            <li key={p.id} className="flex items-center">
              {i > 0 && <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle" />}
              <Link
                data-phase={p.id}
                href={`/runs/${job}?phase=${p.id}`}
                scroll={false}
                aria-current={on ? "page" : undefined}
                className={cn(
                  "m-1 flex items-center gap-2 rounded-md border-b-2 px-3 py-2 text-sm hover:bg-surface-2",
                  on ? "border-b-fg bg-surface-2" : "border-b-transparent",
                )}
              >
                <ActorAvatar id={p.owner} size="sm" active={p.state === "current"} />
                <span className="grid text-left leading-tight">
                  <span className={cn("font-medium", on && "underline underline-offset-4")}>{p.label}</span>
                  <span className="flex items-center gap-1 text-[12px] text-muted">
                    <Icon aria-hidden className={cn("h-3.5 w-3.5", s.cls)} />
                    {p.note ?? STATE_TEXT[p.state]}
                    {p.attempts > 0 && ` · ${p.attempts} ${p.attempts === 1 ? "attempt" : "attempts"}`}
                    <span className="sr-only">, owned by {actor(p.owner).name}</span>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
