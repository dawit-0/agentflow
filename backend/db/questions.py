import uuid
from typing import Optional

import aiosqlite


async def insert(db: aiosqlite.Connection, task_run_id: str, task_id: str,
                 question: str) -> dict:
    qid = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO questions (id, task_run_id, task_id, question)
           VALUES (?, ?, ?, ?)""",
        (qid, task_run_id, task_id, question),
    )
    cursor = await db.execute("SELECT * FROM questions WHERE id = ?", (qid,))
    row = await cursor.fetchone()
    return dict(row)


async def get_pending_for_run(db: aiosqlite.Connection,
                               task_run_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        """SELECT * FROM questions WHERE task_run_id = ? AND status = 'pending'
           ORDER BY created_at DESC LIMIT 1""",
        (task_run_id,),
    )
    return await cursor.fetchone()


async def get_latest_for_run(db: aiosqlite.Connection,
                              task_run_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        "SELECT * FROM questions WHERE task_run_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_run_id,),
    )
    return await cursor.fetchone()


async def answer(db: aiosqlite.Connection, question_id: str, decision: str,
                 note: Optional[str]) -> None:
    await db.execute(
        """UPDATE questions SET answer = ?, note = ?, status = 'answered',
           answered_at = datetime('now') WHERE id = ?""",
        (decision, note, question_id),
    )


async def mark_timeout(db: aiosqlite.Connection, question_id: str, decision: str,
                       note: Optional[str]) -> None:
    await db.execute(
        """UPDATE questions SET answer = ?, note = ?, status = 'timeout',
           answered_at = datetime('now') WHERE id = ?""",
        (decision, note, question_id),
    )


async def list_pending_task_ids(db: aiosqlite.Connection) -> set:
    cursor = await db.execute("SELECT DISTINCT task_id FROM questions WHERE status = 'pending'")
    return {r[0] for r in await cursor.fetchall()}


async def get_pending_with_timeout(db: aiosqlite.Connection) -> list[dict]:
    """Pending questions whose task run has been waiting longer than the
    task's configured approval_timeout_seconds. Scoped to runs still
    'running' so a cancelled gate is never auto-resolved."""
    cursor = await db.execute(
        """SELECT q.*, tr.flow_run_id, t.approval_timeout_seconds, t.approval_default
           FROM questions q
           JOIN task_runs tr ON tr.id = q.task_run_id
           JOIN tasks t ON t.id = q.task_id
           WHERE q.status = 'pending' AND tr.status = 'running'
           AND t.approval_timeout_seconds IS NOT NULL
           AND datetime(tr.started_at, '+' || t.approval_timeout_seconds || ' seconds') <= datetime('now')"""
    )
    return [dict(r) for r in await cursor.fetchall()]


async def delete_by_task(db: aiosqlite.Connection, task_id: str) -> None:
    await db.execute("DELETE FROM questions WHERE task_id = ?", (task_id,))


async def delete_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute(
        """DELETE FROM questions
           WHERE task_id IN (SELECT id FROM tasks WHERE flow_id = ?)""",
        (flow_id,),
    )
