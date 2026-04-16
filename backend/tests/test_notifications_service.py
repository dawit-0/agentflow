"""Tests for the notification service layer (pure function, no HTTP)."""

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


async def _set_setting(db, key: str, value: bool) -> None:
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, "1" if value else "0"),
    )
    await db.commit()


async def _task(db, title: str = "My task") -> dict:
    fid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    await db.execute("INSERT INTO flows (id, name) VALUES (?, ?)", (fid, "f"))
    await db.execute(
        "INSERT INTO tasks (id, title, prompt, flow_id) VALUES (?, ?, ?, ?)",
        (tid, title, "p", fid),
    )
    await db.commit()
    return {"id": tid, "title": title, "flow_id": fid}


async def test_failure_creates_notification_when_enabled(db):
    from notifications import maybe_notify_run_finished

    task = await _task(db, "Failing task")
    await _set_setting(db, "notify_on_task_failure", True)

    sio = AsyncMock()
    record = await maybe_notify_run_finished(
        db, sio, task=task, task_run_id="run-1",
        status="failed", error_message="stderr blob",
    )
    await db.commit()

    assert record is not None
    assert record["kind"] == "task_failed"
    assert record["severity"] == "error"
    assert "Failing task" in record["title"]
    assert record["body"] == "stderr blob"

    cursor = await db.execute("SELECT COUNT(*) FROM notifications")
    assert (await cursor.fetchone())[0] == 1

    sio.emit.assert_awaited_once()
    event_name, payload = sio.emit.await_args.args
    assert event_name == "notification:new"
    assert payload["unread_count"] == 1


async def test_failure_skipped_when_disabled(db):
    from notifications import maybe_notify_run_finished

    task = await _task(db)
    await _set_setting(db, "notify_on_task_failure", False)

    sio = AsyncMock()
    result = await maybe_notify_run_finished(
        db, sio, task=task, task_run_id="r", status="failed", error_message="x",
    )
    assert result is None

    cursor = await db.execute("SELECT COUNT(*) FROM notifications")
    assert (await cursor.fetchone())[0] == 0
    sio.emit.assert_not_awaited()


async def test_success_respects_toggle(db):
    from notifications import maybe_notify_run_finished

    task = await _task(db)

    await _set_setting(db, "notify_on_task_success", False)
    sio = AsyncMock()
    assert await maybe_notify_run_finished(
        db, sio, task=task, task_run_id="r1", status="success"
    ) is None

    await _set_setting(db, "notify_on_task_success", True)
    sio = AsyncMock()
    record = await maybe_notify_run_finished(
        db, sio, task=task, task_run_id="r2", status="success"
    )
    await db.commit()
    assert record is not None
    assert record["kind"] == "task_succeeded"
    sio.emit.assert_awaited_once()


async def test_error_message_truncated_to_500_chars(db):
    from notifications import maybe_notify_run_finished

    task = await _task(db)
    await _set_setting(db, "notify_on_task_failure", True)

    sio = AsyncMock()
    record = await maybe_notify_run_finished(
        db, sio, task=task, task_run_id="r",
        status="failed", error_message="x" * 2000,
    )
    await db.commit()
    assert record is not None
    assert len(record["body"]) == 500


async def test_notify_flow_completed_respects_setting(db):
    from notifications import notify_flow_completed

    await _set_setting(db, "notify_on_flow_completion", False)
    sio = AsyncMock()
    result = await notify_flow_completed(
        db, sio, flow_id="f1", flow_name="Flow A",
        failed=False, total_tasks=3, failed_tasks=0,
    )
    assert result is None
    sio.emit.assert_not_awaited()


async def test_notify_flow_completed_success_and_failure(db):
    from notifications import notify_flow_completed

    await _set_setting(db, "notify_on_flow_completion", True)

    sio = AsyncMock()
    ok = await notify_flow_completed(
        db, sio, flow_id="f1", flow_name="Flow A",
        failed=False, total_tasks=3, failed_tasks=0,
    )
    await db.commit()
    assert ok["kind"] == "flow_completed"
    assert ok["severity"] == "info"

    sio2 = AsyncMock()
    bad = await notify_flow_completed(
        db, sio2, flow_id="f2", flow_name="Flow B",
        failed=True, total_tasks=3, failed_tasks=2,
    )
    await db.commit()
    assert bad["kind"] == "flow_failed"
    assert bad["severity"] == "error"
    assert "2/3" in bad["body"]
