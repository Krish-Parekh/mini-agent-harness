# MiniAgent

MiniAgent is a coding agent that works on your GitHub repositories. You sign in with GitHub and select a repository. Then you give the agent a task in a chat. The agent reads the code, runs shell commands and edits files on its own branch. You review the diff, and the agent can open a pull request.

Each Conversation gets its own git worktree and branch. Two Conversations on the same repository do not change the same files. An append-only event log in Postgres stores every message, action and result, so you can open an old Conversation and replay it.

## System

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/system-dark.png">
  <img alt="Next.js UI calls FastAPI over REST and SSE. The agent loop runs in a worker thread, writes events to Postgres, and runs tools in a git worktree" src="docs/architecture/system.png">
</picture>

| Part | Does |
|---|---|
| `frontend/` | Next.js 16 UI. Lists repositories, streams the chat, and shows Session changes as a per-file diff |
| `backend/api` | FastAPI routes. Every request carries a Supabase JWT. Events stream to the browser over server-sent events |
| `backend/service` | Writes each event to Postgres through one queue. Loads a Conversation from the log after a server restart |
| `backend/runtime` | Starts each agent turn in a worker thread. Manages clones, worktrees, diffs and pull requests |
| `miniagent/` | The agent loop, its tools, the classifiers and the sandbox |

The browser reconnects to the stream with `Last-Event-ID`. The server then sends only the events that the browser did not get.

## One agent turn

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/turn-dark.png">
  <img alt="A user message goes through TaskClassifier, context, the LLM step and PolicyClassifier. Safe calls run at once. Mutating calls wait for the user. A stuck detector ends loops" src="docs/architecture/turn.png">
</picture>

1. `TaskClassifier` puts the request into a route: `question`, `code_edit`, `review` or `pr_flow`. Each route adds its own prompt.
2. The agent adds a sketch of the workspace files. When the history is longer than 60,000 characters, the agent writes a summary of the old events.
3. The model replies with text, tool calls, or both.
4. `PolicyClassifier` gives each `bash` command a risk level: `safe`, `mutating`, `dangerous` or `unknown`. A risky command stops the turn until the user approves or rejects it.
5. Calls that are safe to run together share a thread pool. Each result becomes an observation event.
6. `StuckDetector` reads the last 20 events. It stops the turn when the agent repeats the same action, fails again and again, or talks without action.

| Tool | Does |
|---|---|
| `bash` | Runs a shell command in the worktree |
| `file_edit` | Views, creates and edits files |
| `present_plan` · `update_plan` | Shows a plan for approval, then tracks its steps |
| `ask_user` | Asks the user a question and waits for the answer |
| `fanout` | Starts read-only workers in parallel and summarises what they find |
| `web_search` · `fetch_url` · `web_research` | Searches the web with Tavily. The agent gets these tools only when you set `TAVILY_API_KEY` |
| `finish` | Ends the task with a summary |

## Workspaces and pull requests

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/workspace-dark.png">
  <img alt="One shared clone per repository. Each Conversation adds a worktree on branch miniagent/{id}. Session changes come from git diff HEAD. Create PR commits, force-pushes the branch and opens a pull request" src="docs/architecture/workspace.png">
</picture>

The server clones each repository one time, under `data/repos/{owner}/{name}`. Each Conversation adds a worktree under `data/worktrees/{id}` on the branch `miniagent/{id}`. Worktrees share one object store, so a new Conversation does not clone again. A lock for each repository protects the clone and each `worktree add`.

Session changes come from `git diff HEAD` in the worktree. **Create PR** stages all files, makes a commit and force-pushes the branch. Then the GitHub REST API opens a pull request into the default branch. The GitHub token comes from the user's own OAuth sign-in. The server never writes the token to an event or a log.

## Sandboxes

By default the agent runs commands as host subprocesses. Set `MINIAGENT_SANDBOX_PROVIDER` to run them in Docker, E2B, Daytona, Modal, Vercel or a self-hosted SPACE deployment. Every provider passes the same contract tests. See [`sandbox/README.md`](sandbox/README.md).

## Stack

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/stack-dark.png">
  <img alt="Stack grouped by role: frontend, auth, models and search, backend, data and ops" src="docs/architecture/stack.png">
</picture>

## Run it

You need Docker, [uv](https://docs.astral.sh/uv/), Node.js 20.9 or later, and a Supabase project with the GitHub provider turned on.

```bash
make install
cp .env.example .env
cp frontend/.env.example frontend/.env.local
uv run alembic upgrade head
make dev
```

`make dev` starts Postgres, the API on port 8000 and the UI on port 3000.

| Variable | File | Needed for |
|---|---|---|
| `OPENAI_API_KEY` | `.env` | The agent model and both classifiers |
| `SUPABASE_URL` | `.env` | JWT checks on the API |
| `DATABASE_URL` | `.env` | The event log |
| `TAVILY_API_KEY` | `.env` | Web tools. Optional |
| `LANGFUSE_*` | `.env` | LLM traces. Optional |
| `NEXT_PUBLIC_SUPABASE_URL` · `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `frontend/.env.local` | Sign-in in the browser |
| `NEXT_PUBLIC_API_URL` | `frontend/.env.local` | The API address |

The default model is `gpt-4o-mini`. To change it, set `MINIAGENT_MODEL` and `MINIAGENT_POLICY_MODEL`. Both values go through LiteLLM, so any model that LiteLLM supports can work.

Tests:

```bash
uv run pytest
```

## Roadmap

- [x] Plan mode
- [x] Open a pull request at the end of a task
- [x] Postgres event store (`ConversationRow` and `EventRow` with JSONB)
- [ ] Condenser: keep the first and the most recent events. Set a token target for each model. Recover when the context window overflows
- [ ] Keep the GitHub token so that the agent can make commits
- [ ] Fan-out for sub-agents that can edit code
- [ ] Better recovery when a turn fails
- [x] Sandbox providers: Docker, E2B, Daytona, Modal, Vercel and SPACE behind the `Sandbox` interface
