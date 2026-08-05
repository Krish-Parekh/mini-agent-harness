import { accessToken } from "@/lib/supabase";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type GitHubConnection = {
  connected: boolean;
  login: string | null;
  avatar_url: string | null;
  connected_at: string | null;
};

export type AuthUser = {
  id: string;
  email: string | null;
  avatar_url: string | null;
};

export type AuthState = { user: AuthUser; github: GitHubConnection };

export type Repo = {
  full_name: string;
  name: string;
  owner: string;
  private: boolean;
  default_branch: string;
  description: string | null;
  language: string | null;
  updated_at: string;
};

export type ConversationStatus =
  | "idle"
  | "running"
  | "waiting_for_confirmation"
  | "finished"
  | "error"
  | "stuck";

export type StepStatus = "pending" | "in_progress" | "done";

export type PlanStep = {
  title: string;
  files: string[];
  description: string;
  status: StepStatus;
};

export type PlanData = {
  title: string;
  steps: PlanStep[];
};

export type ConversationInfo = {
  id: string;
  status: ConversationStatus;
  workspace_dir: string;
  num_events: number;
  repo: string | null;
  branch: string | null;
  title: string | null;
  plan: PlanData | null;
  implementing_plan: boolean;
  pr_number: number | null;
  pr_url: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AgentEvent = {
  id: string;
  timestamp: number;
  source: string;
  kind: "message" | "action" | "observation" | "error" | string;
  role?: "user" | "assistant" | "system";
  text?: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  tool_call_id?: string;
  content?: string;
  error?: boolean;
  duration_ms?: number | null;
  details?: Record<string, unknown> | null;
  message?: string;
};

export type ChangedFile = {
  path: string;
  additions: number;
  deletions: number;
  status: "added" | "modified" | "deleted";
};

export type FileDiff = { path: string; patch: string };

export type FileContent = { path: string; content: string };

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`${status}: ${detail}`);
  }
}

const jsonHeaders = { "content-type": "application/json" };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await accessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return json<T>(await fetch(`${API}${path}`, { ...init, headers }));
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    ...(body === undefined
      ? {}
      : { headers: jsonHeaders, body: JSON.stringify(body) }),
  });

export type StreamFrame = { event: string; data: string; id: string | null };

function parseFrame(block: string): StreamFrame | null {
  let event = "message";
  let id: string | null = null;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "id") id = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n"), id } : null;
}

async function* readEventStream(
  path: string,
  lastEventId: string | null,
  signal: AbortSignal,
): AsyncGenerator<StreamFrame> {
  const token = await accessToken();
  const headers = new Headers({ Accept: "text/event-stream" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (lastEventId) headers.set("Last-Event-ID", lastEventId);

  const res = await fetch(`${API}${path}`, { headers, signal });
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, detail);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += value;
      let split = buffer.indexOf("\n\n");
      while (split !== -1) {
        const frame = parseFrame(buffer.slice(0, split));
        buffer = buffer.slice(split + 2);
        if (frame) yield frame;
        split = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

export const api = {
  syncAuth: (providerToken?: string | null) =>
    post<AuthState>("/auth/sync", { provider_token: providerToken ?? null }),

  me: () => request<AuthState>("/auth/me"),

  disconnectGitHub: () =>
    post<{ connected: boolean }>("/auth/github/disconnect"),

  repos: () => request<Repo[]>("/auth/github/repos"),

  importRepo: (repo: string) => post<Repo>("/auth/github/import", { repo }),

  createConversation: (body: { repo: string; branch?: string | null }) =>
    post<ConversationInfo>("/conversations", body),

  conversations: () => request<ConversationInfo[]>("/conversations"),

  deleteConversation: (id: string) =>
    request<{ deleted: string }>(`/conversations/${id}`, { method: "DELETE" }),

  conversation: (id: string) =>
    request<ConversationInfo>(`/conversations/${id}`),

  events: (id: string) => request<AgentEvent[]>(`/conversations/${id}/events`),

  sendMessage: (id: string, text: string, model?: string) =>
    post<ConversationInfo>(`/conversations/${id}/messages`, {
      text,
      ...(model ? { model } : {}),
    }),

  stop: (id: string) => post<ConversationInfo>(`/conversations/${id}/stop`),

  createPr: (id: string) => post<ConversationInfo>(`/conversations/${id}/pr`),

  approvePlan: (id: string) =>
    post<ConversationInfo>(`/conversations/${id}/plan/approve`),

  confirm: (id: string, approve: boolean, reason?: string) =>
    post<ConversationInfo>(`/conversations/${id}/confirm`, {
      approve,
      ...(reason ? { reason } : {}),
    }),

  changes: (id: string) => request<ChangedFile[]>(`/conversations/${id}/changes`),

  fileDiff: (id: string, path: string) =>
    request<FileDiff>(
      `/conversations/${id}/changes/diff?path=${encodeURIComponent(path)}`,
    ),

  files: (id: string) => request<string[]>(`/conversations/${id}/files`),

  fileContent: (id: string, path: string) =>
    request<FileContent>(
      `/conversations/${id}/files/content?path=${encodeURIComponent(path)}`,
    ),

  eventStream: (id: string, lastEventId: string | null, signal: AbortSignal) =>
    readEventStream(`/conversations/${id}/events/stream`, lastEventId, signal),
};
