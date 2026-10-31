"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { api, type TA } from "@/lib/api";

/** "New run" as a side sheet: every upload field and its hints, a new TA or an update. */
export function NewRunSheet({ open, onClose, tas, onQueued }: { open: boolean; onClose: () => void; tas: TA[]; onQueued: (message: string) => void }) {
  const [updateOf, setUpdateOf] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const form = new FormData(e.currentTarget);
      if (!(form.get("manifest") as File | null)?.size) form.delete("manifest");
      if (!form.get("update_of")) form.delete("update_of");
      const r = await api<{ job: string; duplicate: boolean; events: number; estimated_tokens: number }>("/uploads", { method: "POST", body: form });
      onQueued(
        r.duplicate
          ? `Already known: this log is job ${r.job}.`
          : `Job ${r.job} queued: ${r.events} events, about ${r.estimated_tokens.toLocaleString()} tokens.`,
      );
      setUpdateOf("");
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} sheet title="New run" description="One log source per job, raw as the device writes it.">
      <form onSubmit={submit} className="grid gap-4" aria-describedby="upload-help">
        <div className="grid gap-1">
          <Label htmlFor="file">Log file</Label>
          <Input id="file" name="file" type="file" required accept=".log,.txt,.json,.csv,.gz" />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="manifest">Truth manifest (.manifest.json)</Label>
          <Input id="manifest" name="manifest" type="file" accept=".json" />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="update_of">Update an existing TA (new log format)</Label>
          <select
            id="update_of"
            name="update_of"
            value={updateOf}
            onChange={(e) => setUpdateOf(e.target.value)}
            className="h-9 rounded-md border border-line-strong bg-surface px-2 text-sm text-fg"
          >
            <option value="">No: build a new TA</option>
            {tas.map((t) => (
              <option key={t.app} value={t.app}>
                {t.app} {t.current_version}
              </option>
            ))}
          </select>
        </div>
        <fieldset disabled={updateOf !== ""} className="grid gap-4 disabled:opacity-50">
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1">
              <Label htmlFor="vendor">Vendor</Label>
              <Input id="vendor" name="vendor" maxLength={40} placeholder="acme" />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="product">Product</Label>
              <Input id="product" name="product" maxLength={40} placeholder="vpn" />
            </div>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="tz">Timezone of the logs (if no offset)</Label>
            <Input id="tz" name="tz" maxLength={64} placeholder="UTC" />
          </div>
          <div className="flex items-center gap-2">
            <input id="auto_approve" name="auto_approve" type="checkbox" value="true" className="h-4 w-4" />
            <Label htmlFor="auto_approve">Skip profile review</Label>
          </div>
        </fieldset>
        <p id="upload-help" className="text-[13px] text-subtle">
          Checked before anything is stored: text, UTF-8, at least 50 events, at most 10 MB. An update keeps the TA&apos;s names and profile, and must pass on its old samples too.
        </p>
        <Button type="submit" disabled={busy}>
          {busy ? "Uploading…" : updateOf ? "Start update" : "Start run"}
        </Button>
        {error && (
          <p role="alert" className="text-sm text-bad">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}
