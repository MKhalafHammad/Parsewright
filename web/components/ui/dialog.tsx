"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

/** A modal on the native <dialog>: focus is trapped, Escape closes, the page behind is inert. */
export function Dialog({
  open,
  onClose,
  title,
  description,
  sheet = false,
  role,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  sheet?: boolean;
  role?: "alertdialog";
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      d.querySelector<HTMLElement>("[data-autofocus]")?.focus(); // React's autoFocus fires before showModal
    }
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      role={role}
      aria-labelledby="dlg-title"
      aria-describedby={description ? "dlg-desc" : undefined}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className={cn(
        "glass-strong p-0 text-fg shadow-2xl",
        sheet ? "pw-sheet" : "m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl",
      )}
    >
      {open && (
        <div className={cn("flex flex-col gap-4 p-5", sheet && "h-full overflow-y-auto")}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="dlg-title" className="text-lg font-semibold">
                {title}
              </h2>
              {description && (
                <p id="dlg-desc" className="mt-1 text-sm text-muted">
                  {description}
                </p>
              )}
            </div>
            <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1 text-muted hover:bg-surface-2">
              <X aria-hidden className="h-4 w-4" />
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
