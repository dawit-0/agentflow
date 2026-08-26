from typing import Optional

import aiosqlite


async def get_by_id(db: aiosqlite.Connection, run_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute("SELECT * FROM task_runs WHERE id = ?", (run_id,))
    return await cursor.fetchone()


async def list_by_task(db: aiosqlite.Connection, task_id: str,
                        order_by: str = "run_number DESC") -> list[aiosqlite.Row]:
    cursor = await db.execute(
        f"SELECT * FROM task_runs WHERE task_id = ? ORDER BY {order_by}",
        (task_id,),
    )
    return await cursor.fetchall()


async def list_all(db: aiosqlite.Connection, task_id: Optional[str] = None) -> list[aiosqlite.Row]:
    if task_id:
        cursor = await db.execute(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY started_at DESC",
            (task_id,),
        )
    else:
        cursor = await db.execute("SELECT * FROM task_runs ORDER BY started_at DESC")
    return await cursor.fetchall()


async def get_latest(db: aiosqlite.Connection, task_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        "SELECT * FROM task_runs WHERE task_id = ? ORDER BY run_number DESC LIMIT 1",
        (task_id,),
    )
    return await cursor.fetchone()


async def next_run_number(db: aiosqlite.Connection, task_id: str) -> int:
    cursor = await db.execute(
        "SELECT COALESCE(MAX(run_number), 0) + 1 FROM task_runs WHERE task_id = ?",
        (task_id,),
    )
    row = await cursor.fetchone()
    return row[0]


async def insert(db: aiosqlite.Connection, run_id: str, task_id: str,
                  run_number: int, trigger: str = "manual",
                  status: str = "queued", attempt_number: int = 1,
                  retry_of_run_id: Optional[str] = None,
                  flow_run_id: Optional[str] = None,
                  not_before_seconds: Optional[int] = None) -> None:
    await db.execute(
        """INSERT INTO task_runs (id, task_id, run_number, trigger, status,
                                  attempt_number, retry_of_run_id, flow_run_id, not_before)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                   CASE WHEN ? IS NOT NULL THEN datetime('now', '+' || ? || ' seconds') END)""",
        (run_id, task_id, run_number, trigger, status, attempt_number,
         retry_of_run_id, flow_run_id, not_before_seconds, not_before_seconds),
    )


async def set_running(db: aiosqlite.Connection, run_id: str) -> None:
    await db.execute(
        "UPDATE task_runs SET status = 'running', started_at = datetime('now') WHERE id = ?",
        (run_id,),
    )


async def set_pid(db: aiosqlite.Connection, run_id: str, pid: int) -> None:
    await db.execute(
        "UPDATE task_runs SET pid = ? WHERE id = ?",
        (pid, run_id),
    )


async def set_sandbox(db: aiosqlite.Connection, run_id: str,
                      sandbox: str, container_name: Optional[str]) -> None:
    await db.execute(
        "UPDATE task_runs SET sandbox = ?, container_name = ? WHERE id = ?",
        (sandbox, container_name, run_id),
    )


async def set_finished(db: aiosqlite.Connection, run_id: str, status: str,
                         exit_code: Optional[int] = None, duration_ms: int = 0,
                         num_turns: int = 0,
                         error_message: Optional[str] = None,
                         cost_usd: float = 0.0) -> None:
    await db.execute(
        """UPDATE task_runs SET status = ?, exit_code = ?, duration_ms = ?,
           num_turns = ?, finished_at = datetime('now'), error_message = ?,
           cost_usd = ?
           WHERE id = ?""",
        (status, exit_code, duration_ms, num_turns, error_message, cost_usd, run_id),
    )


async def set_failed(db: aiosqlite.Connection, run_id: str,
                      duration_ms: int, error_message: str) -> None:
    await db.execute(
        """UPDATE task_runs SET status = 'failed', duration_ms = ?,
           finished_at = datetime('now'), error_message = ? WHERE id = ?""",
        (duration_ms, error_message, run_id),
    )


async def cancel(db: aiosqlite.Connection, run_id: str) -> None:
    await db.execute(
        "UPDATE task_runs SET status = 'cancelled', finished_at = datetime('now') WHERE id = ?",
        (run_id,),
    )


async def cancel_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute(
        """UPDATE task_runs SET status = 'cancelled', finished_at = datetime('now')
           WHERE task_id IN (SELECT id FROM tasks WHERE flow_id = ?)
           AND status IN ('queued', 'running')""",
        (flow_id,),
    )


async def delete_by_task(db: aiosqlite.Connection, task_id: str) -> None:
    await db.execute("DELETE FROM task_runs WHERE task_id = ?", (task_id,))


async def delete_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute(
        """DELETE FROM task_runs
           WHERE task_id IN (SELECT id FROM tasks WHERE flow_id = ?)""",
        (flow_id,),
    )


async def get_active_by_flow(db: aiosqlite.Connection, flow_id: str) -> list[dict]:
    cursor = await db.execute(
        """SELECT tr.id, tr.task_id FROM task_runs tr
           JOIN tasks t ON t.id = tr.task_id
           WHERE t.flow_id = ? AND tr.status IN ('queued', 'running')""",
        (flow_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_attempt_number(db: aiosqlite.Connection, run_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        "SELECT attempt_number FROM task_runs WHERE id = ?", (run_id,)
    )
    return await cursor.fetchone()


# Dependency-met predicate for a queued run, scoped to its flow run:
#  - upstream has run(s) in the same flow run  -> its latest in-run attempt must be success
#  - upstream absent from a full flow run      -> wait (it will be cascaded in)
#  - upstream absent from a partial flow run,
#    or the run predates flow_runs (NULL)      -> fall back to global latest success
_DEP_MET_SQL = """
    CASE
        WHEN tr.flow_run_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM task_runs d
            WHERE d.task_id = td.depends_on_task_id AND d.flow_run_id = tr.flow_run_id
        ) THEN EXISTS (
            SELECT 1 FROM task_runs d
            WHERE d.task_id = td.depends_on_task_id
            AND d.flow_run_id = tr.flow_run_id
            AND d.status = 'success'
            AND d.run_number = (
                SELECT MAX(run_number) FROM task_runs
                WHERE task_id = td.depends_on_task_id AND flow_run_id = tr.flow_run_id
            )
        )
        WHEN tr.flow_run_id IS NOT NULL AND COALESCE(fr.partial, 0) = 0 THEN 0
        ELSE EXISTS (
            SELECT 1 FROM task_runs d
            WHERE d.task_id = td.depends_on_task_id
            AND d.status = 'success'
            AND d.run_number = (
                SELECT MAX(run_number) FROM task_runs WHERE task_id = td.depends_on_task_id
            )
        )
    END
"""


async def get_queued_ready(db: aiosqlite.Connection, limit: int) -> list[dict]:
    """Get queued runs whose task is active, whose retry delay (not_before) has
    elapsed, whose flow run is dispatchable, and whose upstream deps are met
    within their flow run."""
    cursor = await db.execute(
        f"""SELECT tr.*, t.prompt, t.model, t.work_dir, t.permissions, t.priority, t.sandbox AS task_sandbox,
                  t.secret_keys AS task_secret_keys
           FROM task_runs tr
           JOIN tasks t ON t.id = tr.task_id
           LEFT JOIN flow_runs fr ON fr.id = tr.flow_run_id
           WHERE tr.status = 'queued' AND t.status = 'active'
           AND (tr.not_before IS NULL OR tr.not_before <= datetime('now'))
           AND (tr.flow_run_id IS NULL OR fr.status = 'running')
           AND NOT EXISTS (
               SELECT 1 FROM task_dependencies td
               WHERE td.task_id = tr.task_id
               AND NOT ({_DEP_MET_SQL})
           )
           ORDER BY t.priority DESC, tr.started_at ASC LIMIT ?""",
        (limit,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_latest_successful(db: aiosqlite.Connection, task_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        """SELECT * FROM task_runs WHERE task_id = ? AND status = 'success'
           ORDER BY run_number DESC LIMIT 1""",
        (task_id,),
    )
    return await cursor.fetchone()


async def get_latest_successful_in_flow_run(db: aiosqlite.Connection, task_id: str,
                                            flow_run_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        """SELECT * FROM task_runs
           WHERE task_id = ? AND flow_run_id = ? AND status = 'success'
           ORDER BY run_number DESC LIMIT 1""",
        (task_id, flow_run_id),
    )
    return await cursor.fetchone()


async def get_active_run(db: aiosqlite.Connection, task_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        "SELECT * FROM task_runs WHERE task_id = ? AND status IN ('running', 'queued') ORDER BY run_number DESC LIMIT 1",
        (task_id,),
    )
    return await cursor.fetchone()


async def has_active_run(db: aiosqlite.Connection, task_id: str,
                         flow_run_id: Optional[str] = None) -> bool:
    """Active run check; scoped to one flow run when flow_run_id is given so
    concurrent flow runs of the same task don't block each other."""
    if flow_run_id:
        cursor = await db.execute(
            """SELECT id FROM task_runs
               WHERE task_id = ? AND flow_run_id = ? AND status IN ('queued', 'running')""",
            (task_id, flow_run_id),
        )
    else:
        cursor = await db.execute(
            "SELECT id FROM task_runs WHERE task_id = ? AND status IN ('queued', 'running')",
            (task_id,),
        )
    return await cursor.fetchone() is not None
