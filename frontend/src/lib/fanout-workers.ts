import type { AgentEvent } from "@/lib/api";
import { isAction, isObservation } from "@/lib/events";

export type FanoutWorkerStatus = "pending" | "running" | "done" | "error";

export type FanoutWorkerState = {
  index: number;
  title: string;
  status: FanoutWorkerStatus;
  activity?: string;
};

type FanoutWorkerEvent = AgentEvent & {
  kind: "fanout_worker";
  parent_tool_call_id: string;
  worker_index: number;
  title: string;
  status: "running" | "done" | "error";
  activity?: string;
};

function isFanoutWorker(e: AgentEvent): e is FanoutWorkerEvent {
  return e.kind === "fanout_worker";
}

function parseFanoutObservation(content: string): FanoutWorkerState[] {
  const workers: FanoutWorkerState[] = [];
  const sections = content.split(/\n## /).slice(1);
  for (let i = 0; i < sections.length; i++) {
    const section = sections[i];
    const headerEnd = section.indexOf("\n");
    const header = headerEnd >= 0 ? section.slice(0, headerEnd) : section;
    const match = header.match(/^(.+?) \((\w+)\)$/);
    const title = match?.[1]?.trim() ?? header.trim();
    const rawStatus = match?.[2] ?? "idle";
    const status: FanoutWorkerStatus =
      rawStatus === "error" ? "error" : "done";
    workers.push({
      index: i,
      title,
      status,
      activity: status === "done" ? "Completed" : undefined,
    });
  }
  return workers;
}

/** Latest worker state per fanout tool call, for live + replayed conversations. */
export function buildFanoutWorkerMap(
  events: AgentEvent[],
): Map<string, FanoutWorkerState[]> {
  const byCall = new Map<string, Map<number, FanoutWorkerState>>();

  function ensure(callId: string, tasks: { title: string }[]) {
    if (!byCall.has(callId)) {
      const workers = new Map<number, FanoutWorkerState>();
      tasks.forEach((task, index) => {
        workers.set(index, {
          index,
          title: task.title,
          status: "pending",
        });
      });
      byCall.set(callId, workers);
    }
    return byCall.get(callId)!;
  }

  for (const event of events) {
    if (isAction(event) && event.tool_name === "fanout" && event.tool_call_id) {
      const tasks =
        (event.arguments?.tasks as { title: string }[] | undefined) ?? [];
      const workers = ensure(event.tool_call_id, tasks);
      for (const worker of workers.values()) {
        if (worker.status === "pending") worker.status = "running";
      }
    }

    if (isFanoutWorker(event)) {
      const workers = ensure(
        event.parent_tool_call_id,
        [{ title: event.title }],
      );
      workers.set(event.worker_index, {
        index: event.worker_index,
        title: event.title,
        status: event.status,
        activity: event.activity ?? undefined,
      });
    }

    if (
      isObservation(event) &&
      event.tool_name === "fanout" &&
      event.tool_call_id &&
      !event.error
    ) {
      const parsed = parseFanoutObservation(event.content ?? "");
      if (parsed.length > 0) {
        const workers = ensure(
          event.tool_call_id,
          parsed.map((w) => ({ title: w.title })),
        );
        for (const worker of parsed) {
          const existing = workers.get(worker.index);
          workers.set(worker.index, {
            ...worker,
            activity: existing?.activity ?? worker.activity,
          });
        }
      } else {
        const workers = byCall.get(event.tool_call_id);
        if (workers) {
          for (const worker of workers.values()) {
            if (worker.status !== "error") {
              worker.status = "done";
              worker.activity = worker.activity ?? "Completed";
            }
          }
        }
      }
    }
  }

  const result = new Map<string, FanoutWorkerState[]>();
  for (const [callId, workers] of byCall) {
    result.set(
      callId,
      [...workers.values()].sort((a, b) => a.index - b.index),
    );
  }
  return result;
}
