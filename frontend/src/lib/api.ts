export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type GitHubStatus = { connected: boolean; login: string | null };

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
  | "error";

export type ConversationInfo = {
  id: string;
  status: ConversationStatus;
  workspace_dir: string;
  num_events: number;
  repo: string | null;
  branch: string | null;
  title: string | null;
  updated_at: string | null;
};

export type AgentEvent = {
  id: string;
  timestamp: number;
  source: string;
  kind: "message" | "action" | "observation" | "error" | string;
  // message
  role?: "user" | "assistant" | "system";
  text?: string;
  // action / observation
  tool_name?: string;
  arguments?: Record<string, unknown>;
  tool_call_id?: string;
  content?: string;
  error?: boolean;
  // error
  message?: string;
};

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

export const api = {
  loginUrl: () => `${API}/auth/github/login`,

  githubStatus: () =>
    fetch(`${API}/auth/github/status`).then((r) => json<GitHubStatus>(r)),

  logout: () =>
    fetch(`${API}/auth/github/logout`, { method: "POST" }).then((r) =>
      json<{ connected: boolean }>(r),
    ),

  repos: () => fetch(`${API}/auth/github/repos`).then((r) => json<Repo[]>(r)),

  importRepo: (repo: string) =>
    fetch(`${API}/auth/github/import`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ repo }),
    }).then((r) => json<Repo>(r)),

  createConversation: (body: { repo: string; branch: string }) =>
    fetch(`${API}/conversations`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    }).then((r) => json<ConversationInfo>(r)),

  conversations: () =>
    fetch(`${API}/conversations`).then((r) => json<ConversationInfo[]>(r)),

  conversation: (id: string) =>
    fetch(`${API}/conversations/${id}`).then((r) => json<ConversationInfo>(r)),

  events: (id: string) =>
    fetch(`${API}/conversations/${id}/events`).then((r) => json<AgentEvent[]>(r)),

  sendMessage: (id: string, text: string, model?: string) =>
    fetch(`${API}/conversations/${id}/messages`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ text, ...(model ? { model } : {}) }),
    }).then((r) => json<ConversationInfo>(r)),

  confirm: (id: string, approve: boolean, reason?: string) =>
    fetch(`${API}/conversations/${id}/confirm`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ approve, ...(reason ? { reason } : {}) }),
    }).then((r) => json<ConversationInfo>(r)),

  wsUrl: (id: string) =>
    `${API.replace(/^http/, "ws")}/conversations/${id}/ws`,
};
