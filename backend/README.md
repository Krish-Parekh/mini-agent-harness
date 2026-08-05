# Backend API — curl testing guide

How to start the server and exercise every HTTP endpoint with `curl`.

## 1. Start the stack

```bash
# 1. Postgres (matches docker-compose.yml)
docker compose up -d db

# 2. Environment (copy and fill in OPENAI_API_KEY and the SUPABASE_* values)
cp .env.example .env

# 3. Schema. The app does not create or alter tables — it verifies the database is
# at the expected Alembic revision and refuses to start otherwise.
uv run alembic upgrade head

# 4. API server — FastAPI app lives at backend.app:app
# Limit reload to backend/ + miniagent/ so agent edits under data/ don't restart the server.
uv run uvicorn backend.app:app --reload --port 8000 --reload-dir backend --reload-dir miniagent
```

### Migrations

```bash
uv run alembic upgrade head       # apply
uv run alembic current            # what the database is stamped with
uv run alembic check              # models vs migrations — must be clean
uv run alembic revision --autogenerate -m "what changed"
```

After adding a revision, bump `EXPECTED_SCHEMA_REVISION` in `backend/core/db.py`;
`tests/test_migrations.py` fails if you forget.

A database created before ownership shipped has `conversations`/`events` but no
Alembic history, and its conversations have no owner. Those rows are discarded by
design (decision D2), so reset and migrate:

```bash
docker compose down -v && docker compose up -d db
uv run alembic upgrade head
```

The server listens on `http://127.0.0.1:8000`. Interactive docs are at
`http://127.0.0.1:8000/docs`.

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
Browsers can't set headers on a WebSocket, so the JWT rides in the subprotocol
list. curl can't drive a WebSocket easily; use `websocat`:

```bash
websocat -H='Sec-WebSocket-Protocol: bearer, '"$TOKEN" \
  "ws://127.0.0.1:8000/conversations/$CID/ws"
```

Closes with **4401** if the token is missing or invalid, **4404** if the
conversation is gone or belongs to someone else.

---

## 3. Auth (prefix `/auth`)

Sign-in is Supabase Auth with the GitHub provider — the OAuth dance happens in
the browser, so there is no curl target for it. Grab an access token from the
frontend (`supabase.auth.getSession()`) and export it:

```bash
TOKEN=<supabase access token>
AUTH=(-H "Authorization: Bearer $TOKEN")
```

```bash
# Create-or-update the caller, optionally attaching the GitHub provider token.
# This is the sign-up path: the users row is created on first call.
curl -s -X POST "$BASE/auth/sync" "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"provider_token": "gho_..."}'    # omit or null to sync identity only

# Current user + GitHub connection
curl -s "$BASE/auth/me" "${AUTH[@]}"
# -> {"user": {...}, "github": {"connected": true, "login": "...", ...}}

# Drop the stored GitHub token (the Supabase session is untouched)
curl -s -X POST "$BASE/auth/github/disconnect" "${AUTH[@]}"
# -> {"connected": false}

# List the caller's repos (401 if GitHub is not connected)
curl -s "$BASE/auth/github/repos" "${AUTH[@]}"

# Import (fork) a repo into the caller's account
curl -s -X POST "$BASE/auth/github/import" "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"repo": "https://github.com/owner/name"}'   # or "owner/name"
```

Every `/conversations` route needs `"${AUTH[@]}"` too — without it they return
**401**, and another user's conversation id returns **404**.

---

## Tips

- Pipe through `jq` for readable JSON: `curl -s "$BASE/conversations" "${AUTH[@]}" | jq`.
- Add `-i` to see status codes and headers (handy for the 409/401/404 cases).
- GitHub tokens are stored per user in `github_connections`, so a server restart
  no longer drops the connection. Supabase access tokens do expire (~1h) — pull a
  fresh one from the browser when curl starts returning 401.
