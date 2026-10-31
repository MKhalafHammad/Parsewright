"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { RunWorkspace } from "@/components/run/run-workspace";

const JOB_ID = /^[a-z0-9]{4,16}$/;

export default function RunPage() {
  const params = useParams<{ id: string }>();
  if (!JOB_ID.test(params.id)) return <p role="alert" className="text-bad">Not a job id.</p>;
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <RunWorkspace key={params.id} id={params.id} />
    </Suspense>
  );
}
