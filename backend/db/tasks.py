from typing import Optional

import aiosqlite


async def list_all(db: aiosqlite.Connection, flow_id: Optional[str] = None,
                   status: Optional[str] = None) -> list[aiosqlite.Row]:
    query = "SELECT * FROM tasks WHERE 1=1"
    params = []
    if flow_id:
        query += " AND flow_id = ?"
        params.append(flow_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    cursor = await db.execute(query, params)
    return await cursor.fetchall()


async def get_by_id(db: aiosqlite.Connection, task_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return await cursor.fetchone()


async def exists(db: aiosqlite.Connection, task_id: str) -> bool:
    cursor = await db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
    return await cursor.fetchone() is not None


async def insert(db: aiosqlite.Connection, task_id: str, title: str, prompt: str,
                 model: str, priority: int, work_dir: str, flow_id: str,
                 agent_id: Optional[str], permissions_json: str,
                 schedule: Optional[str], next_run_at: Optional[str],
                 max_retries: int, retry_delay_seconds: int,
                 sandbox: str = "", task_type: str = "agent") -> None:
    await db.execute(
        """INSERT INTO tasks (id, title, prompt, model, priority, work_dir, flow_id,
                              agent_id, permissions, schedule, next_run_at,
                              max_retries, retry_delay_seconds, sandbox, task_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (task_id, title, prompt, model, priority, work_dir, flow_id,
         agent_id, permissions_json, schedule, next_run_at,
         max_retries, retry_delay_seconds, sandbox, task_type),
    )


async def insert_quick(db: aiosqlite.Connection, task_id: str, title: str,
                        prompt: str, model: str, work_dir: str, flow_id: str,
                        permissions_json: str, schedule: Optional[str],
                        next_run_at: Optional[str], max_retries: int,
                        retry_delay_seconds: int, sandbox: str = "") -> None:
    await db.execute(
        """INSERT INTO tasks (id, title, prompt, model, work_dir, flow_id,
                              permissions, schedule, next_run_at,
                              max_retries, retry_delay_seconds, sandbox)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (task_id, title, prompt, model, work_dir, flow_id,
         permissions_json, schedule, next_run_at, max_retries,
         retry_delay_seconds, sandbox),
    )


async def insert_spawned(db: aiosqlite.Connection, task_id: str, title: str,
                          prompt: str, model: str, priority: int, work_dir: str,
                          flow_id: str, permissions_json: str,
                          agent_id: str, sandbox: str = "") -> None:
    await db.execute(
        """INSERT INTO tasks (id, title, prompt, model, priority, work_dir, flow_id, permissions, agent_id, sandbox)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (task_id, title, prompt, model, priority, work_dir, flow_id, permissions_json, agent_id, sandbox),
    )


async def update_fields(db: aiosqlite.Connection, task_id: str,
                          updates: list[str], params: list) -> None:
    params.append(task_id)
    await db.execute(
        f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
        params,
    )


async def delete(db: aiosqlite.Connection, task_id: str) -> None:
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


async def delete_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute("DELETE FROM tasks WHERE flow_id = ?", (flow_id,))


async def get_dag_nodes(db: aiosqlite.Connection,
                         flow_id: Optional[str] = None) -> list[dict]:
    if flow_id:
        cursor = await db.execute(
            """SELECT t.id, t.title, t.status, t.model, t.schedule, t.max_retries, t.retry_delay_seconds,
                      t.task_type, t.created_at, t.updated_at,
                      tr.status as latest_run_status, tr.run_number as latest_run_number,
                      tr.attempt_number, tr.trigger as latest_run_trigger
               FROM tasks t
               LEFT JOIN task_runs tr ON tr.task_id = t.id AND tr.run_number = (
                   SELECT MAX(run_number) FROM task_runs WHERE task_id = t.id
               )
               WHERE t.flow_id = ? ORDER BY t.created_at ASC""",
            (flow_id,),
        )
    else:
        cursor = await db.execute(
            """SELECT t.id, t.title, t.status, t.model, t.schedule, t.max_retries, t.retry_delay_seconds,
                      t.task_type, t.created_at, t.updated_at,
                      tr.status as latest_run_status, tr.run_number as latest_run_number,
                      tr.attempt_number, tr.trigger as latest_run_trigger
               FROM tasks t
               LEFT JOIN task_runs tr ON tr.task_id = t.id AND tr.run_number = (
                   SELECT MAX(run_number) FROM task_runs WHERE task_id = t.id
               )
               ORDER BY t.created_at ASC"""
        )
    return [dict(r) for r in await cursor.fetchall()]


async def get_due_scheduled(db: aiosqlite.Connection, now_str: str) -> list[dict]:
    cursor = await db.execute(
        """SELECT * FROM tasks
           WHERE status = 'active' AND schedule IS NOT NULL
           AND schedule_enabled = 1 AND next_run_at IS NOT NULL
           AND next_run_at <= ?""",
        (now_str,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def update_schedule_times(db: aiosqlite.Connection, task_id: str,
                                 last_run_at: str, next_run_at: str) -> None:
    await db.execute(
        "UPDATE tasks SET last_run_at = ?, next_run_at = ?, updated_at = datetime('now') WHERE id = ?",
        (last_run_at, next_run_at, task_id),
    )


async def get_root_tasks(db: aiosqlite.Connection, flow_id: str) -> list[dict]:
    cursor = await db.execute(
        """SELECT t.id, t.task_type FROM tasks t
           WHERE t.flow_id = ? AND t.status = 'active'
           AND NOT EXISTS (
               SELECT 1 FROM task_dependencies td WHERE td.task_id = t.id
           )""",
        (flow_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_root_tasks_alt(db: aiosqlite.Connection, flow_id: str) -> list[dict]:
    """Get root tasks using tasks.id reference (used in orchestrator flow schedules)."""
    cursor = await db.execute(
        """SELECT id FROM tasks
           WHERE flow_id = ? AND status = 'active'
           AND NOT EXISTS (
               SELECT 1 FROM task_dependencies td WHERE td.task_id = tasks.id
           )""",
        (flow_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_retry_config(db: aiosqlite.Connection, task_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        "SELECT max_retries, retry_delay_seconds FROM tasks WHERE id = ?", (task_id,)
    )
    return await cursor.fetchone()


async def get_resumable_failed_tasks(db: aiosqlite.Connection, flow_id: str) -> list[dict]:
    cursor = await db.execute(
        """SELECT t.id, t.task_type FROM tasks t
           JOIN task_runs tr ON tr.task_id = t.id AND tr.run_number = (
               SELECT MAX(run_number) FROM task_runs WHERE task_id = t.id
           )
           WHERE t.flow_id = ? AND t.status = 'active'
           AND tr.status IN ('failed', 'cancelled')
           AND NOT EXISTS (
               SELECT 1 FROM task_dependencies td
               JOIN task_runs dep_run ON dep_run.task_id = td.depends_on_task_id
               AND dep_run.run_number = (
                   SELECT MAX(run_number) FROM task_runs WHERE task_id = td.depends_on_task_id
               )
               WHERE td.task_id = t.id AND dep_run.status IN ('failed', 'cancelled')
           )""",
        (flow_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]
