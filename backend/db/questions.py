import uuid
from typing import Optional

import aiosqlite


async def insert_approval_request(db: aiosqlite.Connection, task_run_id: str,
                                   task_id: str, question: str) -> dict:
    """Record an approval-gate request. Reuses the generic questions table:
    `question` holds the human-readable prompt, `answer` later holds the
    reviewer's optional comment."""
    qid = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO questions (id, task_run_id, task_id, question)
           VALUES (?, ?, ?, ?)""",
        (qid, task_run_id, task_id, question),
    )
    cursor = await db.execute("SELECT * FROM questions WHERE id = ?", (qid,))
    row = await cursor.fetchone()
    return dict(row) if row else {"id": qid}


async def get_by_run(db: aiosqlite.Connection, task_run_id: str) -> Optional[dict]:
    cursor = await db.execute(
        "SELECT * FROM questions WHERE task_run_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_run_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_pending(db: aiosqlite.Connection) -> list[dict]:
    """Pending approval requests, newest first, joined with task/flow context."""
    cursor = await db.execute(
        """SELECT q.*, t.title AS task_title, t.flow_id AS flow_id,
                  t.model AS model, t.permissions AS permissions,
                  tr.trigger AS run_trigger, tr.run_number AS run_number,
                  f.name AS flow_name
           FROM questions q
           JOIN tasks t ON t.id = q.task_id
           JOIN task_runs tr ON tr.id = q.task_run_id
           LEFT JOIN flows f ON f.id = t.flow_id
           WHERE q.status = 'pending'
           ORDER BY q.created_at DESC"""
    )
    return [dict(r) for r in await cursor.fetchall()]


async def answer(db: aiosqlite.Connection, question_id: str, answer_text: Optional[str]) -> None:
    await db.execute(
        """UPDATE questions SET status = 'answered', answer = ?,
           answered_at = datetime('now') WHERE id = ?""",
        (answer_text, question_id),
    )


async def delete_by_task(db: aiosqlite.Connection, task_id: str) -> None:
    await db.execute("DELETE FROM questions WHERE task_id = ?", (task_id,))


async def delete_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    await db.execute(
        """DELETE FROM questions
           WHERE task_id IN (SELECT id FROM tasks WHERE flow_id = ?)""",
        (flow_id,),
    )
