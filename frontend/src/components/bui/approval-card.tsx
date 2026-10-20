"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function ApprovalIcon({ path, size = 14, sw = 2 }: { path: ReactNode; size?: number; sw?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={sw}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {path}
    </svg>
  );
}

export function ApprovalCard({
  children,
  footer,
  onDismiss,
  dismissLabel = "Dismiss",
  className,
}: {
  children: ReactNode;
  footer?: ReactNode;
  onDismiss?: () => void;
  dismissLabel?: string;
  className?: string;
}) {
  return (
    <div
      className={cn("relative w-full overflow-hidden rounded-card bg-surface shadow-card", className)}
      style={{ animation: "fade-up 380ms var(--ease-out-strong) both" }}
    >
      {onDismiss && (
        <button
          type="button"
          aria-label={dismissLabel}
          onClick={onDismiss}
          className="absolute top-2.5 right-2.5 z-10 inline-flex size-7 items-center justify-center rounded-control text-ink-3 transition-colors duration-100 hover:bg-hover hover:text-ink"
        >
          <ApprovalIcon size={14} sw={2.2} path={<path d="M18 6L6 18M6 6l12 12" />} />
        </button>
      )}
      <div className="p-3">{children}</div>
      {footer && <div className="flex items-center justify-between gap-3 p-2.5">{footer}</div>}
    </div>
  );
}

export function ChoiceMark({ type, on }: { type: "radio" | "check"; on: boolean }) {
  return (
    <span
      className={cn(
        "flex size-4 shrink-0 items-center justify-center transition-colors duration-200",
        type === "radio" ? "rounded-full" : "rounded-[5px]",
        on ? "bg-ink text-canvas" : "text-transparent shadow-[inset_0_0_0_1.5px_var(--line-strong)]",
      )}
    >
      {type === "radio" ? (
        <span
          className="size-1.5 rounded-full bg-canvas transition-transform duration-200"
          style={{ transform: on ? "scale(1)" : "scale(0)" }}
        />
      ) : (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M20 6L9 17l-5-5" />
        </svg>
      )}
    </span>
  );
}
