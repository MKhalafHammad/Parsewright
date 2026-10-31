import { Cog, Hand, Sparkles } from "lucide-react";

import { actor, KIND_LABEL, type ActorId } from "@/lib/actors";
import { cn } from "@/lib/utils";

const SHAPE = {
  ai: "rounded-full border-2",
  code: "rounded-lg border-2",
  splunk: "rounded-sm border-2 outline outline-2 outline-offset-2",
  human: "rounded-full border-2 border-dashed",
} as const;

function Badge({ kind }: { kind: keyof typeof SHAPE }) {
  const cls = "absolute -bottom-1 -right-1 flex items-center justify-center rounded-full border border-line bg-surface text-fg";
  if (kind === "ai") return <span className={cn(cls, "h-4 w-4")}><Sparkles aria-hidden className="h-2.5 w-2.5" /></span>;
  if (kind === "code") return <span className={cn(cls, "h-4 w-4")}><Cog aria-hidden className="h-2.5 w-2.5" /></span>;
  if (kind === "human") return <span className={cn(cls, "h-4 w-4")}><Hand aria-hidden className="h-2.5 w-2.5" /></span>;
  return <span className={cn(cls, "h-4 px-0.5 text-[8px] font-bold leading-none")}>SPL</span>;
}

/** The actor's avatar. Decorative: the name is always shown next to it (ActorName/ActorChip). */
export function ActorAvatar({ id, size = "md", active = false }: { id: ActorId | string; size?: "sm" | "md" | "lg"; active?: boolean }) {
  const a = actor(id);
  const Icon = a.icon;
  const box = { sm: "h-6 w-6", md: "h-8 w-8", lg: "h-11 w-11" }[size];
  const icon = { sm: "h-3.5 w-3.5", md: "h-4 w-4", lg: "h-5 w-5" }[size];
  return (
    <span
      aria-hidden
      style={{ "--accent": a.accent, color: a.accent, borderColor: a.accent, outlineColor: a.accent } as React.CSSProperties}
      className={cn("relative inline-flex shrink-0 items-center justify-center bg-surface", box, SHAPE[a.kind], active && "pw-pulse")}
    >
      <Icon className={icon} />
      {size !== "sm" && <Badge kind={a.kind} />}
    </span>
  );
}

export function ActorName({ id, className }: { id: ActorId | string; className?: string }) {
  const a = actor(id);
  return (
    <span className={cn("font-medium", className)}>
      {a.name}
      <span className="sr-only"> ({KIND_LABEL[a.kind]})</span>
    </span>
  );
}

/** Avatar + name (+ optional tagline): the standard way to show who did something. */
export function ActorChip({ id, tagline = false, size = "sm", active = false }: { id: ActorId | string; tagline?: boolean; size?: "sm" | "md" | "lg"; active?: boolean }) {
  const a = actor(id);
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <ActorAvatar id={id} size={size} active={active} />
      <span className="min-w-0">
        <ActorName id={id} className="block truncate" />
        {tagline && (
          <span className="block text-[13px] text-subtle">
            {KIND_LABEL[a.kind]} · {a.tagline}
          </span>
        )}
      </span>
    </span>
  );
}
