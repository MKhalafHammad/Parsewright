import type { UpdateReview } from "@/lib/api";

import { RawLine } from "./raw-line";

// The parser-update part of the approval report: version, local/ overrides, diff, an old event.
// Everything here is rendered as text nodes (diff lines can contain log-derived regexes).
export function UpdateSection({ update }: { update: UpdateReview }) {
  return (
    <section
      aria-labelledby="update"
      className="grid gap-3 rounded-md border border-blue-200 bg-blue-50/40 p-3"
    >
      <h3 id="update" className="text-sm font-semibold">
        Parser update: {update.app} {update.version_from} → {update.version_to}
      </h3>
      <p className="text-sm text-slate-700">
        Patched: {update.patched.length ? update.patched.join(", ") : "nothing"}
        . Every check passed on the new samples and on every earlier
        version&apos;s samples. Promotion replaces default/ in place and keeps
        local/.
      </p>
      {update.overrides.length > 0 ? (
        <div
          role="alert"
          className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm"
        >
          <p className="mb-1 font-semibold">
            Overrides that would hide this fix
          </p>
          <ul className="list-disc pl-5">
            {update.overrides.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-slate-600">
          No local/ override touches the changed settings.
        </p>
      )}
      <ul className="list-disc pl-5 text-sm text-slate-700">
        {update.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
      {update.old_event && (
        <div>
          <p className="mb-1 text-xs text-slate-500">
            An old-format event, parsed by the update: _time{" "}
            {new Date(update.old_event.time * 1000)
              .toISOString()
              .replace(".000Z", "Z")}
          </p>
          <RawLine
            raw={update.old_event.raw}
            highlights={update.old_event.highlights}
          />
        </div>
      )}
      <div>
        <p className="mb-1 text-sm font-semibold">Diff against production</p>
        {Object.entries(update.diff).map(([file, text]) => (
          <details
            key={file}
            open
            className="mb-2 rounded-md border border-slate-200 bg-white"
          >
            <summary className="cursor-pointer px-3 py-2 font-mono text-xs">
              {file}
            </summary>
            <pre className="overflow-auto p-3 text-xs">
              {text.split("\n").map((line, i) => (
                <span
                  key={i}
                  className={
                    line.startsWith("+") && !line.startsWith("+++")
                      ? "block bg-green-50 text-green-900"
                      : line.startsWith("-") && !line.startsWith("---")
                        ? "block bg-red-50 text-red-900"
                        : "block"
                  }
                >
                  {line || " "}
                </span>
              ))}
            </pre>
          </details>
        ))}
      </div>
      <p className="text-xs text-slate-600">
        To undo after promotion:{" "}
        <code className="font-mono">{update.rollback}</code>
      </p>
    </section>
  );
}
