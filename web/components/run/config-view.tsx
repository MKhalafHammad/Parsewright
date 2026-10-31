"use client";

import { CircleMinus, CirclePlus, Pencil } from "lucide-react";
import { useState } from "react";

import { confKey, isCode } from "@/lib/conf-keys";
import { groupRows, summary, type Change, type Row } from "@/lib/settings-diff";
import { cn } from "@/lib/utils";

// Configuration as the .conf file itself, in an editor-style pane: line numbers, syntax
// colours, a title bar and a status line. "Explain" adds a plain-language note under each
// known setting. Values are untrusted: every piece is a text node.

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

type Line = { kind: "stanza" | "kv" | "comment" | "blank"; key?: string; text: string; no?: number };

function linesOf(stanzas: { stanza: string; rows: Row[] }[]): Line[] {
  const out: Line[] = [];
  stanzas.forEach((s, i) => {
    if (i > 0) out.push({ kind: "blank", text: "" });
    out.push({ kind: "stanza", text: s.stanza });
    for (const r of s.rows) out.push(r.key ? { kind: "kv", key: r.key, text: r.value } : { kind: "comment", text: r.value });
  });
  let n = 0;
  return out.map((l) => (l.kind === "blank" ? l : { ...l, no: ++n }));
}

function Editor({ file, stanzas }: { file: string; stanzas: { stanza: string; rows: Row[] }[] }) {
  const [explain, setExplain] = useState(false);
  const lines = linesOf(stanzas);
  const n = lines.filter((l) => l.no).length;
  return (
    <section aria-label={file} className="overflow-hidden rounded-xl border border-line shadow-[0_12px_40px_-16px_rgb(0_0_0/0.8)]" style={{ background: "var(--ed-bg)" }}>
      <div className="flex items-center gap-3 border-b border-line bg-white/[0.04] px-3 py-2">
        <span aria-hidden className="flex gap-1.5">
          <span className="h-3 w-3 rounded-full bg-[#ff5f57]/80" />
          <span className="h-3 w-3 rounded-full bg-[#febc2e]/80" />
          <span className="h-3 w-3 rounded-full bg-[#28c840]/80" />
        </span>
        <h4 className="min-w-0 flex-1 truncate text-center font-mono text-[13px] text-muted">{file}</h4>
        <button
          type="button"
          aria-pressed={explain}
          onClick={() => setExplain(!explain)}
          className={cn("bubble rounded-full px-3 py-0.5 text-[12px]", explain ? "text-fg" : "text-muted")}
        >
          {explain ? "Hide explanations" : "Explain settings"}
        </button>
      </div>
      <div className="overflow-x-auto py-2 font-mono text-[13px] leading-6">
        {lines.map((l, i) => {
          const info = l.kind === "kv" ? confKey(l.key!) : null;
          return (
            <div key={i}>
              <div className="grid grid-cols-[3.25rem_1fr] hover:bg-white/[0.03]">
                <span aria-hidden className="select-none border-r border-line pr-3 text-right" style={{ color: "var(--ed-gutter)" }}>
                  {l.no ?? ""}
                </span>
                <span className="min-w-0 whitespace-pre-wrap break-all pl-3 pr-3">
                  {l.kind === "stanza" && (
                    <span style={{ color: "var(--ed-stanza)" }}>
                      [<span className="font-semibold">{l.text}</span>]
                    </span>
                  )}
                  {l.kind === "comment" && <span className="italic" style={{ color: "var(--ed-comment)" }}># {l.text}</span>}
                  {l.kind === "kv" && (
                    <>
                      <span title={info ? `${info.label}: ${info.description}` : undefined} style={{ color: "var(--ed-key)" }}>
                        {l.key}
                      </span>
                      <span style={{ color: "var(--ed-op)" }}> = </span>
                      <span style={{ color: "var(--ed-value)" }}>{l.text}</span>
                    </>
                  )}
                </span>
              </div>
              {explain && info && (
                <div className="grid grid-cols-[3.25rem_1fr]">
                  <span aria-hidden className="border-r border-line" />
                  <span className="pb-1 pl-3 pr-3 font-sans text-[12px] text-subtle">
                    <span className="font-medium text-muted">{info.label}.</span> {info.description}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex justify-between gap-3 border-t border-line bg-white/[0.04] px-3 py-1 font-mono text-[12px] text-subtle">
        <span>-- READ ONLY --</span>
        <span>
          {n} {n === 1 ? "line" : "lines"} · {stanzas.length} {stanzas.length === 1 ? "stanza" : "stanzas"}
        </span>
      </div>
    </section>
  );
}

export function ConfigView({ rows, empty = "No settings." }: { rows: Row[]; empty?: string }) {
  if (!rows.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <div className="grid gap-4">
      {groupRows(rows).map((f) => (
        <Editor key={f.file} file={f.file} stanzas={f.stanzas} />
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
