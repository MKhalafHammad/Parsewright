import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

// shadcn/ui Badge.
const badgeVariants = cva("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[13px] font-medium", {
  variants: {
    variant: {
      default: "bg-surface-2 text-fg",
      running: "bg-run-bg text-run",
      waiting: "bg-warn-bg text-warn",
      good: "bg-good-bg text-good",
      bad: "bg-bad-bg text-bad",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
