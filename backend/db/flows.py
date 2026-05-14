from typing import Optional

import aiosqlite


_SELECT_WITH_LAST_RUN = """
    SELECT f.*,
           (SELECT MAX(tr.started_at) FROM task_runs tr
            JOIN tasks t ON t.id = tr.task_id
            WHERE t.flow_id = f.id) AS computed_last_run
    FROM flows f
"""


def _project_last_run(row: aiosqlite.Row) -> dict:
    d = dict(row)
    computed = d.pop("computed_last_run", None)
    if computed:
        d["last_run_at"] = computed
    return d


async def list_active(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        _SELECT_WITH_LAST_RUN + " WHERE f.archived = 0 ORDER BY f.created_at DESC"
    )
    return [_project_last_run(r) for r in await cursor.fetchall()]


async def get_by_id(db: aiosqlite.Connection, flow_id: str) -> Optional[dict]:
    cursor = await db.execute(
        _SELECT_WITH_LAST_RUN + " WHERE f.id = ?", (flow_id,)
    )
    row = await cursor.fetchone()
    return _project_last_run(row) if row else None


async def insert(db: aiosqlite.Connection, flow_id: str, name: str,
                 description: str = "", schedule: Optional[str] = None,
                 next_run_at: Optional[str] = None) -> None:
    await db.execute(
        "INSERT INTO flows (id, name, description, schedule, next_run_at) VALUES (?, ?, ?, ?, ?)",
        (flow_id, name, description, schedule, next_run_at),
    )


async def update_fields(db: aiosqlite.Connection, flow_id: str,
                         updates: list[str], params: list) -> None:
    params.append(flow_id)
    await db.execute(
        f"UPDATE flows SET {', '.join(updates)} WHERE id = ?",
        params,
    )


async def archive(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute(
        "UPDATE flows SET archived = 1 WHERE id = ?", (flow_id,)
    )


async def update_schedule_times(db: aiosqlite.Connection, flow_id: str,
                                 last_run_at: str, next_run_at: str) -> None:
    await db.execute(
        "UPDATE flows SET last_run_at = ?, next_run_at = ? WHERE id = ?",
        (last_run_at, next_run_at, flow_id),
    )


async def get_due_scheduled(db: aiosqlite.Connection, now_str: str) -> list[dict]:
    cursor = await db.execute(
        """SELECT * FROM flows
           WHERE archived = 0 AND schedule IS NOT NULL
           AND schedule_enabled = 1 AND next_run_at IS NOT NULL
           AND next_run_at <= ?""",
        (now_str,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def clear_agent_flow_references(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute(
        "UPDATE agents SET default_flow_id = NULL WHERE default_flow_id = ?",
        (flow_id,),
    )
