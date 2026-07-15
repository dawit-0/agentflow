"""Tests for approval-gated tasks: a task with requires_approval=True must be
approved by a human before its run is eligible for dispatch, and rejecting it
cancels the run and cascades cancellation downstream."""

import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_task(client, title="Task", prompt="do it", **kwargs):
    payload = {"title": title, "prompt": prompt, **kwargs}
    resp = await client.post("/api/tasks", json=payload)
    assert resp.status_code == 200
    return resp.json()


async def _trigger_task(client, task_id):
    resp = await client.post(f"/api/tasks/{task_id}/trigger")
    assert resp.status_code == 200
    return resp.json()


# ── Task config ──────────────────────────────────────────────────────────────

async def test_create_task_with_requires_approval(client, db):
    task = await _create_task(client, requires_approval=True)

    cursor = await db.execute(
        "SELECT requires_approval FROM tasks WHERE id = ?", (task["id"],)
    )
    row = await cursor.fetchone()
    assert row["requires_approval"] == 1


async def test_default_task_does_not_require_approval(client, db):
    task = await _create_task(client)

    cursor = await db.execute(
        "SELECT requires_approval FROM tasks WHERE id = ?", (task["id"],)
    )
    row = await cursor.fetchone()
    assert row["requires_approval"] == 0


async def test_patch_task_to_require_approval(client, db):
    task = await _create_task(client)
    resp = await client.patch(f"/api/tasks/{task['id']}", json={"requires_approval": True})
    assert resp.status_code == 200

    cursor = await db.execute(
        "SELECT requires_approval FROM tasks WHERE id = ?", (task["id"],)
    )
    row = await cursor.fetchone()
    assert row["requires_approval"] == 1


# ── Gating behavior ──────────────────────────────────────────────────────────

async def test_triggering_gated_task_creates_pending_run(client, db):
    """A run for a requires_approval task starts life awaiting approval, not queued for dispatch."""
    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    assert run["status"] == "queued"
    assert run["approval_status"] == "pending"


async def test_triggering_ungated_task_has_no_approval_status(client, db):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    assert run["approval_status"] is None


async def test_pending_approval_run_excluded_from_dispatch(client, db):
    from db import task_runs as db_task_runs

    task = await _create_task(client, requires_approval=True)
    await _trigger_task(client, task["id"])

    ready = await db_task_runs.get_queued_ready(db, 10)
    assert ready == []


async def test_approved_run_becomes_dispatchable(client, db):
    from db import task_runs as db_task_runs

    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    resp = await client.post(f"/api/task-runs/{run['id']}/approve")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    ready = await db_task_runs.get_queued_ready(db, 10)
    assert [r["id"] for r in ready] == [run["id"]]

    row = await db_task_runs.get_by_id(db, run["id"])
    assert row["approval_status"] == "approved"


async def test_rejected_run_is_cancelled(client, db):
    from db import task_runs as db_task_runs

    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    resp = await client.post(f"/api/task-runs/{run['id']}/reject", json={"note": "not safe"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    row = await db_task_runs.get_by_id(db, run["id"])
    assert row["status"] == "cancelled"
    assert row["approval_status"] == "rejected"
    assert row["approval_note"] == "not safe"


async def test_rejecting_cascades_cancel_downstream(client, db):
    from db import task_runs as db_task_runs

    upstream = await _create_task(client, title="Upstream", requires_approval=True)
    downstream = await _create_task(
        client, title="Downstream", depends_on=[upstream["id"]]
    )

    run = await _trigger_task(client, upstream["id"])
    await client.post(f"/api/task-runs/{run['id']}/reject")

    # No run should ever be created for the downstream task since upstream
    # never succeeded.
    cursor = await db.execute(
        "SELECT COUNT(*) FROM task_runs WHERE task_id = ?", (downstream["id"],)
    )
    count = (await cursor.fetchone())[0]
    assert count == 0


async def test_cannot_approve_a_non_pending_run(client, db):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    resp = await client.post(f"/api/task-runs/{run['id']}/approve")
    assert resp.status_code == 200
    assert "error" in resp.json()


async def test_pending_approvals_endpoint_lists_gated_runs(client, db):
    gated = await _create_task(client, requires_approval=True)
    ungated = await _create_task(client)
    gated_run = await _trigger_task(client, gated["id"])
    await _trigger_task(client, ungated["id"])

    resp = await client.get("/api/task-runs/pending-approvals")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids == [gated_run["id"]]
