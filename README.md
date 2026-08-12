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
- **Secrets** — A vault for API keys and tokens, encrypted at rest. Reference one from any task prompt with `{{secret.NAME}}`; it's resolved right before the run starts and never written back to the prompt. See [Secrets](#secrets).
- **Sandbox** — Optional Docker isolation per run: disposable container, bind-mounted work directory, restricted network, resource caps. See [Sandbox mode](#sandbox-mode).
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

## Secrets

Before this, the only way to get a credential into a prompt was to paste it
in directly — visible forever in the task's edit history and run output.
Secrets fixes that: store a value once under Settings → Secrets, then
reference it from any task prompt as `{{secret.NAME}}`.

- **Encrypted at rest.** Values are encrypted with a key kept outside git
  (`backend/.secret_key`, auto-generated on first use, or pin one yourself
  via `AGENTFLOW_SECRET_KEY`). The API never returns a stored value back —
  only its name, description, and last-used time.
- **Resolved at run time, not save time.** The placeholder is expanded
  against the vault right before the agent starts, so the task's stored
  prompt keeps the placeholder, never the plaintext value.
- **Fails fast on typos.** A prompt referencing a secret that doesn't exist
  fails the run immediately with a clear error, before any provider (and
  cost) is involved.
- **Masked in run output.** If an agent's output happens to echo a resolved
  secret back, the value is replaced with `***NAME***` before it's logged
  or streamed — the model still gets the real value, only the persisted
  history is redacted.
- **Rotation.** Update a secret's value in place from Settings without
  touching the tasks that reference it.

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
