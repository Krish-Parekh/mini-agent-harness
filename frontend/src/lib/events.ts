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
};

export type ErrorEvent = AgentEvent & {
  kind: "error";
  message?: string;
};

export type FanoutWorkerEvent = AgentEvent & {
  kind: "fanout_worker";
  parent_tool_call_id: string;
  worker_index: number;
  title: string;
  status: "running" | "done" | "error";
  activity?: string;
};

export const isMessage = (e: AgentEvent): e is MessageEvent =>
  e.kind === "message";

export const isAction = (e: AgentEvent): e is ActionEvent =>
  e.kind === "action";

export const isObservation = (e: AgentEvent): e is ObservationEvent =>
  e.kind === "observation";

export const isErrorEvent = (e: AgentEvent): e is ErrorEvent =>
  e.kind === "error";

export const isFanoutWorker = (e: AgentEvent): e is FanoutWorkerEvent =>
  e.kind === "fanout_worker";
