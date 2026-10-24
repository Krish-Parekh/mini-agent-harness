"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import type { AgentEvent, ConversationStatus } from "@/lib/api";
import { type WorkerKind, type WorkerStatus, isAction, isObservation } from "@/lib/events";
import { formatDuration, formatElapsed, useElapsed } from "@/lib/time";
import { toolView } from "@/lib/tool-views";
import type { WorkerView } from "@/lib/workers";
import { TaskBadge, type TaskStatus } from "@/components/bui/task-rows";
import { ValuePill } from "@/components/bui/value-pill";

export const WORKER_STATUS: Record<WorkerStatus, TaskStatus> = {
  running: "running",
  done: "done",
  failed: "failed",
  cancelled: "failed",
};

export const WORKER_CONVERSATION_STATUS: Record<WorkerStatus, ConversationStatus> = {
  running: "running",
  done: "finished",
  failed: "error",
  cancelled: "idle",
};

export const WORKER_TONE: Record<WorkerKind, "brand" | "orange" | "neutral"> = {
  fork: "brand",
  explore: "neutral",
  research: "orange",
};

export function workerOutcome(worker: WorkerView): string | null {
  if (worker.merged) return "Merged into the workspace";
  if (worker.conflict) return `Conflicted with the workspace, kept on ${worker.branch}`;
  if (worker.files.length > 0) return `Not merged, kept on ${worker.branch}`;
  return null;
}

export function workerObservations(worker: WorkerView): Map<string, AgentEvent> {
  const observations = new Map<string, AgentEvent>();
  for (const event of worker.events) {
    if (isObservation(event) && event.tool_call_id) observations.set(event.tool_call_id, event);
  }
  return observations;
}

export function useWorkerDuration(worker: WorkerView): string {
  const running = worker.status === "running";
  const elapsed = useElapsed(running ? worker.startedAt * 1000 : null, running);
  return running
    ? formatElapsed(elapsed)
    : formatDuration(((worker.endedAt ?? worker.startedAt) - worker.startedAt) * 1000);
}

function WorkerCard({ worker, href }: { worker: WorkerView; href: string }) {
  const duration = useWorkerDuration(worker);
  const latest = worker.events.findLast(isAction);
  const latestView = latest ? toolView(latest) : undefined;
  const outcome = worker.status === "running" ? null : workerOutcome(worker);

  return (
    <li className="min-w-0">
      <Link
        href={href}
        className="flex w-full min-w-0 flex-col gap-0.5 rounded-control bg-surface px-2.5 py-2 shadow-hairline transition-colors duration-100 hover:bg-hover-2"
      >
        <span className="flex w-full min-w-0 items-center gap-2">
          <TaskBadge compact status={WORKER_STATUS[worker.status]} />
          <span className="min-w-0 truncate text-[12.5px] font-medium text-ink">{worker.title}</span>
          <ValuePill tone={WORKER_TONE[worker.worker_kind]} className="shrink-0">
            {worker.worker_kind}
          </ValuePill>
          <span className="ml-auto shrink-0 text-[11.5px] text-ink-3 tabular-nums">{duration}</span>
        </span>
        {(outcome || latestView) && (
          <span className="truncate pl-6 text-[12px] text-ink-3">
            {outcome ??
              `${latestView?.verb ?? ""}${latestView?.target ? ` ${latestView.target}` : ""}`}
          </span>
        )}
      </Link>
    </li>
  );
}

export function WorkerCards({ workers }: { workers: WorkerView[] }) {
  const { id } = useParams<{ id: string }>();
  const ended = workers.filter((w) => w.status !== "running").length;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <p className="text-[12px] font-medium text-ink-2 tabular-nums">
        {ended}/{workers.length} worker{workers.length === 1 ? "" : "s"} finished
      </p>
      <ul className="flex min-w-0 flex-col gap-1.5">
        {workers.map((worker) => (
          <WorkerCard
            key={worker.worker_id}
            worker={worker}
            href={`/chat/${id}/workers/${worker.worker_id}`}
          />
        ))}
      </ul>
    </div>
  );
}
