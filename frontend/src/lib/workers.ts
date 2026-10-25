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
    const ids = idsByCall.get(event.parent_tool_call_id) ?? [];
    if (!ids.includes(event.worker_id)) {
      idsByCall.set(event.parent_tool_call_id, [...ids, event.worker_id]);
    }
    const known = workers.get(event.worker_id);
    const resumed = known !== undefined && known.status !== "running" && event.status === "running";
    workers.set(event.worker_id, {
      worker_id: event.worker_id,
      worker_kind: event.worker_kind,
      title: event.title,
      status: event.status,
      stop_reason: event.stop_reason ?? null,
      report: event.report,
      base: event.base,
      branch: event.branch,
      files: event.files,
      merged: event.merged,
      conflict: event.conflict,
      startedAt: resumed ? event.timestamp : (known?.startedAt ?? event.timestamp),
      endedAt: event.status === "running" ? null : (known?.endedAt ?? event.timestamp),
      events: known?.events ?? [],
    });
  }
  return new Map(
    Array.from(idsByCall, ([callId, ids]) => [callId, ids.map((id) => workers.get(id)!)]),
  );
}

export function uniqueWorkers(byCall: Map<string, WorkerView[]>): WorkerView[] {
  return Array.from(new Map(Array.from(byCall.values()).flat().map((w) => [w.worker_id, w])).values());
}
