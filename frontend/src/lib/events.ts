import type { AgentEvent } from "@/lib/api";

export type MessageEvent = AgentEvent & {
  kind: "message";
  role: "user" | "assistant" | "system";
};

export type ActionEvent = AgentEvent & {
  kind: "action";
  tool_name: string;
  tool_call_id?: string;
  arguments?: Record<string, unknown>;
};

export type ObservationEvent = AgentEvent & {
  kind: "observation";
  tool_call_id?: string;
  content?: string;
  error?: boolean;
  details?: Record<string, unknown> | null;
};

export type ProviderFailure = {
  kind:
    | "usage_limit"
    | "provider_error"
    | "transport_error"
    | "permission_error"
    | "validation_error";
  retryable: boolean;
  reset_at: number | null;
};

export type ErrorEvent = AgentEvent & {
  kind: "error";
  message?: string;
  failure?: ProviderFailure | null;
};

export type WorkerKind = "explore" | "fork" | "research";

export type WorkerStatus = "running" | "done" | "failed" | "cancelled";

export type WorkerState = {
  worker_id: string;
  worker_kind: WorkerKind;
  title: string;
  status: WorkerStatus;
  report: string | null;
  base: string | null;
  branch: string | null;
  files: string[];
  merged: boolean;
  conflict: string | null;
};

export type WorkerStatusEvent = AgentEvent &
  WorkerState & {
    kind: "worker_status";
    parent_tool_call_id: string;
  };

export type WorkerEvent = AgentEvent & {
  kind: "worker";
  parent_tool_call_id: string;
  worker_id: string;
  event: AgentEvent;
};

export const isMessage = (e: AgentEvent): e is MessageEvent =>
  e.kind === "message";

export const isAction = (e: AgentEvent): e is ActionEvent =>
  e.kind === "action";

export const isObservation = (e: AgentEvent): e is ObservationEvent =>
  e.kind === "observation";

export const isErrorEvent = (e: AgentEvent): e is ErrorEvent =>
  e.kind === "error";

export const isWorkerStatus = (e: AgentEvent): e is WorkerStatusEvent =>
  e.kind === "worker_status";

export const isWorkerEvent = (e: AgentEvent): e is WorkerEvent =>
  e.kind === "worker";

export const eventKey = (e: AgentEvent) => e.client_event_id ?? e.id;
