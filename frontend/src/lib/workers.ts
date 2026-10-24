import type { AgentEvent } from "@/lib/api";
import { type WorkerState, isWorkerEvent, isWorkerStatus } from "@/lib/events";

export type WorkerView = WorkerState & {
  startedAt: number;
  endedAt: number | null;
  events: AgentEvent[];
};

export function buildWorkers(events: AgentEvent[]): Map<string, WorkerView[]> {
  const workers = new Map<string, WorkerView>();
  const idsByCall = new Map<string, string[]>();
  for (const event of events) {
    if (isWorkerEvent(event)) {
      workers.get(event.worker_id)?.events.push(event.event);
      continue;
    }
    if (!isWorkerStatus(event)) continue;
    const known = workers.get(event.worker_id);
    if (!known) {
      idsByCall.set(event.parent_tool_call_id, [
        ...(idsByCall.get(event.parent_tool_call_id) ?? []),
        event.worker_id,
      ]);
    }
    workers.set(event.worker_id, {
      worker_id: event.worker_id,
      worker_kind: event.worker_kind,
      title: event.title,
      status: event.status,
      report: event.report,
      base: event.base,
      branch: event.branch,
      files: event.files,
      merged: event.merged,
      conflict: event.conflict,
      startedAt: known?.startedAt ?? event.timestamp,
      endedAt: known?.endedAt ?? (event.status === "running" ? null : event.timestamp),
      events: known?.events ?? [],
    });
  }
  return new Map(
    Array.from(idsByCall, ([callId, ids]) => [callId, ids.map((id) => workers.get(id)!)]),
  );
}
