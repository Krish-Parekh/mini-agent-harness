"use client";

import { useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export type TaskStatus = "pending" | "running" | "done" | "partial" | "failed";

const EASE = "var(--ease-out-strong)";

function SpinnerRing({ active, size = 24, children }: { active?: boolean; size?: number; children?: ReactNode }) {
  const stroke = 2;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} aria-hidden className={cn("absolute inset-0", active && "animate-spin")}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth={stroke} />
        {active && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--ink-3)"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${c * 0.28} ${c * 0.72}`}
          />
        )}
      </svg>
      <span className="relative text-[10.5px] font-semibold text-ink tabular-nums">{children}</span>
    </span>
  );
}

const BADGE_TONE = { red: "bg-red", green: "bg-green", orange: "bg-orange" } as const;

function Badge({ tone, size = 22, children }: { tone: keyof typeof BADGE_TONE; size?: number; children: ReactNode }) {
  return (
    <span
      className={cn("flex shrink-0 items-center justify-center rounded-full text-white", BADGE_TONE[tone])}
      style={{ width: size, height: size, animation: `pop-in 300ms ${EASE} both` }}
    >
      {children}
    </span>
  );
}

export function TaskBadge({ status, step, compact }: { status: TaskStatus; step?: ReactNode; compact?: boolean }) {
  const size = compact ? 16 : 22;
  if (status === "done") {
    return (
      <Badge tone="green" size={size}>
        <svg width={compact ? 10 : 13} height={compact ? 10 : 13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </Badge>
    );
  }
  if (status === "partial") {
    return (
      <Badge tone="orange" size={size}>
        <svg width={compact ? 9 : 12} height={compact ? 9 : 12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" aria-hidden>
          <path d="M9 6v12M15 6v12" />
        </svg>
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge tone="red" size={size}>
        <svg width={compact ? 9 : 12} height={compact ? 9 : 12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" aria-hidden>
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </Badge>
    );
  }
  return (
    <SpinnerRing active={status === "running"} size={compact ? 16 : 24}>
      {compact ? null : step}
    </SpinnerRing>
  );
}

export function StatusPill({ status }: { status: TaskStatus }) {
  if (status === "done") {
    return (
      <span className="inline-flex h-5.5 shrink-0 items-center rounded-full bg-green-tint px-2 text-[11.5px] font-medium text-green" style={{ animation: "fade-in 200ms ease-out both" }}>
        Completed
      </span>
    );
  }
  if (status === "partial") {
    return (
      <span className="inline-flex h-5.5 shrink-0 items-center rounded-full bg-orange-tint px-2 text-[11.5px] font-medium text-orange" style={{ animation: "fade-in 200ms ease-out both" }}>
        Partial
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex h-5.5 shrink-0 items-center rounded-full bg-red-tint px-2 text-[11.5px] font-medium text-red" style={{ animation: "fade-in 200ms ease-out both" }}>
        Failed
      </span>
    );
  }
  return null;
}

export function TaskRow({
  label,
  sub,
  amount,
  status,
  step,
  strike,
  index = 0,
  children,
}: {
  label: string;
  sub?: string;
  amount?: ReactNode;
  status: TaskStatus;
  step?: ReactNode;
  strike?: boolean;
  index?: number;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const expandable = !!children;
  const head = (
    <>
      <span className="flex size-6 shrink-0 items-center justify-center">
        <TaskBadge status={status} step={step} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={cn("truncate text-[13px] font-medium", strike ? "text-ink-3 line-through" : "text-ink")}>
          {label}
        </span>
        {sub && !open && <span className="truncate text-[12px] text-ink-3">{sub}</span>}
      </span>
      {amount != null && <span className="shrink-0 text-[12.5px] text-ink-2 tabular-nums">{amount}</span>}
      <StatusPill status={status} />
      {expandable && (
        <span aria-hidden className="-ml-1 flex size-6 shrink-0 items-center justify-center text-ink-3">
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="transition-transform duration-300"
            style={{ transform: open ? "rotate(180deg)" : "rotate(0)" }}
          >
            <path d="M6 9l6 6 6-6" />
          </svg>
        </span>
      )}
    </>
  );
  return (
    <div
      className="self-stretch border-b border-line transition-colors duration-150 last:border-0 hover:bg-inset"
      style={{ animation: `fade-up 450ms ${EASE} ${Math.min(index, 10) * 60}ms both` }}
    >
      {expandable ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
          className="flex min-h-11 w-full items-center gap-2.5 px-2.5 py-1.5 text-left"
        >
          {head}
        </button>
      ) : (
        <div className="flex min-h-11 w-full items-center gap-2.5 px-2.5 py-1.5">{head}</div>
      )}
      {expandable && open && (
        <div className="mb-2.5 grid grid-cols-[24px_1fr] gap-2.5 px-2.5" style={{ animation: `fade-up 300ms ${EASE} both` }}>
          <span aria-hidden className="mx-auto h-full w-px bg-line" />
          <div className="flex min-w-0 flex-col gap-1.5">{children}</div>
        </div>
      )}
    </div>
  );
}

export function TaskList({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("flex w-full flex-col", className)}>{children}</div>;
}
