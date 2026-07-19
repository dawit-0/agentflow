from typing import Optional

import aiosqlite


async def get_edges_for_nodes(db: aiosqlite.Connection,
                               node_ids: set[str]) -> list[dict]:
    placeholders = ",".join("?" for _ in node_ids)
    cursor = await db.execute(
        f"""SELECT task_id, depends_on_task_id, COALESCE(pass_output, 1) as pass_output
            FROM task_dependencies WHERE task_id IN ({placeholders})""",
        list(node_ids),
    )
    return [{"source": r["depends_on_task_id"], "target": r["task_id"],
             "pass_output": bool(r["pass_output"])}
            for r in await cursor.fetchall()]


async def get_upstream(db: aiosqlite.Connection, task_id: str) -> list[str]:
    cursor = await db.execute(
        "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ?", (task_id,)
    )
    return [r["depends_on_task_id"] for r in await cursor.fetchall()]


async def get_downstream(db: aiosqlite.Connection, task_id: str) -> list[dict]:
    cursor = await db.execute(
        "SELECT DISTINCT task_id FROM task_dependencies WHERE depends_on_task_id = ?",
        (task_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def insert(db: aiosqlite.Connection, task_id: str,
                  depends_on_task_id: str) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)",
        (task_id, depends_on_task_id),
    )


async def delete_for_task(db: aiosqlite.Connection, task_id: str) -> None:
    await db.execute(
        "DELETE FROM task_dependencies WHERE task_id = ? OR depends_on_task_id = ?",
        (task_id, task_id),
    )


async def delete_one(db: aiosqlite.Connection, task_id: str,
                      depends_on_task_id: str) -> None:
    await db.execute(
        "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on_task_id = ?",
        (task_id, depends_on_task_id),
    )


async def delete_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute(
        """DELETE FROM task_dependencies
           WHERE task_id IN (SELECT id FROM tasks WHERE flow_id = ?)
           OR depends_on_task_id IN (SELECT id FROM tasks WHERE flow_id = ?)""",
        (flow_id, flow_id),
    )


async def get_upstream_with_config(db: aiosqlite.Connection, task_id: str) -> list[dict]:
    """Get upstream dependencies with their data-passing configuration."""
    cursor = await db.execute(
        """SELECT depends_on_task_id,
                  COALESCE(pass_output, 1) as pass_output,
                  COALESCE(max_output_chars, 4000) as max_output_chars
           FROM task_dependencies WHERE task_id = ?""",
        (task_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def insert_with_config(db: aiosqlite.Connection, task_id: str,
                              depends_on_task_id: str, pass_output: bool = True,
                              max_output_chars: int = 4000) -> None:
    await db.execute(
        """INSERT OR IGNORE INTO task_dependencies
           (task_id, depends_on_task_id, pass_output, max_output_chars)
           VALUES (?, ?, ?, ?)""",
        (task_id, depends_on_task_id, 1 if pass_output else 0, max_output_chars),
    )


async def get_unmet_upstream(db: aiosqlite.Connection, task_id: str) -> list[dict]:
    """Get upstream deps that don't have a successful latest run (global,
    pre-flow_runs semantics — used for legacy runs)."""
    cursor = await db.execute(
        """SELECT td.depends_on_task_id FROM task_dependencies td
           WHERE td.task_id = ?
           AND NOT EXISTS (
               SELECT 1 FROM task_runs tr
               WHERE tr.task_id = td.depends_on_task_id
               AND tr.status = 'success'
               AND tr.run_number = (
                   SELECT MAX(run_number) FROM task_runs WHERE task_id = td.depends_on_task_id
               )
           )""",
        (task_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_unmet_upstream_in_flow_run(db: aiosqlite.Connection, task_id: str,
                                         flow_run_id: str, partial: bool) -> list[dict]:
    """Upstream deps not yet satisfied within the flow run.

    A dep with runs in the flow run must have its latest in-run attempt
    succeed. A dep with no run in the flow run is unmet for full runs
    (it will be cascaded in), but falls back to the global latest success
    for partial (mid-graph) runs.
    """
    cursor = await db.execute(
        """SELECT td.depends_on_task_id FROM task_dependencies td
           WHERE td.task_id = :task_id
           AND NOT (
               CASE
                   WHEN EXISTS (
                       SELECT 1 FROM task_runs d
                       WHERE d.task_id = td.depends_on_task_id AND d.flow_run_id = :fr
                   ) THEN EXISTS (
                       SELECT 1 FROM task_runs d
                       WHERE d.task_id = td.depends_on_task_id
                       AND d.flow_run_id = :fr
                       AND d.status = 'success'
                       AND d.run_number = (
                           SELECT MAX(run_number) FROM task_runs
                           WHERE task_id = td.depends_on_task_id AND flow_run_id = :fr
                       )
                   )
                   WHEN :partial THEN EXISTS (
                       SELECT 1 FROM task_runs d
                       WHERE d.task_id = td.depends_on_task_id
                       AND d.status = 'success'
                       AND d.run_number = (
                           SELECT MAX(run_number) FROM task_runs WHERE task_id = td.depends_on_task_id
                       )
                   )
                   ELSE 0
               END
           )""",
        {"task_id": task_id, "fr": flow_run_id, "partial": 1 if partial else 0},
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_queued_downstream(db: aiosqlite.Connection, task_id: str,
                                flow_run_id: Optional[str] = None) -> list[dict]:
    """Get queued runs for tasks that depend on the given task, scoped to one
    flow run when given so a failure can't cancel another run's tasks."""
    if flow_run_id:
        cursor = await db.execute(
            """SELECT DISTINCT tr.id, tr.task_id FROM task_runs tr
               JOIN task_dependencies td ON td.task_id = tr.task_id
               WHERE td.depends_on_task_id = ? AND tr.status = 'queued'
               AND tr.flow_run_id = ?""",
            (task_id, flow_run_id),
        )
    else:
        cursor = await db.execute(
            """SELECT DISTINCT tr.id, tr.task_id FROM task_runs tr
               JOIN task_dependencies td ON td.task_id = tr.task_id
               WHERE td.depends_on_task_id = ? AND tr.status = 'queued'""",
            (task_id,),
        )
    return [dict(r) for r in await cursor.fetchall()]
