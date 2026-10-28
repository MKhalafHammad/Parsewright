import type { LedgerEvent } from "@/lib/api";

// Ledger events as plain text lines. Worker log lines carry check results and evidence; they
// can contain log text, so they are only ever text nodes.
function line(e: LedgerEvent): string {
  if (e.event === "log") return String(e.data.line ?? "");
  if (e.event === "state") return `state → ${String(e.data.to)}`;
  if (e.event === "record") return `record → ${String(e.data.status)}`;
  if (e.event === "claimed") return `claimed by ${String(e.data.worker)} (from ${String(e.data.from)})`;
  return `${e.event} ${JSON.stringify(e.data)}`;
}

function tone(text: string): string {
  if (/\bFAIL\b|guardrail block|error|refused/i.test(text)) return "text-red-400";
  if (/\bPASS\b/.test(text)) return "text-green-400";
  if (/attempt \d|^cim attempt|backtrack/.test(text)) return "font-semibold text-white";
  return "text-slate-300";
}

export function Timeline({ events }: { events: LedgerEvent[] }) {
  return (
    <ol aria-label="Run timeline" aria-live="polite" className="max-h-[32rem] overflow-auto rounded-md bg-slate-950 p-3 font-mono text-xs leading-5">
      {events.map((e) => {
        const text = line(e);
        return (
          <li key={e.id} className={`whitespace-pre-wrap break-all ${tone(text)}`}>
            <span className="select-none text-slate-500">{new Date(e.at).toLocaleTimeString()} </span>
            {text}
          </li>
        );
      })}
    </ol>
  );
}
