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
  // message
  role?: "user" | "assistant" | "system";
  text?: string;
  // action / observation
  tool_name?: string;
  arguments?: Record<string, unknown>;
  tool_call_id?: string;
  content?: string;
  error?: boolean;
  duration_ms?: number | null;
  details?: Record<string, unknown> | null;
  // error
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

export type SkillInfo = {
  name: string;
  description: string;
  scope: "repo" | "global";
  repo: string | null;
};

export type SkillBody = { name: string; content: string };

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

  createConversation: (body: { repo: string; branch?: string | null }) =>
    fetch(`${API}/conversations`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    }).then((r) => json<ConversationInfo>(r)),

  conversations: () =>
    fetch(`${API}/conversations`).then((r) => json<ConversationInfo[]>(r)),

  deleteConversation: (id: string) =>
    fetch(`${API}/conversations/${id}`, { method: "DELETE" }).then((r) =>
      json<{ deleted: string }>(r),
    ),

  conversation: (id: string) =>
    fetch(`${API}/conversations/${id}`).then((r) => json<ConversationInfo>(r)),

  events: (id: string) =>
    fetch(`${API}/conversations/${id}/events`).then((r) => json<AgentEvent[]>(r)),

  sendMessage: (id: string, text: string, model?: string, planMode?: boolean) =>
    fetch(`${API}/conversations/${id}/messages`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        text,
        ...(model ? { model } : {}),
        ...(planMode ? { plan_mode: true } : {}),
      }),
    }).then((r) => json<ConversationInfo>(r)),

  stop: (id: string) =>
    fetch(`${API}/conversations/${id}/stop`, { method: "POST" }).then((r) =>
      json<ConversationInfo>(r),
    ),

  createPr: (id: string) =>
    fetch(`${API}/conversations/${id}/pr`, { method: "POST" }).then((r) =>
      json<ConversationInfo>(r),
    ),

  approvePlan: (id: string) =>
    fetch(`${API}/conversations/${id}/plan/approve`, { method: "POST" }).then(
      (r) => json<ConversationInfo>(r),
    ),

  confirm: (id: string, approve: boolean, reason?: string) =>
    fetch(`${API}/conversations/${id}/confirm`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ approve, ...(reason ? { reason } : {}) }),
    }).then((r) => json<ConversationInfo>(r)),

  changes: (id: string) =>
    fetch(`${API}/conversations/${id}/changes`).then((r) =>
      json<ChangedFile[]>(r),
    ),

  fileDiff: (id: string, path: string) =>
    fetch(
      `${API}/conversations/${id}/changes/diff?path=${encodeURIComponent(path)}`,
    ).then((r) => json<FileDiff>(r)),

  files: (id: string) =>
    fetch(`${API}/conversations/${id}/files`).then((r) => json<string[]>(r)),

  fileContent: (id: string, path: string) =>
    fetch(
      `${API}/conversations/${id}/files/content?path=${encodeURIComponent(path)}`,
    ).then((r) => json<FileContent>(r)),

  skills: () => fetch(`${API}/skills`).then((r) => json<SkillInfo[]>(r)),

  // repo is a query param (not path) because repo full names contain a slash.
  skillBody: (name: string, repo?: string | null) => {
    const params = new URLSearchParams({ name });
    if (repo) params.set("repo", repo);
    return fetch(`${API}/skills/body?${params}`).then((r) => json<SkillBody>(r));
  },

  wsUrl: (id: string) =>
    `${API.replace(/^http/, "ws")}/conversations/${id}/ws`,
};
