"use client";

import { PenLine, Undo2 } from "lucide-react";
import { useState } from "react";

import { ActorChip } from "@/components/actors/actor";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Meter } from "@/components/ui/status";
import { postJson, type Profile } from "@/lib/api";

/** What the Profiler found, read-only: format, timestamp, field coverage, CIM targets. */
export function ProfileFindings({ profile }: { profile: Profile }) {
  return (
    <div className="grid gap-4">
      <ActorChip id="profiler" size="md" tagline />
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-subtle">Format</dt>
        <dd>{profile.format}</dd>
        <dt className="text-subtle">Timestamp example</dt>
        <dd className="break-all font-mono text-[13px]">{profile.timestamp_example}</dd>
        <dt className="text-subtle">Timezone in the timestamp</dt>
        <dd>{profile.timezone_in_timestamp ? "Yes" : "No: the timezone below is applied"}</dd>
        <dt className="text-subtle">Event types</dt>
        <dd>{profile.event_categories.join(", ") || "none"}</dd>
        <dt className="text-subtle">CIM targets</dt>
        <dd>{profile.cim_targets.join(", ") || "none"}</dd>
      </dl>
      <div>
        <h4 className="mb-2 text-[13px] font-semibold text-muted">Fields, by share of sample events that carry them</h4>
        <ul className="grid gap-2 sm:grid-cols-2">
          {profile.fields.map((f) => (
            <li key={f.name}>
              <Meter label={f.name} value={f.coverage} max={1} text={`${Math.round(f.coverage * 100)}%`} tone={f.coverage >= 0.5 ? "run" : "warn"} />
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[13px] text-subtle">The Profiler gives no confidence score; the coverage bars show how often each field appears.</p>
      </div>
    </div>
  );
}

type Form = { vendor: string; product: string; sourcetype: string; tz: string };

export function ProfileReview({ job, profile, onDone }: { job: string; profile: Profile; onDone: () => void }) {
  const original: Form = { vendor: profile.vendor, product: profile.product, sourcetype: profile.sourcetype, tz: profile.timezone_hint ?? "" };
  const [form, setForm] = useState<Form>(original);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await postJson(`/runs/${job}/profile`, { ...form, tz: form.tz || null });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const field = (id: keyof Form, label: string, hint?: string) => {
    const changed = form[id] !== original[id];
    return (
      <div className={changed ? "grid gap-1 rounded-md border-l-4 border-warn bg-warn-bg p-2" : "grid gap-1 p-2"}>
        <Label htmlFor={`pr-${id}`}>{label}</Label>
        <Input
          id={`pr-${id}`}
          value={form[id]}
          onChange={(e) => setForm({ ...form, [id]: e.target.value })}
          aria-describedby={[hint ? `pr-${id}-hint` : "", changed ? `pr-${id}-changed` : ""].filter(Boolean).join(" ") || undefined}
        />
        {hint && (
          <p id={`pr-${id}-hint`} className="text-[13px] text-subtle">
            {hint}
          </p>
        )}
        {changed && (
          <p id={`pr-${id}-changed`} className="flex flex-wrap items-center gap-2 text-[13px]">
            <PenLine aria-hidden className="h-3.5 w-3.5 text-warn" />
            <span>
              You changed this. The Profiler said <span className="font-mono">{original[id] || "(empty)"}</span>.
            </span>
            <button type="button" onClick={() => setForm({ ...form, [id]: original[id] })} className="inline-flex items-center gap-1 underline underline-offset-2">
              <Undo2 aria-hidden className="h-3.5 w-3.5" /> Undo
            </button>
          </p>
        )}
      </div>
    );
  };

  return (
    <section aria-labelledby="pr-title" className="grid gap-6">
      <div>
        <h3 id="pr-title" className="text-base font-semibold">
          Profile review
        </h3>
        <p className="text-sm text-muted">The Profiler read the samples. Check what it found, correct anything wrong, then confirm. The run continues from here.</p>
      </div>
      <ProfileFindings profile={profile} />
      <form onSubmit={confirm} className="grid gap-2 sm:grid-cols-2">
        {field("vendor", "Vendor")}
        {field("product", "Product")}
        {field("sourcetype", "Sourcetype", "vendor:product or vendor:product:type")}
        {field("tz", "Timezone", profile.timezone_in_timestamp ? "Not needed: timestamps carry an offset" : "IANA name, e.g. UTC or Asia/Tokyo")}
        <div className="p-2 sm:col-span-2">
          <Button type="submit" disabled={busy}>
            {busy ? "Confirming…" : "Confirm profile"}
          </Button>
          {error && (
            <p role="alert" className="mt-2 text-sm text-bad">
              {error}
            </p>
          )}
        </div>
      </form>
    </section>
  );
}
