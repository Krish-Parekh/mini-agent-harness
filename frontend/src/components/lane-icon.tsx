import { type Lane } from "@/lib/api";
import { cn } from "@/lib/utils";

// Board lanes, in display order. `progress` drives the Linear-style circular
// glyph (empty ring -> partial pie -> fuller pie -> filled check); `text`/`tint`
// are the Intercom-style saturated accent used for the icon and the column pill.
export const LANES: readonly Lane[] = ["todo", "working", "review", "done"] as const;

export const LANE_META: Record<
  Lane,
  { label: string; progress: number; text: string; tint: string }
> = {
  todo: {
    label: "Todo",
    progress: 0,
    text: "text-muted-foreground",
    tint: "bg-muted text-muted-foreground",
  },
  working: {
    label: "Working",
    progress: 0.4,
    text: "text-amber-500",
    tint: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  },
  review: {
    label: "In Review",
    progress: 0.7,
    text: "text-violet-500",
    tint: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  },
  done: {
    label: "Done",
    progress: 1,
    text: "text-emerald-500",
    tint: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  },
};

const PROGRESS_R = 3;
const PROGRESS_C = 2 * Math.PI * PROGRESS_R;

export function LaneIcon({ lane, className }: { lane: Lane; className?: string }) {
  const { progress, text } = LANE_META[lane];

  return (
    <svg
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden
      className={cn("size-3.5 shrink-0", text, className)}
    >
      {lane === "done" ? (
        <>
          <circle cx="7" cy="7" r="7" fill="currentColor" />
          <path
            d="M4.4 7.2 6.1 9 9.7 4.9"
            stroke="white"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      ) : (
        <>
          <circle
            cx="7"
            cy="7"
            r="6"
            stroke="currentColor"
            strokeWidth="1.5"
            opacity={lane === "todo" ? 0.55 : 1}
          />
          {progress > 0 && (
            // A thick stroke on a small radius reads as a filled pie wedge.
            <circle
              cx="7"
              cy="7"
              r={PROGRESS_R}
              stroke="currentColor"
              strokeWidth={PROGRESS_R * 2}
              strokeDasharray={`${PROGRESS_C * progress} ${PROGRESS_C}`}
              transform="rotate(-90 7 7)"
            />
          )}
        </>
      )}
    </svg>
  );
}
