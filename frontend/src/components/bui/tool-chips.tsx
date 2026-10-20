"use client";

import { useState, type ComponentType, type CSSProperties, type ReactNode } from "react";

import { Shimmer } from "@/components/bui/shimmer";
import { cn } from "@/lib/utils";

const EASE = "var(--ease-out-strong)";

function Chevron({ size = 12, className, style }: { size?: number; className?: string; style?: CSSProperties }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
      style={style}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function RowSpinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "size-3 shrink-0 animate-spin rounded-full border-[1.5px] border-line-strong border-t-ink-2",
        className,
      )}
    />
  );
}

export function ToolRun({
  label,
  meta,
  live,
  defaultOpen = true,
  children,
  footer,
}: {
  label: string;
  meta?: string;
  live: boolean;
  defaultOpen?: boolean;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="not-prose w-full min-w-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="-mx-1.5 flex w-fit max-w-full items-center gap-2 rounded-control px-1.5 py-1 transition-colors duration-100 hover:bg-hover-2"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill={live ? "var(--ink-2)" : "var(--ink-3)"}
          aria-hidden
          className="shrink-0"
        >
          <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
        </svg>
        <span role="status" className="contents">
          {live ? (
            <Shimmer duration={1.4} className="text-[13px] font-medium whitespace-nowrap tabular-nums">
              {label}
            </Shimmer>
          ) : (
            <span
              className="text-[13px] font-medium whitespace-nowrap text-ink-2 tabular-nums"
              style={{ animation: "fade-in 350ms ease-out both" }}
            >
              {label}
            </span>
          )}
        </span>
        {meta && !live && (
          <span className="text-[12px] whitespace-nowrap text-ink-3 tabular-nums">{meta}</span>
        )}
        <Chevron
          size={14}
          className="shrink-0 text-ink-3 transition-transform duration-300"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0)", transitionTimingFunction: EASE }}
        />
      </button>
      <div hidden={!open} style={{ animation: open ? "fade-in 200ms ease-out both" : undefined }}>
        <div className="mt-1 flex flex-col gap-1">{children}</div>
        {footer}
      </div>
    </div>
  );
}

export type DiffStat = { add: number; del: number };

export function DiffCounts({ stat, className }: { stat: DiffStat; className?: string }) {
  return (
    <span className={cn("shrink-0 font-mono text-[11px] tabular-nums", className)}>
      <span className="text-green">+{stat.add}</span>
      {stat.del > 0 && <span className="text-red"> −{stat.del}</span>}
    </span>
  );
}

export function ToolRow({
  icon: Icon,
  label,
  chip,
  chipMono = true,
  onChipClick,
  chipHref,
  meta,
  stat,
  status,
  open,
  onToggle,
  children,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  chip?: string;
  chipMono?: boolean;
  onChipClick?: () => void;
  chipHref?: string;
  meta?: ReactNode;
  stat?: DiffStat;
  status: "running" | "done" | "error";
  open: boolean;
  onToggle?: () => void;
  children?: ReactNode;
}) {
  const expandable = !!onToggle && !!children;
  const chipClass = cn(
    "inline-flex h-5.5 min-w-0 max-w-full items-center truncate rounded-chip bg-field px-1.5 text-[11.5px] text-ink-2 shadow-hairline",
    chipMono && "font-mono",
  );
  const glyph =
    status === "running" ? (
      <RowSpinner />
    ) : (
      <Icon
        className={cn(
          "size-[13px] transition-opacity duration-100",
          status === "error" ? "text-red" : "text-ink-3",
          expandable && "group-hover/row:opacity-0",
          expandable && open && "opacity-0",
        )}
      />
    );
  const lead = (
    <>
      <span className="relative flex size-4 shrink-0 items-center justify-center">
        {glyph}
        {expandable && (
          <Chevron
            className={cn(
              "absolute text-ink-3 transition-[opacity,transform] duration-150 group-hover/row:opacity-100",
              open ? "opacity-100" : "opacity-0",
              status === "running" && "hidden",
            )}
            style={{ transform: open ? "rotate(0deg)" : "rotate(-90deg)" }}
          />
        )}
      </span>
      <span className={cn("shrink-0 text-[12.5px] font-medium", status === "error" ? "text-red" : "text-ink")}>
        {label}
      </span>
    </>
  );
  const interactiveChip = chip && (onChipClick || chipHref);
  const chipNode = chip ? (
    onChipClick ? (
      <button
        type="button"
        onClick={onChipClick}
        title={chip}
        className={cn(chipClass, "cursor-pointer transition-colors duration-100 hover:bg-hover-2 hover:text-ink")}
      >
        <span className="truncate">{chip}</span>
      </button>
    ) : chipHref ? (
      <a
        href={chipHref}
        target="_blank"
        rel="noreferrer"
        title={chip}
        className={cn(chipClass, "transition-colors duration-100 hover:bg-hover-2 hover:text-ink")}
      >
        <span className="truncate">{chip}</span>
      </a>
    ) : (
      <span title={chip} className={chipClass}>
        <span className="truncate">{chip}</span>
      </span>
    )
  ) : null;
  const tail = (
    <>
      {stat && <DiffCounts stat={stat} />}
      {meta && (
        <span className="ml-auto shrink-0 pl-1 text-[11.5px] text-ink-3 tabular-nums">{meta}</span>
      )}
    </>
  );
  const rowClass =
    "group/row -mx-[3px] flex h-7 w-[calc(100%+6px)] min-w-0 items-center gap-2 rounded-control px-[3px] text-left transition-colors duration-100";

  return (
    <div style={{ animation: `fade-up 300ms ${EASE} both` }}>
      {expandable && !interactiveChip ? (
        <button type="button" aria-expanded={open} onClick={onToggle} className={cn(rowClass, "hover:bg-hover-2")}>
          {lead}
          {chipNode}
          {tail}
        </button>
      ) : (
        <div className={cn(rowClass, expandable && "hover:bg-hover-2")}>
          {expandable ? (
            <button
              type="button"
              aria-expanded={open}
              aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
              onClick={onToggle}
              className="flex shrink-0 items-center gap-2"
            >
              {lead}
            </button>
          ) : (
            lead
          )}
          {chipNode && <span className="flex min-w-0 flex-1">{chipNode}</span>}
          {tail}
        </div>
      )}
      {children && open && (
        <div
          className="mt-0.5 mb-1 ml-2 flex min-w-0 flex-col gap-2 border-l border-line py-0.5 pl-3.5"
          style={{ animation: `fade-up 250ms ${EASE} both` }}
        >
          {children}
        </div>
      )}
    </div>
  );
}

export function DiffChips({
  files,
  onSelect,
}: {
  files: { path: string; stat: DiffStat }[];
  onSelect?: (path: string) => void;
}) {
  if (files.length === 0) return null;
  return (
    <div className="mt-2.5 flex max-w-full flex-wrap gap-1.5 border-t border-line pt-2.5">
      {files.map((file, i) => {
        const name = file.path.split("/").pop() || file.path;
        const content = (
          <>
            <span className="min-w-0 truncate">{name}</span>
            <DiffCounts stat={file.stat} />
          </>
        );
        const cls =
          "inline-flex h-7 max-w-full items-center gap-2 rounded-chip bg-surface px-2 font-mono text-[11.5px] text-ink shadow-btn";
        const style = { animation: `pop-in 250ms ${EASE} ${Math.min(i, 8) * 60}ms both` };
        return onSelect ? (
          <button
            key={file.path}
            type="button"
            title={file.path}
            aria-label={`Open ${file.path}`}
            onClick={() => onSelect(file.path)}
            className={cn(cls, "transition-colors duration-100 hover:bg-hover")}
            style={style}
          >
            {content}
          </button>
        ) : (
          <span key={file.path} title={file.path} className={cls} style={style}>
            {content}
          </span>
        );
      })}
    </div>
  );
}
