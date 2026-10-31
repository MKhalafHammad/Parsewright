import { CircleMinus, CirclePlus, Pencil } from "lucide-react";

import { confKey, isCode } from "@/lib/conf-keys";
import { groupRows, summary, type Change, type Row } from "@/lib/settings-diff";
import { cn } from "@/lib/utils";

// Configuration as readable rows: file, then stanza, then one row per setting with a plain
// label, the raw key in small type and the value as wrapping text. Values are untrusted text
// nodes; monospace only where exact characters matter (patterns and expressions).

function KeyLabel({ k, brief = false }: { k: string; brief?: boolean }) {
  const info = confKey(k);
  if (!k) return <span className="text-[13px] text-subtle">Note</span>;
  return (
    <span className="block min-w-0">
      <span className="block font-medium">{info?.label ?? k}</span>
      {info && <span className="block break-all font-mono text-[12px] text-subtle">{k}</span>}
      {info && !brief && <span className="mt-0.5 block text-[13px] text-subtle">{info.description}</span>}
    </span>
  );
}

function Value({ k, v }: { k: string; v: string }) {
  if (!k) return <span className="text-muted italic">{v}</span>;
  return <span className={cn("block min-w-0 whitespace-pre-wrap break-words", isCode(k) && "font-mono text-[13px]")}>{v === "" ? "(empty)" : v}</span>;
}

function StanzaHead({ file, stanza }: { file: string; stanza: string }) {
  return (
    <p className="text-[13px] text-subtle">
      <span className="sr-only">{file}, </span>Stanza <span className="font-mono text-fg">{stanza}</span>
    </p>
  );
}

export function ConfigView({ rows, empty = "No settings." }: { rows: Row[]; empty?: string }) {
  if (!rows.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <div className="grid gap-4">
      {groupRows(rows).map((f) => (
        <section key={f.file} aria-label={f.file} className="grid gap-2">
          <h4 className="font-mono text-sm font-semibold">{f.file}</h4>
          {f.stanzas.map((s) => (
            <div key={s.stanza} className="grid gap-1">
              <StanzaHead file={f.file} stanza={s.stanza} />
              <dl className="divide-y divide-line rounded-md border border-line">
                {s.rows.map((r, i) => (
                  <div key={`${r.key}-${i}`} className="grid gap-x-4 gap-y-1 px-3 py-2 text-sm md:grid-cols-[minmax(12rem,18rem)_1fr]">
                    <dt>
                      <KeyLabel k={r.key} />
                    </dt>
                    <dd className="min-w-0">
                      <Value k={r.key} v={r.value} />
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

const CHANGE = {
  added: { icon: CirclePlus, word: "Added", row: "bg-good-bg border-l-good", tone: "text-good" },
  removed: { icon: CircleMinus, word: "Removed", row: "bg-bad-bg border-l-bad", tone: "text-bad" },
} as const;

function DiffRow({ c, side }: { c: Change; side: "added" | "removed" }) {
  const look = CHANGE[side];
  const Icon = c.change === "changed" ? Pencil : look.icon;
  const word = c.change === "changed" ? (side === "removed" ? "Changed, before" : "Changed, after") : look.word;
  const value = side === "removed" ? c.before : c.after;
  return (
    <div data-change={c.change} className={cn("grid gap-x-4 gap-y-1 border-l-4 px-3 py-2 text-sm md:grid-cols-[minmax(12rem,18rem)_1fr]", look.row)}>
      <div className="flex min-w-0 gap-2">
        <Icon aria-hidden className={cn("mt-0.5 h-4 w-4 shrink-0", look.tone)} />
        <span className="sr-only">{word}: </span>
        <KeyLabel k={c.key} brief={c.change === "changed" && side === "added"} />
      </div>
      <div className="min-w-0">
        <span aria-hidden className={cn("mb-0.5 block text-[12px] font-medium", look.tone)}>
          {c.change === "changed" ? (side === "removed" ? "Before" : "After") : look.word}
        </span>
        <Value k={c.key} v={value ?? ""} />
      </div>
    </div>
  );
}

function plural(n: number, w: string) {
  return `${n} ${w}${n === 1 ? "" : "s"}`;
}

/** Row-tinted diff. No unified-diff markers anywhere: icons, words and tints carry the meaning. */
export function SettingsDiff({ changes, label }: { changes: Change[]; label: string }) {
  const n = summary(changes);
  const moved = changes.filter((c) => c.change !== "unchanged");
  const same = changes.filter((c) => c.change === "unchanged");
  return (
    <section aria-label={label} className="grid gap-3" data-testid="settings-diff">
      <p className="text-sm font-medium">
        {plural(n.changed, "setting")} changed, {n.added} added, {n.removed} removed
      </p>
      {moved.length > 0 && (
        <div className="grid gap-3">
          {groupRows(moved).map((f) => (
            <div key={f.file} className="grid gap-2">
              <h4 className="font-mono text-sm font-semibold">{f.file}</h4>
              {f.stanzas.map((s) => (
                <div key={s.stanza} className="grid gap-1">
                  <StanzaHead file={f.file} stanza={s.stanza} />
                  <div className="grid gap-px overflow-hidden rounded-md border border-line">
                    {s.rows.map((c, i) =>
                      c.change === "changed" ? (
                        <div key={`${c.key}-${i}`} className="grid gap-px">
                          <DiffRow c={c} side="removed" />
                          <DiffRow c={c} side="added" />
                        </div>
                      ) : (
                        <DiffRow key={`${c.key}-${i}`} c={c} side={c.change === "removed" ? "removed" : "added"} />
                      ),
                    )}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
      {same.length > 0 && (
        <details className="rounded-md border border-line">
          <summary className="cursor-pointer px-3 py-2 text-sm text-muted">{plural(same.length, "unchanged setting")}</summary>
          <div className="pw-expand border-t border-line p-3">
            <ConfigView rows={same.map((c) => ({ file: c.file, stanza: c.stanza, key: c.key, value: c.after ?? "" }))} />
          </div>
        </details>
      )}
    </section>
  );
}
