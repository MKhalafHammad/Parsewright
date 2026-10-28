const STEPS = ["Profile", "Profile review", "Index-time", "Extraction", "CIM mapping", "Approval", "Promoted"];

function current(status: string, stageIndex: number | null, hasProfile: boolean): number {
  if (status === "done") return 7;
  if (["awaiting_approval", "approved", "promoting", "smoke_failed", "promotion_failed"].includes(status)) return 5;
  if (status === "profile_review") return 1;
  if (!hasProfile) return 0;
  return 2 + Math.min(stageIndex ?? 0, 2);
}

export function Stepper({ status, stageIndex, hasProfile }: { status: string; stageIndex: number | null; hasProfile: boolean }) {
  const at = current(status, stageIndex, hasProfile);
  const failed = ["stage_failed", "error", "rejected"].includes(status);
  return (
    <ol aria-label="Run progress" className="flex flex-wrap gap-2">
      {STEPS.map((s, i) => {
        const state = i < at ? "done" : i === at ? (failed ? "failed" : "current") : "todo";
        const style = {
          done: "bg-green-100 text-green-800",
          current: "bg-blue-600 text-white",
          failed: "bg-red-600 text-white",
          todo: "bg-slate-100 text-slate-500",
        }[state];
        return (
          <li key={s} aria-current={state === "current" ? "step" : undefined} className={`rounded-full px-3 py-1 text-xs font-medium ${style}`}>
            {i + 1}. {s}
          </li>
        );
      })}
    </ol>
  );
}
