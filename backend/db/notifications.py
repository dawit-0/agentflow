"""Persistent notification log."""

import uuid
from typing import Optional

import aiosqlite


VALID_KINDS = {"task_failed", "task_succeeded", "flow_completed", "flow_failed", "approval_requested"}
VALID_SEVERITIES = {"info", "warning", "error"}


async def insert(
    db: aiosqlite.Connection,
    *,
    kind: str,
    severity: str,
    title: str,
    body: Optional[str] = None,
    task_id: Optional[str] = None,
    task_run_id: Optional[str] = None,
    flow_id: Optional[str] = None,
) -> dict:
    nid = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO notifications
             (id, kind, severity, title, body, task_id, task_run_id, flow_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (nid, kind, severity, title, body, task_id, task_run_id, flow_id),
    )
    cursor = await db.execute("SELECT * FROM notifications WHERE id = ?", (nid,))
    row = await cursor.fetchone()
    return dict(row) if row else {"id": nid}


async def list_recent(
    db: aiosqlite.Connection, limit: int = 50, unread_only: bool = False
) -> list[dict]:
    if unread_only:
        cursor = await db.execute(
            """SELECT * FROM notifications
               WHERE read_at IS NULL
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in await cursor.fetchall()]


async def mark_read(db: aiosqlite.Connection, nid: str) -> None:
    await db.execute(
        "UPDATE notifications SET read_at = datetime('now') WHERE id = ? AND read_at IS NULL",
        (nid,),
    )


async def mark_all_read(db: aiosqlite.Connection) -> int:
    cursor = await db.execute(
        "UPDATE notifications SET read_at = datetime('now') WHERE read_at IS NULL"
    )
    return cursor.rowcount or 0


async def unread_count(db: aiosqlite.Connection) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM notifications WHERE read_at IS NULL"
    )
    return (await cursor.fetchone())[0] or 0
