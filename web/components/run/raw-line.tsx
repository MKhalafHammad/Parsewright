import type { Highlight } from "@/lib/api";

// Log text is untrusted. Highlights are built as React elements from (start, end) offsets the
// engine computed; every piece is a text node, never HTML (web/CLAUDE.md, threat T8.1).
const COLORS = ["bg-yellow-200", "bg-sky-200", "bg-lime-200", "bg-pink-200", "bg-orange-200", "bg-violet-200"];

export function RawLine({ raw, highlights }: { raw: string; highlights: Highlight[] }) {
  const parts: React.ReactNode[] = [];
  let at = 0;
  const fields = [...new Set(highlights.map((h) => h.field))];
  for (const h of [...highlights].sort((a, b) => a.start - b.start)) {
    if (h.start < at || h.end > raw.length || h.end <= h.start) continue; // ignore bad spans
    if (h.start > at) parts.push(raw.slice(at, h.start));
    parts.push(
      <mark key={`${h.start}-${h.field}`} title={h.field} className={`${COLORS[fields.indexOf(h.field) % COLORS.length]} rounded px-0.5`}>
        {raw.slice(h.start, h.end)}
      </mark>,
    );
    at = h.end;
  }
  if (at < raw.length) parts.push(raw.slice(at));
  return <code className="block whitespace-pre-wrap break-all font-mono text-xs">{parts}</code>;
}
