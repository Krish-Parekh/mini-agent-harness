"use client";

import {
  GitBranchIcon,
  MoreHorizontalIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";

import { LANE_META, LANES, LaneIcon } from "@/components/lane-icon";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";
import { type ConversationInfo, type Lane } from "@/lib/api";
import { formatElapsed, relativeTime, useElapsed } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useConversations, useSetLane } from "@/lib/queries";

// The backend prefixes titles with "repo: "; drop it on cards since the repo is
// shown separately.
function cardLabel(c: ConversationInfo): string {
  const name = c.repo?.split("/").pop();
  if (name && c.title?.startsWith(`${name}: `)) {
    return c.title.slice(name.length + 2);
  }
  return c.title ?? `Chat ${c.id.slice(0, 6)}`;
}

function BoardCard({ c }: { c: ConversationInfo }) {
  const setLane = useSetLane();
  const running = c.status === "running" || c.status === "waiting_for_confirmation";
  const repoName = c.repo?.split("/").pop();

  // While a run is live, tick elapsed from the server-stamped start so it stays
  // correct across refreshes; idle cards just show how long ago they last moved.
  const runStart = running && c.run_started_at ? new Date(c.run_started_at).getTime() : null;
  const runElapsed = useElapsed(runStart, runStart != null);

  return (
    <div className="group relative rounded-lg border bg-card p-3 shadow-xs transition-colors hover:border-foreground/20">
      <Link href={`/chat/${c.id}`} className="block">
        <p className="line-clamp-2 pr-6 text-sm font-medium leading-snug">
          {cardLabel(c)}
        </p>
        <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
          {repoName && (
            <span className="flex min-w-0 items-center gap-1">
              <HugeiconsIcon icon={GitBranchIcon} className="size-3 shrink-0" />
              <span className="truncate">{repoName}</span>
            </span>
          )}
          <span className="ml-auto shrink-0 tabular-nums">
            {runStart != null ? (
              <span className="flex items-center gap-1 text-foreground">
                <Spinner className="size-3" />
                {formatElapsed(runElapsed)}
              </span>
            ) : (
              relativeTime(c.updated_at)
            )}
          </span>
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground/70">
          Created {relativeTime(c.created_at)}
        </p>
      </Link>

      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label="Move card"
          className="absolute right-2 top-2 rounded p-0.5 text-muted-foreground opacity-0 hover:bg-muted hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
        >
          <HugeiconsIcon icon={MoreHorizontalIcon} className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>Move to</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {LANES.filter((l) => l !== c.lane).map((l) => (
            <DropdownMenuItem
              key={l}
              disabled={setLane.isPending}
              onClick={() => setLane.mutate({ id: c.id, lane: l })}
            >
              <LaneIcon lane={l} />
              {LANE_META[l].label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function Column({ lane, items }: { lane: Lane; items: ConversationInfo[] }) {
  const meta = LANE_META[lane];
  return (
    <div className="flex h-full w-72 shrink-0 flex-col">
      <div className="mb-3 flex items-center gap-2">
        <span
          className={cn(
            "flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
            meta.tint,
          )}
        >
          <LaneIcon lane={lane} />
          {meta.label}
        </span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {items.length}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {items.length === 0 ? (
          <div className="rounded-lg border border-dashed py-8 text-center text-xs text-muted-foreground">
            Nothing here
          </div>
        ) : (
          items.map((c) => <BoardCard key={c.id} c={c} />)
        )}
      </div>
    </div>
  );
}

export default function BoardPage() {
  // Poll so lanes update as runs start and finish without a manual refresh.
  const { data, isPending, isError } = useConversations({ refetchInterval: 4000 });

  const byLane = (lane: Lane) => (data ?? []).filter((c) => c.lane === lane);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4">
        <SidebarTrigger />
        <h1 className="text-sm font-semibold">Board</h1>
      </header>

      {isError ? (
        <p className="p-6 text-sm text-muted-foreground">
          Couldn&apos;t load the board.
        </p>
      ) : isPending ? (
        <p className="p-6 text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="flex min-h-0 flex-1 gap-4 overflow-x-auto p-4">
          {LANES.map((lane) => (
            <Column key={lane} lane={lane} items={byLane(lane)} />
          ))}
        </div>
      )}
    </div>
  );
}
