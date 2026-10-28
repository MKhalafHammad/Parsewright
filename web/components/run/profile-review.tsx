"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { postJson, type Profile } from "@/lib/api";

export function ProfileReview({ job, profile, onDone }: { job: string; profile: Profile; onDone: () => void }) {
  const [form, setForm] = useState({
    vendor: profile.vendor,
    product: profile.product,
    sourcetype: profile.sourcetype,
    tz: profile.timezone_hint ?? "",
  });
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

  const field = (id: keyof typeof form, label: string, hint?: string) => (
    <div className="grid gap-1">
      <Label htmlFor={`pr-${id}`}>{label}</Label>
      <Input id={`pr-${id}`} value={form[id]} onChange={(e) => setForm({ ...form, [id]: e.target.value })} aria-describedby={hint ? `pr-${id}-hint` : undefined} />
      {hint && (
        <p id={`pr-${id}-hint`} className="text-xs text-slate-500">
          {hint}
        </p>
      )}
    </div>
  );

  return (
    <Card className="border-amber-300">
      <CardHeader>
        <CardTitle>Profile review</CardTitle>
        <p className="text-sm text-slate-600">
          The Profiler read the samples. Check what it found, correct anything wrong, then confirm. The run continues from here.
        </p>
      </CardHeader>
      <CardContent>
        <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt className="text-slate-500">Format</dt>
          <dd>{profile.format}</dd>
          <dt className="text-slate-500">Timestamp example</dt>
          <dd className="font-mono text-xs">{profile.timestamp_example}</dd>
          <dt className="text-slate-500">Timezone in timestamp</dt>
          <dd>{profile.timezone_in_timestamp ? "yes" : "no: set it below"}</dd>
          <dt className="text-slate-500">Event types</dt>
          <dd>{profile.event_categories.join(", ")}</dd>
          <dt className="text-slate-500">CIM targets</dt>
          <dd>{profile.cim_targets.join(", ")}</dd>
          <dt className="text-slate-500">Fields</dt>
          <dd className="font-mono text-xs">{profile.fields.map((f) => f.name).join(", ")}</dd>
        </dl>
        <form onSubmit={confirm} className="grid gap-3 sm:grid-cols-2">
          {field("vendor", "Vendor")}
          {field("product", "Product")}
          {field("sourcetype", "Sourcetype", "vendor:product or vendor:product:type")}
          {field("tz", "Timezone", profile.timezone_in_timestamp ? "Not needed: timestamps carry an offset" : "IANA name, e.g. UTC or Asia/Tokyo")}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={busy}>
              {busy ? "Confirming…" : "Confirm profile"}
            </Button>
            {error && (
              <p role="alert" className="mt-2 text-sm text-red-700">
                {error}
              </p>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
