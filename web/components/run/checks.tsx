import { str, type Check, type Entry } from "@/lib/events";
import { ToneIcon } from "@/components/ui/status";

/** The Validator's checks: each with pass or fail, expected vs actual, up to 3 failing events. */
export function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="divide-y divide-line rounded-md border border-line">
      {checks.map((c, i) => (
        <li key={`${c.name}-${i}`} className="grid gap-1 px-3 py-2 text-sm">
          <div className="flex items-start gap-2">
            <ToneIcon tone={c.passed ? "good" : "bad"} className="mt-0.5" />
            <span className="min-w-0 flex-1">
              <span className="font-medium">{c.name}</span>{" "}
              <span className={c.passed ? "text-good" : "text-bad"}>{c.passed ? "Pass" : "Fail"}</span>
            </span>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 pl-6 text-[13px]">
            <dt className="text-subtle">Expected</dt>
            <dd className="min-w-0 break-words">{str(c.expected)}</dd>
            <dt className="text-subtle">Actual</dt>
            <dd className="min-w-0 break-words">{str(c.actual)}</dd>
          </dl>
          {!c.passed && c.examples.length > 0 && (
            <div className="pl-6">
              <p className="text-[13px] text-subtle">Failing events (up to 3)</p>
              <ul className="mt-1 grid gap-1">
                {c.examples.map((x, j) => (
                  <li key={j} className="rounded bg-surface-2 px-2 py-1 font-mono text-[12px] whitespace-pre-wrap break-all">
                    {x}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The engine's own line and the event's structured detail, verbatim, as text. */
export function TechDetail({ entry, label = "Technical detail" }: { entry: Entry; label?: string }) {
  const detail = Object.keys(entry.detail).length ? JSON.stringify(entry.detail, null, 2) : "";
  if (!entry.line && !detail) return null;
  return (
    <details className="group text-[13px]">
      <summary className="cursor-pointer text-subtle hover:text-fg">{label}</summary>
      <div className="pw-expand mt-1 grid gap-2 rounded-md border border-line bg-surface-2 p-2">
        {entry.line && <pre className="whitespace-pre-wrap break-all font-mono text-[12px]">{entry.line}</pre>}
        {detail && <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all font-mono text-[12px]">{detail}</pre>}
      </div>
    </details>
  );
}
