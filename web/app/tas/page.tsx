"use client";

import { useEffect, useState } from "react";

import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, type TA } from "@/lib/api";

/** Add-ons Parsewright promoted, with their versions (read-only). */
export default function Registry() {
  const [tas, setTas] = useState<TA[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<TA[]>("/tas")
      .then(setTas)
      .catch((e: Error) => setError(e.message));
  }, []);
  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-xl font-semibold">TA registry</h1>
        <p className="text-sm text-muted">Add-ons Parsewright promoted. Start a parser update from “New run” on the Runs page.</p>
      </div>
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}
      <section className="rounded-lg border border-line bg-surface">
        {tas === null ? (
          <p className="p-4 text-sm text-muted">Loading…</p>
        ) : tas.length === 0 ? (
          <p className="p-4 text-sm text-muted">Nothing promoted yet.</p>
        ) : (
          <Table aria-label="Promoted add-ons">
            <THead>
              <Tr>
                <Th scope="col" className="pl-4">Add-on</Th>
                <Th scope="col">Sourcetype</Th>
                <Th scope="col">Current version</Th>
                <Th scope="col">All versions</Th>
              </Tr>
            </THead>
            <TBody>
              {tas.map((t) => (
                <Tr key={t.app}>
                  <Td className="pl-4 font-mono text-[13px]">{t.app}</Td>
                  <Td className="font-mono text-[13px]">{t.sourcetype}</Td>
                  <Td>{t.current_version}</Td>
                  <Td className="text-[13px] text-muted">{t.versions.join(", ")}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </section>
    </div>
  );
}
