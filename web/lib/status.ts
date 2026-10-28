export function statusVariant(status: string): "running" | "waiting" | "good" | "bad" | "default" {
  if (["running", "promoting", "queued", "approved"].includes(status)) return "running";
  if (["profile_review", "awaiting_approval"].includes(status)) return "waiting";
  if (status === "done") return "good";
  if (["stage_failed", "error", "rejected", "smoke_failed", "promotion_failed"].includes(status)) return "bad";
  return "default";
}

export const STATUS_TEXT: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  profile_review: "Needs profile review",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  promoting: "Promoting",
  done: "Promoted",
  rejected: "Rejected",
  stage_failed: "Stage failed",
  error: "Error",
  smoke_failed: "Smoke test failed",
  promotion_failed: "Promotion failed",
};
