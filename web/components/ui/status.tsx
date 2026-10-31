import { Circle, CircleCheck, CircleX, Hand, LoaderCircle, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { Tone } from "@/lib/events";
import { STATUS_TEXT, statusVariant } from "@/lib/status";
import { cn } from "@/lib/utils";

const ICON = { running: LoaderCircle, waiting: Hand, good: CircleCheck, bad: CircleX, default: Circle } as const;

/** A job status in plain words, with an icon (never colour alone). */
export function StatusBadge({ status }: { status: string }) {
  const v = statusVariant(status);
  const Icon = ICON[v];
  return (
    <Badge variant={v}>
      <Icon aria-hidden className={cn("h-3.5 w-3.5", v === "running" && "motion-safe:animate-spin")} />
      {STATUS_TEXT[status] ?? status}
    </Badge>
  );
}

const TONE_ICON = { good: CircleCheck, bad: CircleX, warn: TriangleAlert, run: LoaderCircle, neutral: null } as const;
export const TONE_TEXT = { good: "text-good", bad: "text-bad", warn: "text-warn", run: "text-run", neutral: "text-muted" } as const;

/** A tone icon with a screen-reader word. */
export function ToneIcon({ tone, label, className }: { tone: Tone; label?: string; className?: string }) {
  const Icon = TONE_ICON[tone];
  if (!Icon) return null;
  return (
    <>
      <Icon aria-hidden className={cn("h-4 w-4 shrink-0", TONE_TEXT[tone], className)} />
      {label && <span className="sr-only">{label}</span>}
    </>
  );
}

/** A labelled meter: value against a maximum, with the numbers written out. */
export function Meter({ label, value, max, text, tone = "run" }: { label: string; value: number; max: number; text: string; tone?: Tone }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const bar = { good: "bg-good", bad: "bg-bad", warn: "bg-warn", run: "bg-run", neutral: "bg-muted" }[tone];
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 text-[13px]">
        <span className="text-muted">{label}</span>
        <span className="font-medium tabular-nums">{text}</span>
      </div>
      <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={Math.min(value, max)} aria-valuetext={text} className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div className={cn("h-full rounded-full", bar)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
