"""Tests for /api/notifications CRUD."""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


async def _insert(db, title: str = "t", kind: str = "task_failed", severity: str = "error"):
    from db import notifications as db_notifications
    record = await db_notifications.insert(
        db, kind=kind, severity=severity, title=title, body="body"
    )
    await db.commit()
    return record


async def test_list_empty(client):
    resp = await client.get("/api/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_insert_and_list_newest_first(client, db):
    a = await _insert(db, title="alpha")
    b = await _insert(db, title="beta")

    resp = await client.get("/api/notifications")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    ids = [r["id"] for r in rows]
    # beta was inserted second, should come first
    assert b["id"] in ids
    assert a["id"] in ids


async def test_unread_count(client, db):
    await _insert(db)
    await _insert(db)
    await _insert(db)

    resp = await client.get("/api/notifications/unread_count")
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 3


async def test_mark_read_marks_single(client, db):
    a = await _insert(db)
    b = await _insert(db)

    resp = await client.post(f"/api/notifications/{a['id']}/read")
    assert resp.status_code == 200

    cursor = await db.execute(
        "SELECT id, read_at FROM notifications ORDER BY id"
    )
    rows = {r["id"]: r["read_at"] for r in await cursor.fetchall()}
    assert rows[a["id"]] is not None
    assert rows[b["id"]] is None

    count_resp = await client.get("/api/notifications/unread_count")
    assert count_resp.json()["unread_count"] == 1


async def test_mark_all_read(client, db):
    await _insert(db)
    await _insert(db)
    await _insert(db)

    resp = await client.post("/api/notifications/read_all")
    assert resp.status_code == 200
    assert resp.json()["marked"] == 3

    count_resp = await client.get("/api/notifications/unread_count")
    assert count_resp.json()["unread_count"] == 0


async def test_unread_only_filter(client, db):
    a = await _insert(db, title="to-read")
    await _insert(db, title="unread")
    await client.post(f"/api/notifications/{a['id']}/read")

    resp = await client.get("/api/notifications", params={"unread_only": "true"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["title"] == "unread"
