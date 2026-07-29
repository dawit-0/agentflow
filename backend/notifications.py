"""Notification service: decides when to create notifications and emits them.

Pure functions — orchestrator passes `db` and `sio` in, no globals.
"""

from typing import Optional

import aiosqlite

from db import notifications as db_notifications
from db import settings as db_settings


MAX_BODY_LEN = 500


async def _emit_new(sio, record: dict, unread_count: int) -> None:
    """Emit a `notification:new` Socket.IO event with the record and the new unread count."""
    if sio is None:
        return
    await sio.emit("notification:new", {"notification": record, "unread_count": unread_count})


async def maybe_notify_run_finished(
    db: aiosqlite.Connection,
    sio,
    *,
    task: dict,
    task_run_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> Optional[dict]:
    """Create a notification for a finished run if settings opt in. Returns the created record or None."""
    settings = await db_settings.get_all(db)
    title_prefix = None
    kind = None
    severity = "info"

    if status == "failed" and settings.get("notify_on_task_failure"):
        title_prefix = "Task failed"
        kind = "task_failed"
        severity = "error"
    elif status == "success" and settings.get("notify_on_task_success"):
        title_prefix = "Task succeeded"
        kind = "task_succeeded"
        severity = "info"
    else:
        return None

    body = (error_message or "")[:MAX_BODY_LEN] if error_message else None
    task_title = task.get("title") or task.get("id", "")[:8]

    record = await db_notifications.insert(
        db,
        kind=kind,
        severity=severity,
        title=f"{title_prefix}: {task_title}",
        body=body,
        task_id=task.get("id"),
        task_run_id=task_run_id,
        flow_id=task.get("flow_id"),
    )
    count = await db_notifications.unread_count(db)
    await _emit_new(sio, record, count)
    return record


async def notify_approval_requested(
    db: aiosqlite.Connection,
    sio,
    *,
    task: dict,
    task_run_id: str,
) -> Optional[dict]:
    """Create a notification when a run is gated behind an approval requirement."""
    settings = await db_settings.get_all(db)
    if not settings.get("notify_on_approval_requested"):
        return None

    task_title = task.get("title") or task.get("id", "")[:8]

    record = await db_notifications.insert(
        db,
        kind="approval_requested",
        severity="warning",
        title=f"Approval requested: {task_title}",
        body="This task is waiting for approval before it can run.",
        task_id=task.get("id"),
        task_run_id=task_run_id,
        flow_id=task.get("flow_id"),
    )
    count = await db_notifications.unread_count(db)
    await _emit_new(sio, record, count)
    return record


async def notify_flow_completed(
    db: aiosqlite.Connection,
    sio,
    *,
    flow_id: str,
    flow_name: str,
    failed: bool,
    total_tasks: int,
    failed_tasks: int,
) -> Optional[dict]:
    """Create a notification when a whole flow reaches a terminal state."""
    settings = await db_settings.get_all(db)
    if not settings.get("notify_on_flow_completion"):
        return None

    if failed:
        kind = "flow_failed"
        severity = "error"
        title = f"Flow failed: {flow_name}"
        body = f"{failed_tasks}/{total_tasks} tasks failed"
    else:
        kind = "flow_completed"
        severity = "info"
        title = f"Flow completed: {flow_name}"
        body = f"{total_tasks} tasks finished successfully"

    record = await db_notifications.insert(
        db,
        kind=kind,
        severity=severity,
        title=title,
        body=body,
        flow_id=flow_id,
    )
    count = await db_notifications.unread_count(db)
    await _emit_new(sio, record, count)
    return record
