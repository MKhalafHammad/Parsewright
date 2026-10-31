// Settings as rows (file, stanza, key, value) and the comparison of two sets of rows, for
// display. Proposals arrive as JSON objects; the tested configuration arrives as .conf text
// written by the engine's escaping writer (one "key = value" per line, no continuations).
import type { ConfChange } from "@/lib/api";
import { str } from "@/lib/events";

export type Row = { file: string; stanza: string; key: string; value: string };
export type Change = ConfChange;

const CONF_SECTIONS = ["props", "transforms", "eventtypes", "tags"];

/** A stage proposal as rows. Index-time proposes flat props keys; later stages per conf file. */
export function proposalRows(settings: Record<string, unknown> | null, stanza = "this sourcetype"): Row[] {
  if (!settings) return [];
  const rows: Row[] = [];
  const sectioned = Object.keys(settings).some((k) => CONF_SECTIONS.includes(k));
  if (!sectioned) {
    for (const [key, v] of Object.entries(settings)) rows.push({ file: "props.conf", stanza, key, value: str(v) });
    return rows;
  }
  for (const section of CONF_SECTIONS) {
    const block = settings[section];
    if (!block || typeof block !== "object") continue;
    const entries = Object.entries(block as Record<string, unknown>);
    if (section === "props") {
      for (const [key, v] of entries) rows.push({ file: "props.conf", stanza, key, value: str(v) });
      continue;
    }
    for (const [name, inner] of entries) {
      if (inner && typeof inner === "object") {
        for (const [key, v] of Object.entries(inner as Record<string, unknown>))
          rows.push({ file: `${section}.conf`, stanza: name, key, value: str(v) });
      } else {
        rows.push({ file: `${section}.conf`, stanza: name, key: "", value: str(inner) });
      }
    }
  }
  return rows;
}

/** .conf text as rows. Comment lines are kept as rows with an empty key (shown as notes). */
export function confRows(file: string, text: string): Row[] {
  const rows: Row[] = [];
  let stanza = "default";
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const head = /^\[(.*)\]$/.exec(line);
    if (head) {
      stanza = head[1] ?? "";
      continue;
    }
    if (line.startsWith("#")) {
      rows.push({ file, stanza, key: "", value: line.replace(/^#\s?/, "") });
      continue;
    }
    const eq = line.indexOf("=");
    if (eq < 0) rows.push({ file, stanza, key: "", value: line });
    else rows.push({ file, stanza, key: line.slice(0, eq).trim(), value: line.slice(eq + 1).trim() });
  }
  return rows;
}

const id = (r: Pick<Row, "file" | "stanza" | "key">) => `${r.file}\u0000${r.stanza}\u0000${r.key}`;

/** before -> after, one row per setting, in after's order with removed rows where they were. */
export function diffRows(before: Row[], after: Row[]): Change[] {
  const a = new Map(before.map((r) => [id(r), r]));
  const b = new Map(after.map((r) => [id(r), r]));
  const out: Change[] = [];
  for (const r of before) {
    if (!b.has(id(r))) out.push({ file: r.file, stanza: r.stanza, key: r.key, before: r.value, after: null, change: "removed" });
  }
  for (const r of after) {
    const old = a.get(id(r));
    out.push({
      file: r.file,
      stanza: r.stanza,
      key: r.key,
      before: old ? old.value : null,
      after: r.value,
      change: !old ? "added" : old.value === r.value ? "unchanged" : "changed",
    });
  }
  return out;
}

export function summary(changes: Change[]): { changed: number; added: number; removed: number; unchanged: number } {
  const n = { changed: 0, added: 0, removed: 0, unchanged: 0 };
  for (const c of changes) n[c.change] += 1;
  return n;
}

/** Group rows by file, then stanza, keeping first-seen order. */
export function groupRows<T extends { file: string; stanza: string }>(rows: T[]): { file: string; stanzas: { stanza: string; rows: T[] }[] }[] {
  const files: { file: string; stanzas: { stanza: string; rows: T[] }[] }[] = [];
  for (const r of rows) {
    let f = files.find((x) => x.file === r.file);
    if (!f) files.push((f = { file: r.file, stanzas: [] }));
    let s = f.stanzas.find((x) => x.stanza === r.stanza);
    if (!s) f.stanzas.push((s = { stanza: r.stanza, rows: [] }));
    s.rows.push(r);
  }
  return files;
}

/** Rows from a stored unified diff, for update runs recorded before the engine kept structured
 *  `changes`. Only the lines the diff shows are known: shown context becomes "unchanged". */
export function changesFromUnified(diff: Record<string, string>): Change[] {
  const out: Change[] = [];
  for (const [path, text] of Object.entries(diff)) {
    const file = path.replace(/^default\//, "");
    let stanza = "default";
    const removed = new Map<string, number>(); // key -> index in out, within one stanza
    for (const raw of text.split("\n")) {
      if (raw.startsWith("---") || raw.startsWith("+++") || raw.startsWith("@@") || !raw) continue;
      const sign = raw[0];
      const line = raw.slice(1).trim();
      const head = /^\[(.*)\]$/.exec(line);
      if (head) {
        stanza = head[1] ?? "";
        removed.clear();
        continue;
      }
      const eq = line.indexOf("=");
      if (eq < 0 || line.startsWith("#")) continue;
      const key = line.slice(0, eq).trim();
      const value = line.slice(eq + 1).trim();
      if (sign === "-") {
        removed.set(key, out.length);
        out.push({ file, stanza, key, before: value, after: null, change: "removed" });
      } else if (sign === "+") {
        const at = removed.get(key);
        if (at !== undefined && out[at]) out[at] = { ...out[at]!, after: value, change: "changed" };
        else out.push({ file, stanza, key, before: null, after: value, change: "added" });
      } else {
        out.push({ file, stanza, key, before: value, after: value, change: "unchanged" });
      }
    }
  }
  return out;
}
