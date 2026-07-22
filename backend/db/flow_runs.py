"""Queries for flow_runs — one row per execution of a flow's DAG.

Every task_run belongs to a flow_run. "Partial" flow runs are executions
started mid-graph (a single task triggered manually or by its own schedule);
their dependency checks fall back to global latest-run state for upstream
tasks that have no run in the flow run.
"""

import uuid
from typing import Optional

import aiosqlite

from db import tasks as db_tasks, task_runs as db_task_runs
from models import initial_run_status

# Statuses of a member task's latest attempt within a flow run, as a
# correlated subquery fragment reused by the rollup queries below.
_LATEST_ATTEMPT_FILTER = """
    tr.run_number = (
        SELECT MAX(run_number) FROM task_runs
        WHERE flow_run_id = fr.id AND task_id = tr.task_id
    )
"""


async def get_by_id(db: aiosqlite.Connection, flow_run_id: str) -> Optional[dict]:
    cursor = await db.execute("SELECT * FROM flow_runs WHERE id = ?", (flow_run_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def next_run_number(db: aiosqlite.Connection, flow_id: str) -> int:
    cursor = await db.execute(
        "SELECT COALESCE(MAX(run_number), 0) + 1 FROM flow_runs WHERE flow_id = ?",
        (flow_id,),
    )
    return (await cursor.fetchone())[0]


async def insert(db: aiosqlite.Connection, flow_run_id: str, flow_id: str,
                 run_number: int, trigger: str = "manual",
                 partial: bool = False, status: str = "running") -> None:
    await db.execute(
        """INSERT INTO flow_runs (id, flow_id, run_number, trigger, partial, status, started_at)
           VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? = 'running' THEN datetime('now') END)""",
        (flow_run_id, flow_id, run_number, trigger, 1 if partial else 0, status, status),
    )


async def list_by_flow(db: aiosqlite.Connection, flow_id: str) -> list[dict]:
    """Flow runs newest-first, with per-task rollup counts (latest attempt per task)."""
    cursor = await db.execute(
        f"""SELECT fr.*,
               (SELECT COUNT(DISTINCT task_id) FROM task_runs WHERE flow_run_id = fr.id) AS total_tasks,
               (SELECT COUNT(*) FROM task_runs tr WHERE tr.flow_run_id = fr.id
                  AND tr.status = 'success' AND {_LATEST_ATTEMPT_FILTER}) AS succeeded_tasks,
               (SELECT COUNT(*) FROM task_runs tr WHERE tr.flow_run_id = fr.id
                  AND tr.status IN ('failed', 'cancelled') AND {_LATEST_ATTEMPT_FILTER}) AS failed_tasks,
               (SELECT COUNT(*) FROM task_runs tr WHERE tr.flow_run_id = fr.id
                  AND tr.status IN ('queued', 'running', 'awaiting_approval') AND {_LATEST_ATTEMPT_FILTER}) AS active_tasks
            FROM flow_runs fr WHERE fr.flow_id = ?
            ORDER BY fr.run_number DESC""",
        (flow_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_task_runs(db: aiosqlite.Connection, flow_run_id: str) -> list[dict]:
    cursor = await db.execute(
        """SELECT tr.*, t.title AS task_title FROM task_runs tr
           LEFT JOIN tasks t ON t.id = tr.task_id
           WHERE tr.flow_run_id = ? ORDER BY tr.started_at ASC""",
        (flow_run_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def latest_task_statuses(db: aiosqlite.Connection, flow_run_id: str) -> list[str]:
    """Status of each member task's latest attempt within the flow run."""
    cursor = await db.execute(
        """SELECT tr.status FROM task_runs tr
           WHERE tr.flow_run_id = ?
           AND tr.run_number = (
               SELECT MAX(run_number) FROM task_runs
               WHERE flow_run_id = tr.flow_run_id AND task_id = tr.task_id
           )""",
        (flow_run_id,),
    )
    return [row[0] for row in await cursor.fetchall()]


async def count_unfinished_members(db: aiosqlite.Connection, flow_run_id: str) -> int:
    """Queued/running member runs — a queued retry with a future not_before
    counts, and so does a pending approval gate (it's blocked on a human, not
    finished)."""
    cursor = await db.execute(
        """SELECT COUNT(*) FROM task_runs WHERE flow_run_id = ?
           AND status IN ('queued', 'running', 'awaiting_approval')""",
        (flow_run_id,),
    )
    return (await cursor.fetchone())[0]


async def count_active_full(db: aiosqlite.Connection, flow_id: str) -> int:
    """Running non-partial flow runs — what max_active_runs gates against.

    Partial (single-task) runs don't count: an ad-hoc task execution
    shouldn't block a full DAG run, matching Airflow's treatment of
    manually-run task instances.
    """
    cursor = await db.execute(
        "SELECT COUNT(*) FROM flow_runs WHERE flow_id = ? AND status = 'running' AND partial = 0",
        (flow_id,),
    )
    return (await cursor.fetchone())[0]


async def set_running(db: aiosqlite.Connection, flow_run_id: str) -> None:
    await db.execute(
        "UPDATE flow_runs SET status = 'running', started_at = datetime('now') WHERE id = ?",
        (flow_run_id,),
    )


async def reopen(db: aiosqlite.Connection, flow_run_id: str) -> None:
    """Bring a terminal flow run back to running (retry/resume of a member task)."""
    await db.execute(
        "UPDATE flow_runs SET status = 'running', finished_at = NULL WHERE id = ?",
        (flow_run_id,),
    )


async def set_finished(db: aiosqlite.Connection, flow_run_id: str, status: str) -> None:
    await db.execute(
        """UPDATE flow_runs SET status = ?, finished_at = datetime('now'),
           total_cost_usd = (
               SELECT COALESCE(SUM(cost_usd), 0) FROM task_runs WHERE flow_run_id = ?
           )
           WHERE id = ?""",
        (status, flow_run_id, flow_run_id),
    )


async def cancel_active_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute(
        """UPDATE flow_runs SET status = 'cancelled', finished_at = datetime('now')
           WHERE flow_id = ? AND status IN ('queued', 'running')""",
        (flow_id,),
    )


async def get_running(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute("SELECT * FROM flow_runs WHERE status = 'running'")
    return [dict(r) for r in await cursor.fetchall()]


async def get_promotable_queued(db: aiosqlite.Connection) -> list[dict]:
    """Oldest queued flow run per flow, where the flow has capacity for it."""
    cursor = await db.execute(
        """SELECT fr.* FROM flow_runs fr
           WHERE fr.status = 'queued'
           AND fr.run_number = (
               SELECT MIN(run_number) FROM flow_runs q
               WHERE q.flow_id = fr.flow_id AND q.status = 'queued'
           )
           AND (
               SELECT COUNT(*) FROM flow_runs r
               WHERE r.flow_id = fr.flow_id AND r.status = 'running' AND r.partial = 0
           ) < (
               SELECT COALESCE(max_active_runs, 1) FROM flows WHERE id = fr.flow_id
           )""",
    )
    return [dict(r) for r in await cursor.fetchall()]


async def delete_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute("DELETE FROM flow_runs WHERE flow_id = ?", (flow_id,))


async def insert_root_runs(db: aiosqlite.Connection, flow_id: str,
                           flow_run_id: str, trigger: str) -> list[dict]:
    """Queue a run for every root task of the flow, attached to the flow run.

    A root task that's an approval gate starts straight in
    'awaiting_approval' — it never runs an agent, it just waits on a human."""
    created = []
    for task_row in await db_tasks.get_root_tasks(db, flow_id):
        task_id = task_row["id"]
        status = initial_run_status(task_row.get("task_type"))
        run_number = await db_task_runs.next_run_number(db, task_id)
        run_id = str(uuid.uuid4())
        await db_task_runs.insert(db, run_id, task_id, run_number,
                                  trigger=trigger, flow_run_id=flow_run_id,
                                  status=status)
        created.append({"id": run_id, "task_id": task_id, "run_number": run_number,
                        "status": status})
    return created


async def create_for_flow(db: aiosqlite.Connection, flow_id: str,
                          trigger: str = "manual") -> dict:
    """Create a full flow run. Starts running with its root task runs queued,
    unless the flow is at max_active_runs — then the flow run itself is queued
    with no task runs, and the poll loop promotes it later.

    Task-level runs reuse the flow_runs trigger vocabulary minus 'resume';
    root task_runs get trigger 'manual'/'schedule'/'retry' as passed.
    """
    cursor = await db.execute(
        "SELECT COALESCE(max_active_runs, 1) FROM flows WHERE id = ?", (flow_id,)
    )
    row = await cursor.fetchone()
    max_active = row[0] if row else 1

    flow_run_id = str(uuid.uuid4())
    run_number = await next_run_number(db, flow_id)

    if await count_active_full(db, flow_id) >= max_active:
        await insert(db, flow_run_id, flow_id, run_number, trigger=trigger,
                     status="queued")
        return {"flow_run": await get_by_id(db, flow_run_id), "runs": []}

    await insert(db, flow_run_id, flow_id, run_number, trigger=trigger)
    runs = await insert_root_runs(db, flow_id, flow_run_id, trigger)
    return {"flow_run": await get_by_id(db, flow_run_id), "runs": runs}


async def create_partial(db: aiosqlite.Connection, flow_id: str,
                         trigger: str = "manual") -> dict:
    """Create a running partial flow run (mid-graph execution). The caller
    attaches the triggering task's run to it."""
    flow_run_id = str(uuid.uuid4())
    run_number = await next_run_number(db, flow_id)
    await insert(db, flow_run_id, flow_id, run_number, trigger=trigger, partial=True)
    return await get_by_id(db, flow_run_id)


async def promote(db: aiosqlite.Connection, flow_run: dict) -> list[dict]:
    """Start a queued flow run: mark it running and queue its root task runs."""
    await set_running(db, flow_run["id"])
    return await insert_root_runs(db, flow_run["flow_id"], flow_run["id"],
                                  flow_run.get("trigger") or "manual")
