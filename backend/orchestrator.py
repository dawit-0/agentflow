import asyncio
import json
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

import cron as cron_parser
from database import get_db
from db import tasks as db_tasks, task_runs as db_task_runs, flows as db_flows
from db import task_run_output as db_output, task_dependencies as db_deps
from db import task_xcom as db_xcom, flow_runs as db_flow_runs
from db import settings as db_settings, secrets as db_secrets
from logging_config import get_logger, task_logger
from models import DEFAULT_PERMISSIONS
from notifications import maybe_notify_run_finished, notify_flow_completed
from providers.sandbox import SandboxConfig

logger = get_logger("orchestrator")

MAX_CONCURRENT_RUNS = 5
POLL_INTERVAL = 2  # seconds


class Orchestrator:
    def __init__(self, sio):
        self.sio = sio
        self.running_providers: dict[str, "BaseProvider"] = {}  # run_id -> provider
        self._poll_task: Optional[asyncio.Task] = None
        self._max_concurrent_runs: int = MAX_CONCURRENT_RUNS

    def update_max_concurrent(self, value: int):
        self._max_concurrent_runs = value
        logger.info("max_concurrent_runs updated to %d", value)

    async def start(self):
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self._poll_task:
            self._poll_task.cancel()
        for run_id, provider in list(self.running_providers.items()):
            try:
                await provider.cancel()
            except Exception:
                pass
        self.running_providers.clear()

    async def _poll_loop(self):
        while True:
            try:
                logger.debug("poll cycle: %d active runs, %d slots available",
                             len(self.running_providers),
                             self._max_concurrent_runs - len(self.running_providers))
                await self._check_task_schedules()
                await self._check_flow_schedules()
                await self._check_flow_run_lifecycle()
                await self._dispatch_queued_runs()
            except Exception:
                logger.exception("poll cycle error")
            await asyncio.sleep(POLL_INTERVAL)

    async def _check_task_schedules(self):
        """Create task runs from due task-level schedules."""
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        db = await get_db()
        try:
            tasks = await db_tasks.get_due_scheduled(db, now_str)

            for task in tasks:
                task_id = task["id"]
                run_number = await db_task_runs.next_run_number(db, task_id)
                run_id = str(uuid.uuid4())

                logger.info("schedule triggered task=%s", task_id)
                # A task-level schedule is a mid-graph execution: partial flow run
                flow_run = await db_flow_runs.create_partial(db, task["flow_id"],
                                                             trigger="schedule")
                await db_task_runs.insert(db, run_id, task_id, run_number,
                                          trigger="schedule",
                                          flow_run_id=flow_run["id"])

                # Advance next_run_at
                next_run = cron_parser.next_run_after(task["schedule"], now)
                next_run_str = next_run.strftime("%Y-%m-%dT%H:%M:%SZ")

                await db_tasks.update_schedule_times(db, task_id, now_str, next_run_str)
                await db.commit()

                await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": "queued"})
                await self.sio.emit("task_run:started", {"id": run_id, "task_id": task_id, "trigger": "schedule"})
        finally:
            await db.close()

    async def _check_flow_schedules(self):
        """Create task runs for root tasks in flows with due schedules."""
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        db = await get_db()
        try:
            flows = await db_flows.get_due_scheduled(db, now_str)

            for flow in flows:
                flow_id = flow["id"]

                created = await db_flow_runs.create_for_flow(db, flow_id,
                                                             trigger="schedule")
                flow_run = created["flow_run"]
                logger.info("schedule triggered flow=%s flow_run=%s status=%s, %d root tasks",
                            flow_id, flow_run["id"], flow_run["status"], len(created["runs"]))

                await self.sio.emit("flow_run:started", flow_run)
                for run in created["runs"]:
                    await self.sio.emit("task_run:started",
                                        {"id": run["id"], "task_id": run["task_id"],
                                         "trigger": "schedule", "flow_run_id": flow_run["id"]})

                # Advance next_run_at for the flow
                next_run = cron_parser.next_run_after(flow["schedule"], now)
                next_run_str = next_run.strftime("%Y-%m-%dT%H:%M:%SZ")

                await db_flows.update_schedule_times(db, flow_id, now_str, next_run_str)
                await db.commit()
        finally:
            await db.close()

    async def _dispatch_queued_runs(self):
        if len(self.running_providers) >= self._max_concurrent_runs:
            logger.debug("at capacity (%d running), skipping dispatch", self._max_concurrent_runs)
            return

        db = await get_db()
        try:
            slots = self._max_concurrent_runs - len(self.running_providers)
            runs = await db_task_runs.get_queued_ready(db, slots)

            if runs:
                logger.debug("dispatching %d queued runs", len(runs))
            for run in runs:
                await self._start_run(db, run)
        finally:
            await db.close()

    async def _start_run(self, db: aiosqlite.Connection, run: dict):
        run_id = run["id"]
        task_id = run["task_id"]

        logger.info("starting run=%s task=%s trigger=%s", run_id, task_id, run.get("trigger", "?"))

        await db_task_runs.set_running(db, run_id)
        await db.commit()

        await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": "running"})
        await self.sio.emit("task_run:started", {"id": run_id, "task_id": task_id})

        asyncio.create_task(self._execute_run(run_id, run))

    async def _emit_event(self, db, run_id: str, task_id: str, seq: int, event_data: dict):
        """Persist a lifecycle event to the run's output file and broadcast it."""
        content = json.dumps(event_data)
        await db_output.insert(run_id, seq, "event", content)
        await self.sio.emit("task_run:output", {
            "task_run_id": run_id,
            "task_id": task_id,
            "seq": seq,
            "type": "event",
            "content": content,
        })

    async def _resolve_sandbox(self, db, run: dict) -> SandboxConfig:
        """Compute the effective sandbox config for a run.

        Precedence: task.sandbox → settings.default_sandbox. Empty string means
        host execution (no Docker). The returned config carries the
        deterministic container name we'll use for cancel.
        """
        task_sandbox = (run.get("task_sandbox") or "").strip()
        settings = await db_settings.get_all(db)
        mode = task_sandbox if task_sandbox else (settings.get("default_sandbox") or "")
        cfg = SandboxConfig(
            mode=mode,
            image=settings.get("sandbox_image") or "agentflow/claude-sandbox:latest",
            memory=str(settings.get("sandbox_memory") or "4g"),
            cpus=str(settings.get("sandbox_cpus") or "2"),
        )
        if cfg.enabled:
            cfg.container_name = f"agentflow-{run['id'][:12]}"
        return cfg

    async def _resolve_secret_env(self, db, run: dict) -> dict[str, str]:
        """Resolve the task's selected secret keys to decrypted values.

        Only the keys a task explicitly opted into (its ``secret_keys`` list)
        are exposed — a task with none configured gets no secret env vars."""
        try:
            keys = json.loads(run.get("task_secret_keys") or "[]")
        except (json.JSONDecodeError, TypeError):
            keys = []
        if not keys:
            return {}
        return await db_secrets.get_values_for_keys(db, keys)

    async def _build_prompt_with_context(self, db, task_id: str, base_prompt: str,
                                         flow_run_id: Optional[str] = None) -> str:
        """Prepend upstream task outputs to the prompt for inter-task data passing.

        Output is taken from the upstream's successful run in the same flow run.
        Partial flow runs (and legacy runs with no flow run) fall back to the
        upstream's global latest success.
        """
        upstream_deps = await db_deps.get_upstream_with_config(db, task_id)

        if not upstream_deps:
            return base_prompt

        partial = True  # legacy runs behave like partial: global fallback
        if flow_run_id:
            flow_run = await db_flow_runs.get_by_id(db, flow_run_id)
            partial = bool(flow_run and flow_run.get("partial"))

        context_sections = []
        for dep in upstream_deps:
            upstream_task_id = dep["depends_on_task_id"]
            pass_output = dep.get("pass_output", 1)
            max_chars = dep.get("max_output_chars", 4000)

            if not pass_output:
                continue

            latest_run = None
            if flow_run_id:
                latest_run = await db_task_runs.get_latest_successful_in_flow_run(
                    db, upstream_task_id, flow_run_id)
            if not latest_run and partial:
                latest_run = await db_task_runs.get_latest_successful(db, upstream_task_id)
            if not latest_run:
                continue

            upstream_task = await db_tasks.get_by_id(db, upstream_task_id)
            task_title = dict(upstream_task)["title"] if upstream_task else upstream_task_id[:8]

            result_text = await db_output.get_result_text(latest_run["id"], max_chars)
            if result_text.strip():
                context_sections.append(
                    f"=== Output from upstream task: {task_title} ===\n{result_text}"
                )

        if not context_sections:
            return base_prompt

        context_block = "\n\n".join(context_sections)
        return (
            f"The following context comes from upstream tasks that have already completed:\n\n"
            f"{context_block}\n\n"
            f"---\n\n"
            f"{base_prompt}"
        )

    async def _execute_run(self, run_id: str, run: dict):
        task_id = run["task_id"]
        flow_run_id = run.get("flow_run_id")
        work_dir = run["work_dir"] or os.getcwd()
        model = run["model"] or "claude-sonnet-4-20250514"
        base_prompt = run["prompt"]
        start_time = datetime.now(timezone.utc)
        seq = 0
        tlog = task_logger(run_id, task_id)

        try:
            permissions = json.loads(run.get("permissions") or "{}")
        except (json.JSONDecodeError, TypeError):
            permissions = DEFAULT_PERMISSIONS

        try:
            # Build prompt with upstream context (XCom-like data passing).
            # Resolve effective sandbox config: task-level → global default.
            db = await get_db()
            try:
                prompt = await self._build_prompt_with_context(db, task_id, base_prompt,
                                                               flow_run_id)
                sandbox_cfg = await self._resolve_sandbox(db, run)
                if sandbox_cfg.enabled:
                    await db_task_runs.set_sandbox(db, run_id,
                                                    sandbox_cfg.mode,
                                                    sandbox_cfg.container_name)
                    await db.commit()
                env = await self._resolve_secret_env(db, run)
            finally:
                await db.close()

            # Select provider based on model
            from providers import get_provider as resolve_provider
            from providers.claude_provider import ClaudeProvider
            from providers.openai_provider import OpenAIProvider

            provider_name = resolve_provider(model)
            if provider_name == "openai":
                provider = OpenAIProvider()
            else:
                provider = ClaudeProvider()

            self.running_providers[run_id] = provider

            # Set PID early if the provider exposes one (after first event)
            pid_set = False

            # OpenAI provider ignores sandbox (HTTP-only). Pass None so the
            # `sandbox: docker` event marker only appears for ClaudeProvider.
            run_sandbox = sandbox_cfg if (sandbox_cfg.enabled and provider_name != "openai") else None

            async for event in provider.execute(prompt, model, work_dir, permissions,
                                                 sandbox=run_sandbox, env=env):
                seq += 1

                # Track PID for subprocess-based providers
                if not pid_set and provider.pid is not None:
                    pid_set = True
                    tlog.info("provider started pid=%d", provider.pid)
                    db = await get_db()
                    try:
                        await db_task_runs.set_pid(db, run_id, provider.pid)
                        await db.commit()
                    finally:
                        await db.close()

                await db_output.insert(run_id, seq, event.type, event.content)

                await self.sio.emit("task_run:output", {
                    "task_run_id": run_id,
                    "task_id": task_id,
                    "seq": seq,
                    "type": event.type,
                    "content": event.content,
                })

            exit_code = getattr(provider, "exit_code", 1)
            stderr_data = getattr(provider, "stderr_data", "")
            total_cost_usd = getattr(provider, "total_cost_usd", 0.0)

            elapsed = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            status = "success" if exit_code == 0 else "failed"

            tlog.info("finished status=%s exit=%s duration=%dms cost=$%.4f",
                      status, exit_code, elapsed, total_cost_usd)
            if stderr_data and status == "failed":
                tlog.warning("stderr: %s", stderr_data[:500])

            db = await get_db()
            try:
                seq += 1
                await self._emit_event(db, run_id, task_id, seq,
                                        {"event": "subprocess_exited", "exit_code": exit_code, "duration_ms": elapsed})

                await db_task_runs.set_finished(db, run_id, status,
                                                 exit_code=exit_code,
                                                 duration_ms=elapsed,
                                                 num_turns=seq,
                                                 error_message=stderr_data or None,
                                                 cost_usd=total_cost_usd)

                notify_retried = False
                if status == "success":
                    # Store result as xcom for downstream tasks
                    result_text = await db_output.get_result_text(run_id, max_chars=8000)
                    if result_text.strip():
                        await db_xcom.insert(db, run_id, task_id, "return_value", result_text)
                    await self._cascade_trigger_downstream(db, task_id, flow_run_id)
                else:
                    # Check if auto-retry is configured
                    notify_retried = await self._maybe_auto_retry(db, run_id, task_id)
                    if not notify_retried:
                        await self._cascade_cancel_downstream(db, task_id, flow_run_id)

                await db.commit()

                # Per-task notification (skip if a retry is queued — we'll notify when retries are exhausted)
                task_row = await db_tasks.get_by_id(db, task_id)
                if task_row and not (status == "failed" and notify_retried):
                    try:
                        await maybe_notify_run_finished(
                            db, self.sio,
                            task=dict(task_row),
                            task_run_id=run_id,
                            status=status,
                            error_message=stderr_data or None,
                        )
                        await db.commit()
                    except Exception:
                        logger.exception("per-run notification failed for run=%s", run_id)

                # Close out the flow run if this was its last active task
                if flow_run_id:
                    await self._finalize_flow_run(db, flow_run_id)
                    await db.commit()
            finally:
                await db.close()

            await self.sio.emit("task_run:finished", {
                "id": run_id,
                "task_id": task_id,
                "status": status,
                "exit_code": exit_code,
                "duration_ms": elapsed,
            })
            await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": status})

        except Exception:
            elapsed = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            tlog.exception("run failed with exception after %dms", elapsed)
            error_msg = traceback.format_exc()
            db = await get_db()
            try:
                await db_task_runs.set_failed(db, run_id, elapsed, error_msg)
                retried = await self._maybe_auto_retry(db, run_id, task_id)
                if not retried:
                    await self._cascade_cancel_downstream(db, task_id, flow_run_id)
                await db.commit()

                if not retried:
                    task_row = await db_tasks.get_by_id(db, task_id)
                    if task_row:
                        try:
                            await maybe_notify_run_finished(
                                db, self.sio,
                                task=dict(task_row),
                                task_run_id=run_id,
                                status="failed",
                                error_message=error_msg,
                            )
                            await db.commit()
                        except Exception:
                            logger.exception("per-run notification failed for run=%s", run_id)

                    if flow_run_id:
                        await self._finalize_flow_run(db, flow_run_id)
                        await db.commit()
            finally:
                await db.close()

            await self.sio.emit("task_run:finished", {
                "id": run_id,
                "task_id": task_id,
                "status": "failed",
                "error_message": error_msg,
            })
            await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": "failed"})
        finally:
            self.running_providers.pop(run_id, None)

    async def _maybe_auto_retry(self, db: aiosqlite.Connection, failed_run_id: str, task_id: str) -> bool:
        """Queue a delayed retry for the failed run if configured. Returns True
        if one was queued.

        The retry run is inserted immediately with a future ``not_before`` and
        the dispatcher skips it until then — so pending retries survive a
        backend restart and keep their flow run open."""
        task = await db_tasks.get_retry_config(db, task_id)
        if not task or not task["max_retries"] or task["max_retries"] <= 0:
            return False

        failed_run = await db_task_runs.get_by_id(db, failed_run_id)
        attempt = (failed_run["attempt_number"] if failed_run and failed_run["attempt_number"] else 1)

        if attempt >= task["max_retries"]:
            logger.warning("run=%s task=%s exhausted retries (%d/%d)",
                           failed_run_id, task_id, attempt, task["max_retries"])
            return False

        delay = task["retry_delay_seconds"] or 10
        run_number = await db_task_runs.next_run_number(db, task_id)
        run_id = str(uuid.uuid4())

        logger.info("queuing retry attempt=%d for run=%s task=%s in %ds",
                    attempt + 1, failed_run_id, task_id, delay)
        await db_task_runs.insert(db, run_id, task_id, run_number,
                                  trigger="retry", attempt_number=attempt + 1,
                                  retry_of_run_id=failed_run_id,
                                  flow_run_id=failed_run["flow_run_id"] if failed_run else None,
                                  not_before_seconds=delay)

        await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": "queued"})
        await self.sio.emit("task_run:started", {"id": run_id, "task_id": task_id, "trigger": "retry"})
        return True

    async def _reopen_flow_run_if_terminal(self, db, flow_run_id: Optional[str]):
        """A manual retry of a member task brings its finished flow run back to running."""
        if not flow_run_id:
            return
        flow_run = await db_flow_runs.get_by_id(db, flow_run_id)
        if flow_run and flow_run["status"] in ("success", "failed", "cancelled"):
            await db_flow_runs.reopen(db, flow_run_id)
            await self.sio.emit("flow_run:started", {**flow_run, "status": "running"})

    async def retry_task_run(self, task_id: str):
        """Manually retry the latest failed run for a task, then cascade downstream.

        The retry joins the failed run's flow run (reopening it if finished),
        like clearing a task instance within an Airflow DAG run."""
        db = await get_db()
        try:
            last_run = await db_task_runs.get_latest(db, task_id)
            run_number = await db_task_runs.next_run_number(db, task_id)
            run_id = str(uuid.uuid4())

            retry_of = last_run["id"] if last_run else None
            attempt = (last_run["attempt_number"] + 1) if last_run and last_run["attempt_number"] else 1
            flow_run_id = last_run["flow_run_id"] if last_run else None

            await self._reopen_flow_run_if_terminal(db, flow_run_id)
            await db_task_runs.insert(db, run_id, task_id, run_number,
                                      trigger="retry", attempt_number=attempt,
                                      retry_of_run_id=retry_of,
                                      flow_run_id=flow_run_id)
            await db.commit()

            await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": "queued"})
            return {"id": run_id, "task_id": task_id, "run_number": run_number}
        finally:
            await db.close()

    async def resume_flow(self, flow_id: str):
        """Resume a flow by retrying all failed/cancelled leaf tasks (tasks whose failure stopped the flow)."""
        db = await get_db()
        try:
            tasks_to_retry = await db_tasks.get_resumable_failed_tasks(db, flow_id)
            created_runs = []

            for task_row in tasks_to_retry:
                task_id = task_row["id"]
                last_run = await db_task_runs.get_latest(db, task_id)
                run_number = await db_task_runs.next_run_number(db, task_id)
                run_id = str(uuid.uuid4())

                retry_of = last_run["id"] if last_run else None
                flow_run_id = last_run["flow_run_id"] if last_run else None

                await self._reopen_flow_run_if_terminal(db, flow_run_id)
                await db_task_runs.insert(db, run_id, task_id, run_number,
                                          trigger="retry",
                                          retry_of_run_id=retry_of,
                                          flow_run_id=flow_run_id)
                created_runs.append({"id": run_id, "task_id": task_id, "run_number": run_number})
                await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": "queued"})

            await db.commit()
            return {"retried": len(created_runs), "runs": created_runs}
        finally:
            await db.close()

    async def _finalize_flow_run(self, db: aiosqlite.Connection, flow_run_id: str) -> None:
        """Close out a flow run once none of its member runs are queued/running.

        Status is success iff every member task's latest attempt succeeded.
        Pending delayed retries are queued members, so they keep the run open."""
        flow_run = await db_flow_runs.get_by_id(db, flow_run_id)
        if not flow_run or flow_run["status"] != "running":
            return

        if await db_flow_runs.count_unfinished_members(db, flow_run_id) > 0:
            return

        statuses = await db_flow_runs.latest_task_statuses(db, flow_run_id)
        if not statuses:
            return  # nothing has run yet (e.g. roots not created) — keep it open

        total = len(statuses)
        failed = sum(1 for s in statuses if s in ("failed", "cancelled"))
        status = "failed" if failed > 0 else "success"

        await db_flow_runs.set_finished(db, flow_run_id, status)
        logger.info("flow_run=%s finalized status=%s (%d/%d tasks failed)",
                    flow_run_id, status, failed, total)

        await self.sio.emit("flow_run:finished", {
            "id": flow_run_id,
            "flow_id": flow_run["flow_id"],
            "status": status,
        })

        flow = await db_flows.get_by_id(db, flow_run["flow_id"])
        flow_name = (flow or {}).get("name") or flow_run["flow_id"][:8]
        try:
            await notify_flow_completed(
                db, self.sio,
                flow_id=flow_run["flow_id"],
                flow_name=flow_name,
                failed=failed > 0,
                total_tasks=total,
                failed_tasks=failed,
            )
        except Exception:
            logger.exception("flow completion notification failed for flow_run=%s", flow_run_id)

    async def _check_flow_run_lifecycle(self):
        """Poll-cycle pass: promote queued flow runs with capacity, and sweep
        running flow runs whose members all finished (self-healing if a
        finalize was missed, e.g. across a restart)."""
        db = await get_db()
        try:
            await self._promote_queued_flow_runs(db)

            for flow_run in await db_flow_runs.get_running(db):
                await self._finalize_flow_run(db, flow_run["id"])
            await db.commit()
        finally:
            await db.close()

    async def _promote_queued_flow_runs(self, db: aiosqlite.Connection):
        """Start the oldest queued flow run of each flow with free capacity."""
        for flow_run in await db_flow_runs.get_promotable_queued(db):
            runs = await db_flow_runs.promote(db, flow_run)
            await db.commit()
            logger.info("promoted queued flow_run=%s flow=%s, %d root tasks",
                        flow_run["id"], flow_run["flow_id"], len(runs))

            await self.sio.emit("flow_run:started", {**flow_run, "status": "running"})
            for run in runs:
                await self.sio.emit("task_run:started",
                                    {"id": run["id"], "task_id": run["task_id"],
                                     "flow_run_id": flow_run["id"]})

    async def _cascade_trigger_downstream(self, db: aiosqlite.Connection,
                                          completed_task_id: str,
                                          flow_run_id: Optional[str] = None):
        """When a task run succeeds, queue downstream runs in the same flow run
        once all their upstream deps are met within it."""
        downstream_tasks = await db_deps.get_downstream(db, completed_task_id)

        partial = False
        if flow_run_id:
            flow_run = await db_flow_runs.get_by_id(db, flow_run_id)
            partial = bool(flow_run and flow_run.get("partial"))

        for row in downstream_tasks:
            downstream_id = row["task_id"]

            # Check task is active
            task = await db_tasks.get_by_id(db, downstream_id)
            if not task or dict(task).get("status") != "active":
                continue

            # Check all upstream deps are met (scoped to this flow run)
            if flow_run_id:
                unmet_deps = await db_deps.get_unmet_upstream_in_flow_run(
                    db, downstream_id, flow_run_id, partial)
            else:
                unmet_deps = await db_deps.get_unmet_upstream(db, downstream_id)
            if unmet_deps:
                logger.debug("task=%s has unmet deps, skipping cascade", downstream_id)
                continue

            # Check no queued/running run already exists in this flow run
            if await db_task_runs.has_active_run(db, downstream_id, flow_run_id):
                continue

            # All deps met — create a queued run
            run_number = await db_task_runs.next_run_number(db, downstream_id)
            run_id = str(uuid.uuid4())

            logger.info("cascade: queuing downstream task=%s (triggered by task=%s flow_run=%s)",
                        downstream_id, completed_task_id, flow_run_id)
            await db_task_runs.insert(db, run_id, downstream_id, run_number,
                                      trigger="dependency", flow_run_id=flow_run_id)

            await self.sio.emit("task:updated", {"id": downstream_id, "latest_run_status": "queued"})

    async def _cascade_cancel_downstream(self, db: aiosqlite.Connection,
                                         failed_task_id: str,
                                         flow_run_id: Optional[str] = None):
        """Recursively cancel queued downstream runs (in the same flow run) when a task fails."""
        queued_runs = await db_deps.get_queued_downstream(db, failed_task_id, flow_run_id)

        for row in queued_runs:
            run_id = row["id"]
            task_id = row["task_id"]
            logger.warning("cascade cancel: run=%s task=%s (upstream task=%s failed)",
                           run_id, task_id, failed_task_id)
            await db_task_runs.cancel(db, run_id)
            await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": "cancelled"})
            await self.sio.emit("task_run:finished", {"id": run_id, "task_id": task_id, "status": "cancelled"})
            # Recurse
            await self._cascade_cancel_downstream(db, task_id, flow_run_id)

    async def cancel_task_run(self, task_id: str):
        """Cancel the latest running/queued run for a task."""
        db = await get_db()
        try:
            run = await db_task_runs.get_active_run(db, task_id)

            if run:
                run_id = run["id"]
                flow_run_id = run["flow_run_id"]
                provider = self.running_providers.get(run_id)
                if provider:
                    logger.info("cancelling task=%s run=%s pid=%s", task_id, run_id, provider.pid)
                    try:
                        await provider.cancel()
                    except Exception:
                        pass
                    self.running_providers.pop(run_id, None)
                else:
                    logger.info("cancelling task=%s run=%s (no active provider)", task_id, run_id)

                await db_task_runs.cancel(db, run_id)
                await self._cascade_cancel_downstream(db, task_id, flow_run_id)
                if flow_run_id:
                    await self._finalize_flow_run(db, flow_run_id)
                await db.commit()

                await self.sio.emit("task_run:finished", {"id": run_id, "task_id": task_id, "status": "cancelled"})

            await self.sio.emit("task:updated", {"id": task_id, "latest_run_status": "cancelled"})
        finally:
            await db.close()

    async def cancel_flow_run(self, flow_run_id: str):
        """Cancel a whole flow run: stop running providers, cancel queued/running
        member runs, and mark the flow run cancelled."""
        db = await get_db()
        try:
            flow_run = await db_flow_runs.get_by_id(db, flow_run_id)
            if not flow_run:
                return False

            for member in await db_flow_runs.get_task_runs(db, flow_run_id):
                if member["status"] not in ("queued", "running"):
                    continue
                provider = self.running_providers.pop(member["id"], None)
                if provider:
                    try:
                        await provider.cancel()
                    except Exception:
                        pass
                await db_task_runs.cancel(db, member["id"])
                await self.sio.emit("task:updated",
                                    {"id": member["task_id"], "latest_run_status": "cancelled"})
                await self.sio.emit("task_run:finished",
                                    {"id": member["id"], "task_id": member["task_id"],
                                     "status": "cancelled"})

            await db_flow_runs.set_finished(db, flow_run_id, "cancelled")
            await db.commit()

            await self.sio.emit("flow_run:finished", {
                "id": flow_run_id,
                "flow_id": flow_run["flow_id"],
                "status": "cancelled",
            })
            return True
        finally:
            await db.close()
