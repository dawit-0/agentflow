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
- **Secrets** — Encrypted-at-rest credential store. Save an API key or token once, then opt individual tasks or agents into it by name; it's injected as an environment variable only into the runs that ask for it. See [Secrets](#secrets).
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

A place to store the API keys and tokens your agents need — a GitHub PAT for
a `gh` CLI call, a Slack webhook, a third-party API key — without pasting
them into prompts or `.env` files inside a task's working directory, where
they'd sit in plaintext and could leak into agent output or git history.

**Add one:** Secrets tab → New Secret. Give it a key (the environment
variable name the agent will see, e.g. `GITHUB_TOKEN`) and the value. The
value is encrypted at rest with a locally-generated key
(`backend/.secret_key`, git-ignored) and is never shown or returned by the
API again after creation — only the key name and description are.

**Use one:** open a task or agent's form and check the secrets it needs
under "Secrets" / "Default Secrets". Only the secrets a task explicitly
selects are exposed to it, as environment variables, for that run only —
nothing is granted by default. Agent defaults are inherited by tasks spawned
from that agent unless a task overrides them.

**How it's delivered:** on the host, secrets are merged into the subprocess
environment (never passed as command-line arguments, so they don't leak via
`ps`). Under Docker sandbox mode, they're written to a private, run-scoped
`--env-file` instead of `-e KEY=VALUE` flags, for the same reason, and the
file is deleted once the container has started.
