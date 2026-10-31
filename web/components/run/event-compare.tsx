"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import type { Report, ReportEvent } from "@/lib/api";
import { fieldSlot, fieldStyle } from "@/lib/field-colors";
import { cn } from "@/lib/utils";

// Raw vs parsed. Log text is untrusted: highlights are React elements built from the (start,
// end) offsets the engine computed, and every piece is a text node (web/CLAUDE.md, T8.1).

type Hover = { field: string | null; set: (f: string | null) => void };

function RawLine({ event, names, hover }: { event: ReportEvent; names: string[]; hover: Hover }) {
  const raw = event.raw;
  const parts: React.ReactNode[] = [];
  let at = 0;
  for (const h of [...event.highlights].sort((a, b) => a.start - b.start)) {
    if (h.start < at || h.end > raw.length || h.end <= h.start) continue; // ignore bad spans
    if (h.start > at) parts.push(raw.slice(at, h.start));
    parts.push(
      <mark
        key={`${h.start}-${h.field}`}
        title={h.field}
        tabIndex={0}
        data-field={h.field}
        style={fieldStyle(fieldSlot(names, h.field))}
        onMouseEnter={() => hover.set(h.field)}
        onMouseLeave={() => hover.set(null)}
        onFocus={() => hover.set(h.field)}
        onBlur={() => hover.set(null)}
        className={cn("rounded px-0.5 text-fg", hover.field === h.field && "ring-2 ring-fg")}
      >
        {raw.slice(h.start, h.end)}
      </mark>,
    );
    at = h.end;
  }
  if (at < raw.length) parts.push(raw.slice(at));
  return <code className="block whitespace-pre-wrap break-all font-mono text-[13px] leading-6">{parts}</code>;
}

function utc(t: number): string {
  return new Date(t * 1000).toISOString().replace(".000Z", "Z").replace("T", " ").replace("Z", " UTC");
}

export function EventCompare({
  report,
  fieldOrder,
  tzNote,
  event: single,
  title = "Raw vs parsed",
}: {
  report?: Report;
  fieldOrder: string[];
  tzNote?: string;
  event?: ReportEvent;
  title?: string;
}) {
  const events = useMemo(() => (single ? [single] : (report?.events ?? [])), [single, report]);
  const [i, setI] = useState(0);
  const [view, setView] = useState<"parsed" | "cim">("parsed");
  const [field, setField] = useState<string | null>(null);
  const hover = { field, set: setField };
  const names = useMemo(() => {
    const all = [...fieldOrder];
    for (const e of events) for (const k of Object.keys(e.fields)) if (!all.includes(k)) all.push(k);
    return all;
  }, [events, fieldOrder]);
  const mapping = report?.mapping ?? [];
  const e = events[Math.min(i, events.length - 1)];
  if (!e) return <p className="text-sm text-muted">No events were recorded for this run.</p>;

  return (
    <section aria-label={title} className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" aria-label="Previous event" disabled={i === 0} onClick={() => setI(i - 1)}>
            <ChevronLeft aria-hidden className="h-4 w-4" />
          </Button>
          <p className="text-sm tabular-nums" aria-live="polite">
            Event {i + 1} of {events.length}
          </p>
          <Button size="sm" variant="outline" aria-label="Next event" disabled={i >= events.length - 1} onClick={() => setI(i + 1)}>
            <ChevronRight aria-hidden className="h-4 w-4" />
          </Button>
        </div>
        {mapping.length > 0 && (
          <div role="group" aria-label="View" className="flex rounded-md border border-line p-0.5">
            {(["parsed", "cim"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className={cn("rounded px-3 py-1 text-sm", view === v ? "bg-fg text-bg" : "text-muted hover:bg-surface-2")}
              >
                {v === "parsed" ? "Parsed fields" : "CIM view"}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="grid content-start gap-2">
          <h4 className="text-[13px] font-semibold text-muted">Raw line</h4>
          <div className="rounded-md border border-line bg-surface-2 p-3">
            <RawLine event={e} names={names} hover={hover} />
          </div>
          <p className="text-[13px] text-muted">
            <span className="text-subtle">_time (the timestamp Splunk assigned):</span> <span className="font-mono text-fg">{utc(e.time)}</span>
          </p>
          {tzNote && <p className="text-[13px] text-muted">{tzNote}</p>}
        </div>

        {view === "parsed" ? (
          <div className="grid content-start gap-2">
            <h4 className="text-[13px] font-semibold text-muted">Parsed fields</h4>
            <ul className="divide-y divide-line rounded-md border border-line" aria-label="Parsed fields">
              {names.map((n) => {
                const v = e.fields[n];
                const slot = fieldSlot(names, n);
                return (
                  <li
                    key={n}
                    tabIndex={0}
                    data-field={n}
                    onMouseEnter={() => setField(n)}
                    onMouseLeave={() => setField(null)}
                    onFocus={() => setField(n)}
                    onBlur={() => setField(null)}
                    className={cn("grid grid-cols-[auto_minmax(7rem,12rem)_1fr] items-start gap-x-3 px-3 py-1.5 text-sm", field === n && "bg-surface-2 ring-2 ring-inset ring-fg")}
                  >
                    <span aria-hidden className="mt-1 h-3.5 w-3.5 rounded-sm border" style={{ ...fieldStyle(slot), borderColor: `var(--f${slot}-s)` }} />
                    <span className="break-all font-mono text-[13px]">{n}</span>
                    {v === undefined ? (
                      <span className="text-subtle italic">not present in this event</span>
                    ) : (
                      <span className="min-w-0 break-words font-mono text-[13px]">
                        <span className="rounded px-0.5" style={fieldStyle(slot)}>
                          {v}
                        </span>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : (
          <div className="grid content-start gap-2">
            <h4 className="text-[13px] font-semibold text-muted">Raw value → source field → CIM field → normalised value</h4>
            <div className="overflow-x-auto rounded-md border border-line">
              <table className="w-full text-sm" aria-label="CIM view">
                <thead className="bg-surface-2 text-left text-[13px] text-muted">
                  <tr>
                    <th scope="col" className="px-3 py-1.5 font-medium">Raw value</th>
                    <th scope="col" className="px-3 py-1.5 font-medium">Source field</th>
                    <th scope="col" className="px-3 py-1.5 font-medium">CIM field</th>
                    <th scope="col" className="px-3 py-1.5 font-medium">Normalised value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {mapping.map((m) => {
                    const alias = m.kind === "FIELDALIAS";
                    const span = alias ? e.highlights.find((h) => h.field === m.from) : undefined;
                    const raw = span ? e.raw.slice(span.start, span.end) : alias ? e.fields[m.from] : undefined;
                    const out = e.fields[m.cim_field];
                    return (
                      <tr key={m.cim_field} className="align-top">
                        <td className="px-3 py-1.5 font-mono text-[13px] break-all">
                          {raw !== undefined ? (
                            <span className="rounded px-0.5" style={fieldStyle(fieldSlot(names, m.from))}>
                              {raw}
                            </span>
                          ) : (
                            <span className="font-sans text-subtle italic">{alias ? "not present" : "computed"}</span>
                          )}
                        </td>
                        <td className="px-3 py-1.5 text-[13px]">
                          {alias ? <span className="font-mono break-all">{m.from}</span> : <span><span className="text-subtle">Calculated: </span><span className="font-mono break-all">{m.from}</span></span>}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-[13px] break-all">{m.cim_field}</td>
                        <td className="px-3 py-1.5 font-mono text-[13px] break-all">{out ?? <span className="font-sans text-subtle italic">not present in this event</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
