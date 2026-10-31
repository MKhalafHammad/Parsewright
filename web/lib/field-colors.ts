// One stable colour per field name, shared by its highlight in the raw line and its row in
// the parsed list (app/globals.css --f0..--f7, light and dark).
const SLOTS = 8;

export function fieldSlot(names: string[], name: string): number {
  const i = names.indexOf(name);
  if (i >= 0) return i % SLOTS;
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % SLOTS;
}

export function fieldStyle(slot: number): React.CSSProperties {
  return { backgroundColor: `var(--f${slot})`, "--swatch": `var(--f${slot}-s)` } as React.CSSProperties;
}
