<p align="center">
  <img src="frontend/public/favicon.svg" alt="AgentFlow" width="160" />
</p>

<h1 align="center">AgentFlow</h1>

<p align="center">
  A local webapp for orchestrating Claude and OpenAI coding agents — chain them into flows, schedule runs, and watch output stream in real time.
</p>

---

## Quick Start

**Requirements:** [uv](https://docs.astral.sh/uv/) (manages Python 3.11+ for you), Node.js 18+, and the [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) on your `PATH`. For OpenAI models, set `OPENAI_API_KEY`.

```bash
# Backend (http://localhost:3000)
cd backend
uv run main.py

# Frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

## Features

- **Tasks** — Run an agent with a prompt, model, working directory, and permissions. Track status, duration, cost, and full output per run.
- **Flows** — Group tasks into a DAG with dependencies. Cascading execution on success, cascading cancellation on failure, rendered as an interactive graph.
- **Agents** — Reusable templates bundling instructions, attached context (files / URLs / text), and default settings.
- **Scheduling** — Cron-based triggers on tasks or flows, with common presets (hourly, daily, weekdays, weekly, monthly).
- **Permissions** — Per-agent tool access: Read Only, Standard, or Full Access (enforced via Claude CLI `--allowedTools`).
- **Sandbox** — Optional Docker isolation per run: disposable container, bind-mounted work directory, restricted network, resource caps. See [Sandbox mode](#sandbox-mode).
- **Secrets** — Encrypted-at-rest vault for API keys, tokens, and credentials. Select which secrets a task or agent needs and they're decrypted into that run's environment only — never pasted into a prompt or returned by the API after creation.
- **Analytics** — Built-in dashboard for run volume, success rate, cost, and top failing tasks.
- **Notifications** — In-app alerts for run completion, failures, and schedule events.

## Models

| Provider | Models |
|----------|--------|
| Anthropic | Claude Sonnet, Opus, Haiku |
| OpenAI | Codex Mini, o3-mini, o4-mini |

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, python-socketio, aiosqlite |
| Database | SQLite (WAL mode) |
| Frontend | React 18, TypeScript, Vite, React Flow |
| Real-time | Socket.IO (WebSocket) |
| Agents | Claude Code CLI + OpenAI Responses API |

## Configuration

- `MAX_CONCURRENT_RUNS` — parallel run cap (default `5`), editable from the Settings page or in `backend/orchestrator.py`.
- `OPENAI_API_KEY` — required to use OpenAI models.

## Sandbox mode

Run agents inside a disposable Docker container so an agent with `bash` or
`file_write` permissions can't touch the host outside its work directory.

**One-time setup:**

```bash
bash docker/build.sh        # builds agentflow/claude-sandbox:latest
```

**Enable:** Settings → Sandbox → set "Default sandbox mode" to **Docker**.
Individual tasks and agents can override this from their form.

**What gets mounted into the container:**

- The task's `work_dir` — bind-mounted read-write if `file_write` permission
  is on, read-only otherwise. Same path inside and outside.
- `~/.claude` from the host, read-only, so the CLI re-uses your login. Anything
  the agent puts in `~/.ssh`, `~/.aws`, etc. on the host is **not** visible.

**Network policy** (mapped from permissions, no extra knob):

| Permissions                                | Network        |
|--------------------------------------------|----------------|
| `web_search` or `mcp` on                   | `host`         |
| both off                                   | `none`         |

**Resource caps** (overridable from Settings): `--memory 4g`, `--cpus 2`,
`--pids-limit 512`. Containers run as a non-root `agent` user (uid 1000) and
are auto-removed on exit (`docker run --rm`).

**Cancel** stops the container with `docker stop --time=5 agentflow-<run_id>`.

**Note:** OpenAI tasks bypass the sandbox — they make HTTP calls only and have
no local filesystem access to isolate.

## Secrets

Store credentials once in **Secrets** (the key icon in the header) and attach
them to individual tasks or as an agent's defaults. Selected secrets are
decrypted and exposed as environment variables — named after the secret —
only to that run's process (or container, when sandboxed); they're never
interpolated into the prompt.

- Values are encrypted at rest with [Fernet](https://cryptography.io/en/latest/fernet/)
  symmetric encryption. The key comes from `AGENTFLOW_SECRET_KEY` if set,
  otherwise it's generated once and stored in `backend/.secret_key`
  (gitignored — back it up, or existing secrets become unrecoverable).
- The API never returns a secret's value after creation — only its name,
  description, and usage timestamps. Rotate a value or delete it; you can't
  read it back.
- An agent with `bash` permission can still print an env var it was given
  access to (e.g. `echo $GITHUB_TOKEN`) — same trade-off as any CI system.
  Only attach the secrets a task actually needs.
