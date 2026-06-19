# Backend API — curl testing guide

How to start the server and exercise every HTTP endpoint with `curl`.

## 1. Start the stack

```bash
# 1. Postgres (matches docker-compose.yml)
docker compose up -d db

# 2. Environment (copy and fill in OPENAI_API_KEY, optionally GitHub OAuth)
cp .env.example .env

# 3. API server — FastAPI app lives at backend.app:app
# Limit reload to backend/ + miniagent/ so agent edits under data/ don't restart the server.
uv run uvicorn backend.app:app --reload --port 8000 --reload-dir backend --reload-dir miniagent
```

The server listens on `http://127.0.0.1:8000` by default (`public_base_url` in
`miniagent/config.py`). Interactive docs are at `http://127.0.0.1:8000/docs`.

A convenience variable used throughout this guide:

```bash
BASE=http://127.0.0.1:8000
```

---

## 2. Conversations

A conversation owns a git worktree + branch and runs the agent. Most write
endpoints return the updated `ConversationInfo` object.

### Create a conversation

```bash
curl -s -X POST "$BASE/conversations" \
  -H 'Content-Type: application/json' \
  -d '{
        "repo": "owner/name",
        "branch": "main",
        "confirm_mode": "risky",
        "initial_message": "Add a hello world endpoint"
      }'
```

All fields are optional. Body shape (`CreateConversationRequest`):

| field             | type                                  | default    |
| ----------------- | ------------------------------------- | ---------- |
| `repo`            | string `"owner/name"` or null         | null       |
| `branch`          | string or null                        | null       |
| `workspace_dir`   | string or null                        | null       |
| `initial_message` | string or null                        | null       |
| `confirm_mode`    | `"never"` \| `"risky"` \| `"always"`  | `"risky"`  |

Grab the returned `id` for the calls below:

```bash
CID=<id-from-the-create-response>
```

### List / get

```bash
curl -s "$BASE/conversations"            # list all
curl -s "$BASE/conversations/$CID"       # one conversation
```

### Send a message

```bash
curl -s -X POST "$BASE/conversations/$CID/messages" \
  -H 'Content-Type: application/json' \
  -d '{"text": "Now write a test for it", "plan_mode": false}'
```

Body (`SendMessageRequest`): `text` (required), `model` (optional string),
`plan_mode` (bool, default `false`). Returns **409** if the conversation is
`waiting_for_confirmation` — use `/confirm` instead.

### Plan mode flow

```bash
# Generate a plan: send a message with plan_mode = true
curl -s -X POST "$BASE/conversations/$CID/messages" \
  -H 'Content-Type: application/json' \
  -d '{"text": "Refactor the auth module", "plan_mode": true}'

# Approve the produced plan to start implementing it
curl -s -X POST "$BASE/conversations/$CID/plan/approve"
```

`plan/approve` returns **409** if there is no plan, or if the conversation is
running / awaiting confirmation.

### Confirm or reject a risky action

When status is `waiting_for_confirmation`:

```bash
# approve
curl -s -X POST "$BASE/conversations/$CID/confirm" \
  -H 'Content-Type: application/json' \
  -d '{"approve": true}'

# reject with a reason
curl -s -X POST "$BASE/conversations/$CID/confirm" \
  -H 'Content-Type: application/json' \
  -d '{"approve": false, "reason": "Do not delete that file"}'
```

Returns **409** if the conversation is not actually waiting for confirmation.

### Stop a running conversation

```bash
curl -s -X POST "$BASE/conversations/$CID/stop"
```

### Inspect events and file changes

```bash
# Full event history (array of agent events)
curl -s "$BASE/conversations/$CID/events"

# Changed files in the worktree (path, +adds, -dels, status)
curl -s "$BASE/conversations/$CID/changes"

# Unified diff for one file (path is a query param)
curl -s "$BASE/conversations/$CID/changes/diff?path=src/main.py"

# List all files, and read one file's content
curl -s "$BASE/conversations/$CID/files"
curl -s "$BASE/conversations/$CID/files/content?path=src/main.py"
```

### Open a pull request

```bash
curl -s -X POST "$BASE/conversations/$CID/pr"
```

Requires the conversation to have a repo (**409** otherwise) and GitHub to be
connected (**401** otherwise — see §3).

### Delete

```bash
curl -s -X DELETE "$BASE/conversations/$CID"
# -> {"deleted": "<cid>"}  (404 if not found)
```

### Live updates (WebSocket, not curl)

Events and status stream over `ws://127.0.0.1:8000/conversations/$CID/ws`.
curl can't drive a WebSocket easily; use `websocat`:

```bash
websocat "ws://127.0.0.1:8000/conversations/$CID/ws"
```

---

## 3. GitHub (OAuth, prefix `/auth/github`)

Requires `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` in `.env`. The OAuth login
and callback are browser redirects, not curl targets — open them in a browser:

```
$BASE/auth/github/login      # redirects to GitHub, then back to /callback
```

The JSON endpoints are curl-friendly:

```bash
# Connection status
curl -s "$BASE/auth/github/status"
# -> {"connected": true|false, "login": "<username>|null"}

# List the connected user's repos (401 if not connected)
curl -s "$BASE/auth/github/repos"

# Import (fork) a repo into the user's account
curl -s -X POST "$BASE/auth/github/import" \
  -H 'Content-Type: application/json' \
  -d '{"repo": "https://github.com/owner/name"}'   # or "owner/name"

# Disconnect
curl -s -X POST "$BASE/auth/github/logout"
# -> {"connected": false}
```

---

## Tips

- Pipe through `jq` for readable JSON: `curl -s "$BASE/conversations" | jq`.
- Add `-i` to see status codes and headers (handy for the 409/401/404 cases).
- The auth token is held in process memory, so a server restart drops the
  GitHub connection and you'll need to re-run `/auth/github/login`.
