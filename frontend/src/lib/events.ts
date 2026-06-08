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

export const isMessage = (e: AgentEvent): e is MessageEvent =>
  e.kind === "message";

export const isAction = (e: AgentEvent): e is ActionEvent =>
  e.kind === "action";

export const isObservation = (e: AgentEvent): e is ObservationEvent =>
  e.kind === "observation";

export const isErrorEvent = (e: AgentEvent): e is ErrorEvent =>
  e.kind === "error";
