# Sandboxes

The agent runs every tool command in a sandbox. Set `MINIAGENT_SANDBOX_PROVIDER` to select one. The default is `local`.

| Provider | Isolation | Where the repository lives | Install | Credentials |
|---|---|---|---|---|
| `local` | none, a host subprocess | host worktree under `data/` | built in | none |
| `docker` | container | host worktree, mounted at the same path | `uv sync --extra docker` | Docker daemon |
| `e2b` | Firecracker microVM | cloned inside the sandbox | `uv sync --extra e2b` | `E2B_API_KEY` |
| `daytona` | container | cloned inside the sandbox | `uv sync --extra daytona` | `DAYTONA_API_KEY` |
| `modal` | gVisor | cloned inside the sandbox | `uv sync --extra modal` | `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` |
| `vercel` | Firecracker microVM | cloned inside the sandbox | `uv sync --extra vercel` | `VERCEL_TOKEN` + team and project ids, or `VERCEL_OIDC_TOKEN` |
| `space` | Firecracker microVM, self-hosted | cloned inside the sandbox | built in | `SPACE_API_TOKEN`, or an email and password |

The server checks the selected provider when it starts. If the SDK or a credential is missing, the server stops and names the missing item.

## How a command runs

Every provider follows the same contract:

- A command that fails returns its exit code. It does not raise an error.
- A command that runs past its time limit returns exit code `124`.
- **Stop** ends every running command and its child processes. Those commands return exit code `130`.

The container and remote providers start each command in its own process group and record the group id in `/tmp/.miniagent`. **Stop** sends a second command that kills each recorded group. This works the same way on every provider, so no provider-specific kill API is necessary.

## GitHub token

The token never goes into a command, a URL or `.git/config`. Clone and push get the token through an environment variable for that one command. A git credential helper reads that variable.

## Lifetime

The server creates a remote sandbox the first time a Conversation needs it, which is a worker thread, never the event loop. Each new turn extends the sandbox lifetime. The database stores the sandbox id, so a restarted server reconnects to the same sandbox. If the provider deleted the sandbox, the Conversation stays readable from its event log, and Session changes return `409 sandbox_expired`.

## Docker image

```bash
docker build -t miniagent-sandbox:latest sandbox
```

The image adds `git`, `setsid` and GNU `timeout` to `python:3.12-slim`. Commands run as your own user, so files in the mounted worktree stay yours.

## SPACE

SPACE is self-hosted. It needs Linux x86_64 with KVM, so it cannot run on macOS. Point `SPACE_API_URL` and `SPACE_DATA_PLANE_URL` at a running deployment.

- The adapter uses only the SPACE routes that the M1 contract supports: sandboxes, operations, commands and their event streams.
- File operations go through the shell, because the SPACE file routes are still incubating.
- The default template is `code-runtime:latest`, because the `seed` template has no git. An operator must build `code-runtime` first.
- SPACE blocks all outbound traffic by default. With `MINIAGENT_SPACE_ALLOW_INTERNET=true` the adapter asks for an allow policy with TLS interception off, because TLS interception breaks git over HTTPS. If your operator sets egress through a profile, set this to `false` and set `MINIAGENT_SPACE_EGRESS_PROFILES`.

## Tests

```bash
uv run pytest tests/test_sandbox_contract.py
```

The contract suite runs the same tests against every provider:

- `local` always runs.
- `docker`, a fake SPACE server and stubbed versions of the hosted SDK adapters run when the Docker image exists.
- Each hosted provider runs for real when its credentials are in the environment.
