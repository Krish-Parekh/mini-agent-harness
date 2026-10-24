"use client";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { ContextCategoryName, ContextWindow } from "@/lib/api";
import { cn } from "@/lib/utils";

const CATEGORY_COLORS: Record<ContextCategoryName, string> = {
  "System prompt": "bg-neutral-400",
  "Tool definitions": "bg-violet-400",
  Rules: "bg-emerald-500",
  Memory: "bg-teal-400",
  Skills: "bg-amber-400",
  "MCP tools": "bg-pink-300",
  Workspace: "bg-sky-400",
  Conversation: "bg-rose-400",
};

const RADIUS = 7;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function formatTokens(tokens: number) {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return String(tokens);
}

export function ContextWindowMeter({ usage }: { usage: ContextWindow }) {
  const fraction = Math.min(1, usage.used / usage.limit);
  const percent = Math.round(fraction * 100);
  const categories = usage.categories.filter((category) => category.tokens > 0);

  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={150}
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Context window ${percent}% full`}
          />
        }
      >
        <svg viewBox="0 0 18 18" className="size-4 -rotate-90" aria-hidden="true">
          <circle
            cx="9"
            cy="9"
            r={RADIUS}
            fill="none"
            strokeWidth="2.5"
            className="stroke-muted-foreground/25"
          />
          <circle
            cx="9"
            cy="9"
            r={RADIUS}
            fill="none"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE * (1 - fraction)}
            className={fraction > 0.9 ? "stroke-red" : "stroke-muted-foreground"}
          />
        </svg>
      </PopoverTrigger>
      <PopoverContent side="top" align="end" className="w-80 gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-medium">Context Usage</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            ~{formatTokens(usage.used)} / {formatTokens(usage.limit)} tokens
          </span>
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-xs text-muted-foreground tabular-nums">
            {percent}% full
          </span>
          <div
            className="flex h-1.5 gap-px overflow-hidden rounded-full bg-muted"
            role="img"
            aria-label={`${percent}% of the context window is used`}
          >
            {categories.map((category) => (
              <div
                key={category.name}
                className={CATEGORY_COLORS[category.name]}
                style={{ width: `${(category.tokens / usage.limit) * 100}%` }}
              />
            ))}
          </div>
        </div>
        <ul className="flex flex-col gap-1.5">
          {categories.map((category) => (
            <li key={category.name} className="flex items-center gap-2 text-sm">
              <span
                aria-hidden="true"
                className={cn("size-2.5 shrink-0 rounded-[3px]", CATEGORY_COLORS[category.name])}
              />
              <span className="flex-1 truncate">{category.name}</span>
              <span className="text-muted-foreground tabular-nums">
                {formatTokens(category.tokens)}
              </span>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
