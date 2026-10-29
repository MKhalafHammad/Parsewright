"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, type Job, type TA } from "@/lib/api";
import { STATUS_TEXT, statusVariant } from "@/lib/status";

export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tas, setTas] = useState<TA[]>([]);
  const [updateOf, setUpdateOf] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    api<Job[]>("/runs")
      .then(setJobs)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    api<TA[]>("/tas")
      .then(setTas)
      .catch(() => setTas([])); // no registry yet: new builds only
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const form = new FormData(e.currentTarget);
      if (!(form.get("manifest") as File | null)?.size) form.delete("manifest");
      if (!form.get("update_of")) form.delete("update_of");
      const r = await api<{
        job: string;
        duplicate: boolean;
        events: number;
        estimated_tokens: number;
      }>("/uploads", { method: "POST", body: form });
      setMessage(
        r.duplicate
          ? `Already known: this log is job ${r.job}.`
          : `Job ${r.job} queued: ${r.events} events, about ${r.estimated_tokens.toLocaleString()} tokens.`,
      );
      e.currentTarget.reset();
      setUpdateOf("");
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>New run</CardTitle>
          <p className="text-sm text-slate-600">
            One log source per job, raw as the device writes it.
          </p>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={submit}
            className="grid gap-3"
            aria-describedby="upload-help"
          >
            <div className="grid gap-1">
              <Label htmlFor="file">Log file</Label>
              <Input
                id="file"
                name="file"
                type="file"
                required
                accept=".log,.txt,.json,.csv,.gz"
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="manifest">Truth manifest (.manifest.json)</Label>
              <Input id="manifest" name="manifest" type="file" accept=".json" />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="update_of">
                Update an existing TA (new log format)
              </Label>
              <select
                id="update_of"
                name="update_of"
                value={updateOf}
                onChange={(e) => setUpdateOf(e.target.value)}
                className="h-9 rounded-md border border-slate-300 bg-white px-2 text-sm focus-visible:outline-2 focus-visible:outline-blue-600"
              >
                <option value="">No: build a new TA</option>
                {tas.map((t) => (
                  <option key={t.app} value={t.app}>
                    {t.app} {t.current_version}
                  </option>
                ))}
              </select>
            </div>
            <fieldset
              disabled={updateOf !== ""}
              className="grid gap-3 disabled:opacity-50"
            >
              <div className="grid grid-cols-2 gap-2">
                <div className="grid gap-1">
                  <Label htmlFor="vendor">Vendor</Label>
                  <Input
                    id="vendor"
                    name="vendor"
                    maxLength={40}
                    placeholder="acme"
                  />
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="product">Product</Label>
                  <Input
                    id="product"
                    name="product"
                    maxLength={40}
                    placeholder="vpn"
                  />
                </div>
              </div>
              <div className="grid gap-1">
                <Label htmlFor="tz">Timezone of the logs (if no offset)</Label>
                <Input id="tz" name="tz" maxLength={64} placeholder="UTC" />
              </div>
              <div className="flex items-center gap-2">
                <input
                  id="auto_approve"
                  name="auto_approve"
                  type="checkbox"
                  value="true"
                  className="h-4 w-4"
                />
                <Label htmlFor="auto_approve">Skip profile review</Label>
              </div>
            </fieldset>
            <p id="upload-help" className="text-xs text-slate-500">
              Checked before anything is stored: text, UTF-8, at least 50
              events, at most 10 MB. An update keeps the TA&apos;s names and profile,
              and must pass on its old samples too.
            </p>
            <Button type="submit" disabled={busy}>
              {busy ? "Uploading…" : updateOf ? "Start update" : "Start run"}
            </Button>
            <p
              role="status"
              aria-live="polite"
              className="text-sm text-green-800"
            >
              {message}
            </p>
            {error && (
              <p role="alert" className="text-sm text-red-700">
                {error}
              </p>
            )}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Jobs</CardTitle>
          <p className="text-sm text-slate-600">
            Updates every few seconds. Open a job to follow it live.
          </p>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <p className="text-sm text-slate-500">No jobs yet.</p>
          ) : (
            <Table aria-label="Jobs">
              <THead>
                <Tr>
                  <Th scope="col">Job</Th>
                  <Th scope="col">Source</Th>
                  <Th scope="col">Status</Th>
                  <Th scope="col">Tokens</Th>
                  <Th scope="col">Updated</Th>
                </Tr>
              </THead>
              <TBody>
                {jobs.map((j) => (
                  <Tr key={j.job}>
                    <Td>
                      <Link
                        className="font-mono underline"
                        href={`/runs/${j.job}`}
                      >
                        {j.job}
                      </Link>
                    </Td>
                    <Td className="font-mono text-xs">{j.source_key}</Td>
                    <Td>
                      <Badge variant={statusVariant(j.status)}>
                        {STATUS_TEXT[j.status] ?? j.status}
                      </Badge>
                    </Td>
                    <Td>{j.tokens.toLocaleString()}</Td>
                    <Td className="text-xs text-slate-500">
                      {new Date(j.updated_at).toLocaleTimeString()}
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
