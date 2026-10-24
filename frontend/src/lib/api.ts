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

export type Branch = { name: string; default: boolean };

export type SandboxProvider = {
  id: string;
  label: string;
  available: boolean;
  default: boolean;
  reason: string | null;
};

export type AttachmentRef = {
  path: string;
  name: string;
  mime: string;
  size: number;
  kind: "image" | "file";
};

export type CreateConversationBody = {
  repo: string;
  branch?: string | null;
  sandbox_provider?: string | null;
  model?: string | null;
  initial_message?: string | null;
  attachments?: AttachmentRef[];
};

export type ConversationStatus =
  | "idle"
  | "running"
  | "waiting_for_confirmation"
  | "finished"
  | "error"
  | "stuck";

export type StepStatus = "pending" | "in_progress" | "done";

export type PrStep = "drafting" | "pushing" | "opening" | "done" | "failed";

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
  sandbox_provider: string;
  queued?: QueuedMessage[];
  created_at: string | null;
  updated_at: string | null;
};

export type QueuedMessage = { id: string; text: string };

export type AgentEvent = {
  id: string;
  timestamp: number;
  source: string;
  kind: "message" | "action" | "observation" | "error" | string;
  client_event_id?: string | null;
  role?: "user" | "assistant" | "system";
  text?: string;
  attachments?: AttachmentRef[];
  tool_name?: string;
  arguments?: Record<string, unknown>;
  tool_call_id?: string;
  content?: string;
  error?: boolean;
  duration_ms?: number | null;
  details?: Record<string, unknown> | null;
  message?: string;
  hidden_event_ids?: string[];
};

export type RewindResult = { text: string; attachments: AttachmentRef[] };

export type ChangedFile = {
  path: string;
  additions: number;
  deletions: number;
  status: "added" | "modified" | "deleted";
};

export type ContextNote = { text: string; at: number };

export type ConversationContext = {
  repo: string | null;
  branch: string | null;
  workspace_dir: string | null;
  sandbox_provider: string;
  sandbox_expired: boolean;
  model: string;
  status: ConversationStatus;
  workspace_sketch: ContextNote | null;
  repo_instructions: string[];
  condensation: ContextNote | null;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cached_prompt_tokens: number;
    cost_usd: number;
  };
  last_error: { message: string; trace_id: string | null; at: number } | null;
  session_changes: { files: number; additions: number; deletions: number };
  counts: { events: number; user_turns: number };
};

export type ContextCategoryName =
  | "System prompt"
  | "Tool definitions"
  | "Rules"
  | "Memory"
  | "Skills"
  | "MCP tools"
  | "Workspace"
  | "Conversation";

export type ContextWindow = {
  used: number;
  limit: number;
  categories: { name: ContextCategoryName; tokens: number }[];
};

export type Skill = {
  id: string;
  name: string;
  description: string;
  source_url: string | null;
  registry_id: string | null;
  repos: string[];
  created_at: string | null;
};

export type Memory = {
  id: string;
  repo: string | null;
  path: string;
  content: string;
  conversation_id: string | null;
  created_at: string;
  updated_at: string;
};

export type SkillHit = {
  id: string;
  source: string;
  skill_id: string;
  name: string;
  installs: number;
  description: string;
};

export type McpConnection = {
  id: string;
  name: string;
  url: string;
  auth_header: string | null;
  created_at: string | null;
};

export type McpTestResult = { ok: boolean; tools: string[]; error: string | null };

export type EnabledItem = {
  id: string;
  name: string;
  enabled: boolean;
  skipped: boolean;
};

export type FileDiff = { path: string; patch: string; truncated?: boolean };

export type TurnInfo = { id: string; text: string };

export type FileContent = { path: string; content: string };

async function readDetail(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  try {
    const body = JSON.parse(text);
    if (typeof body?.detail === "string") return body.detail;
  } catch {}
  return text;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new ApiError(res.status, await readDetail(res));
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
    throw new ApiError(res.status, await readDetail(res));
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

  branches: (repo: string) =>
    request<Branch[]>(`/auth/github/repos/${repo}/branches`),

  sandboxProviders: () => request<SandboxProvider[]>("/sandbox/providers"),

  createConversation: (body: CreateConversationBody) =>
    post<ConversationInfo>("/conversations", body),

  conversations: () => request<ConversationInfo[]>("/conversations"),

  deleteConversation: (id: string) =>
    request<{ deleted: string }>(`/conversations/${id}`, { method: "DELETE" }),

  conversation: (id: string) =>
    request<ConversationInfo>(`/conversations/${id}`),

  events: (id: string) => request<AgentEvent[]>(`/conversations/${id}/events`),

  sendMessage: (
    id: string,
    text: string,
    model?: string,
    clientEventId?: string,
    attachments: AttachmentRef[] = [],
    mode: "steer" | "queue" = "steer",
  ) =>
    post<ConversationInfo>(`/conversations/${id}/messages`, {
      text,
      attachments,
      mode,
      ...(model ? { model } : {}),
      ...(clientEventId ? { client_event_id: clientEventId } : {}),
    }),

  unqueue: (id: string, queuedId: string) =>
    request<ConversationInfo>(`/conversations/${id}/queue/${queuedId}`, { method: "DELETE" }),

  stop: (id: string) => post<ConversationInfo>(`/conversations/${id}/stop`),

  rewind: (id: string, messageId: string) =>
    post<RewindResult>(`/conversations/${id}/rewind`, { message_id: messageId }),

  createPr: (id: string) => post<ConversationInfo>(`/conversations/${id}/pr`),

  approvePlan: (id: string) =>
    post<ConversationInfo>(`/conversations/${id}/plan/approve`),

  confirm: (id: string, toolCallId: string, approve: boolean, reason?: string) =>
    post<ConversationInfo>(`/conversations/${id}/confirm`, {
      tool_call_id: toolCallId,
      approve,
      ...(reason ? { reason } : {}),
    }),

  context: (id: string) =>
    request<ConversationContext>(`/conversations/${id}/context`),

  contextWindow: (id: string) =>
    request<ContextWindow>(`/conversations/${id}/context/window`),

  skills: () => request<Skill[]>("/skills"),

  searchSkills: (q: string) =>
    request<SkillHit[]>(`/skills/search?q=${encodeURIComponent(q)}`),

  installSkill: (body: { source: string; skill_id: string; repo: string }) =>
    post<Skill>("/skills/install", body),

  setSkillRepo: (id: string, repo: string, enabled: boolean) =>
    request<Skill>(`/skills/${id}/repos`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify({ repo, enabled }),
    }),

  deleteSkill: (id: string) =>
    request<{ deleted: string }>(`/skills/${id}`, { method: "DELETE" }),

  memories: () => request<Memory[]>("/memories"),

  updateMemory: (id: string, content: string) =>
    request<Memory>(`/memories/${id}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify({ content }),
    }),

  deleteMemory: (id: string) =>
    request<{ deleted: string }>(`/memories/${id}`, { method: "DELETE" }),

  mcpConnections: () => request<McpConnection[]>("/mcp/connections"),

  createMcpConnection: (body: {
    name: string;
    url: string;
    auth_header?: string | null;
    auth_value?: string | null;
  }) => post<McpConnection>("/mcp/connections", body),

  deleteMcpConnection: (id: string) =>
    request<{ deleted: string }>(`/mcp/connections/${id}`, { method: "DELETE" }),

  testMcpConnection: (id: string) =>
    post<McpTestResult>(`/mcp/connections/${id}/test`),

  conversationMcp: (id: string) =>
    request<EnabledItem[]>(`/conversations/${id}/mcp`),

  setConversationMcp: (id: string, connectionId: string, enabled: boolean) =>
    request<EnabledItem>(`/conversations/${id}/mcp/${connectionId}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify({ enabled }),
    }),

  changes: (id: string, scope = "all") =>
    request<ChangedFile[]>(
      `/conversations/${id}/changes?scope=${encodeURIComponent(scope)}`,
    ),

  fileDiff: (id: string, path: string, scope = "all") =>
    request<FileDiff>(
      `/conversations/${id}/changes/diff?path=${encodeURIComponent(path)}&scope=${encodeURIComponent(scope)}`,
    ),

  turns: (id: string) => request<TurnInfo[]>(`/conversations/${id}/turns`),

  files: (id: string) => request<string[]>(`/conversations/${id}/files`),

  fileContent: (id: string, path: string) =>
    request<FileContent>(
      `/conversations/${id}/files/content?path=${encodeURIComponent(path)}`,
    ),

  eventStream: (id: string, lastEventId: string | null, signal: AbortSignal) =>
    readEventStream(`/conversations/${id}/events/stream`, lastEventId, signal),

  changesStream: (signal: AbortSignal) =>
    readEventStream("/conversations/changes/stream", null, signal),
};
