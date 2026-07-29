"""Approval gates: tasks flagged `requires_approval` pause before running
until a human approves or rejects the queued run via /api/approvals.
"""

import pytest

pytestmark = pytest.mark.asyncio


class StubSio:
    def __init__(self):
        self.events = []

    async def emit(self, event, data=None):
        self.events.append((event, data))


def _orch():
    from orchestrator import Orchestrator
    return Orchestrator(StubSio())


async def _create_flow(client, name="Test Flow", **kwargs):
    resp = await client.post("/api/flows", json={"name": name, **kwargs})
    assert resp.status_code == 200
    return resp.json()


async def _create_task(client, title="Task", prompt="do it", **kwargs):
    resp = await client.post("/api/tasks", json={"title": title, "prompt": prompt, **kwargs})
    assert resp.status_code == 200
    return resp.json()


async def _trigger_task(client, task_id):
    resp = await client.post(f"/api/tasks/{task_id}/trigger")
    assert resp.status_code == 200
    return resp.json()


# ── Task config ──────────────────────────────────────────────────────────────

async def test_create_task_with_requires_approval(client, db):
    task = await _create_task(client, requires_approval=True)
    assert task["requires_approval"] == 1

    cursor = await db.execute("SELECT requires_approval FROM tasks WHERE id = ?", (task["id"],))
    row = await cursor.fetchone()
    assert row["requires_approval"] == 1


async def test_create_task_default_requires_approval(client, db):
    task = await _create_task(client)
    assert task["requires_approval"] in (0, False, None)


async def test_update_task_requires_approval(client, db):
    task = await _create_task(client)
    resp = await client.patch(f"/api/tasks/{task['id']}", json={"requires_approval": True})
    assert resp.status_code == 200

    cursor = await db.execute("SELECT requires_approval FROM tasks WHERE id = ?", (task["id"],))
    row = await cursor.fetchone()
    assert row["requires_approval"] == 1


# ── Gating ───────────────────────────────────────────────────────────────────

async def test_gated_run_awaits_approval(client, db):
    """A queued run of a requires_approval task is gated instead of dispatched."""
    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    orch = _orch()
    await orch._check_pending_approvals()

    cursor = await db.execute("SELECT approval_status, status FROM task_runs WHERE id = ?", (run["id"],))
    row = await cursor.fetchone()
    assert row["approval_status"] == "pending"
    assert row["status"] == "queued"  # still queued — just gated, not running

    cursor = await db.execute(
        "SELECT * FROM questions WHERE task_run_id = ?", (run["id"],)
    )
    q = await cursor.fetchone()
    assert q is not None
    assert q["status"] == "pending"
    assert task["title"] in q["question"]


async def test_gate_is_idempotent(client, db):
    """Running the gate check twice doesn't create a second approval request."""
    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    orch = _orch()
    await orch._check_pending_approvals()
    await orch._check_pending_approvals()

    cursor = await db.execute("SELECT COUNT(*) FROM questions WHERE task_run_id = ?", (run["id"],))
    count = (await cursor.fetchone())[0]
    assert count == 1


async def test_gated_run_excluded_from_dispatch(client, db):
    """get_queued_ready must not surface a run still awaiting approval."""
    from db import task_runs as db_task_runs

    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    orch = _orch()
    await orch._check_pending_approvals()

    ready = await db_task_runs.get_queued_ready(db, 10)
    assert run["id"] not in [r["id"] for r in ready]


async def test_ungated_task_dispatches_normally_alongside_gated_one(client, db):
    """A gated run blocks only itself — an unrelated task still dispatches."""
    from db import task_runs as db_task_runs

    gated_task = await _create_task(client, title="Gated", requires_approval=True)
    normal_task = await _create_task(client, title="Normal")

    gated_run = await _trigger_task(client, gated_task["id"])
    normal_run = await _trigger_task(client, normal_task["id"])

    orch = _orch()
    await orch._check_pending_approvals()

    ready_ids = [r["id"] for r in await db_task_runs.get_queued_ready(db, 10)]
    assert normal_run["id"] in ready_ids
    assert gated_run["id"] not in ready_ids


async def test_list_pending_approvals(client, db):
    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    orch = _orch()
    await orch._check_pending_approvals()

    resp = await client.get("/api/approvals")
    assert resp.status_code == 200
    pending = resp.json()
    assert len(pending) == 1
    assert pending[0]["task_run_id"] == run["id"]
    assert pending[0]["task_title"] == task["title"]


# ── Approve / Reject ─────────────────────────────────────────────────────────

async def test_approve_run_unblocks_dispatch(client, db):
    from db import task_runs as db_task_runs

    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    orch = _orch()
    await orch._check_pending_approvals()

    resp = await client.post(f"/api/approvals/{run['id']}/approve", json={"comment": "looks safe"})
    assert resp.status_code == 200
    assert resp.json()["decision"] == "approved"

    cursor = await db.execute("SELECT approval_status, status FROM task_runs WHERE id = ?", (run["id"],))
    row = await cursor.fetchone()
    assert row["approval_status"] == "approved"
    assert row["status"] == "queued"

    ready_ids = [r["id"] for r in await db_task_runs.get_queued_ready(db, 10)]
    assert run["id"] in ready_ids

    cursor = await db.execute("SELECT status, answer FROM questions WHERE task_run_id = ?", (run["id"],))
    q = await cursor.fetchone()
    assert q["status"] == "answered"
    assert q["answer"] == "looks safe"


async def test_reject_run_cancels_it(client, db):
    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    orch = _orch()
    await orch._check_pending_approvals()

    resp = await client.post(f"/api/approvals/{run['id']}/reject", json={"comment": "too risky"})
    assert resp.status_code == 200
    assert resp.json()["decision"] == "rejected"

    cursor = await db.execute(
        "SELECT approval_status, status, error_message FROM task_runs WHERE id = ?", (run["id"],)
    )
    row = await cursor.fetchone()
    assert row["approval_status"] == "rejected"
    assert row["status"] == "cancelled"
    assert "too risky" in row["error_message"]


async def test_reject_finalizes_flow_run(client, db):
    """Rejecting the only queued member closes out its flow run as failed."""
    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    cursor = await db.execute("SELECT flow_run_id FROM task_runs WHERE id = ?", (run["id"],))
    flow_run_id = (await cursor.fetchone())["flow_run_id"]

    orch = _orch()
    await orch._check_pending_approvals()
    await client.post(f"/api/approvals/{run['id']}/reject")

    cursor = await db.execute("SELECT status FROM flow_runs WHERE id = ?", (flow_run_id,))
    row = await cursor.fetchone()
    assert row["status"] == "failed"


async def test_decide_without_pending_approval_404s(client, db):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    resp = await client.post(f"/api/approvals/{run['id']}/approve")
    assert resp.status_code == 404

    resp = await client.post(f"/api/approvals/{run['id']}/reject")
    assert resp.status_code == 404


async def test_double_decision_rejected(client, db):
    """Once a run has been decided, deciding it again 404s."""
    task = await _create_task(client, requires_approval=True)
    run = await _trigger_task(client, task["id"])

    orch = _orch()
    await orch._check_pending_approvals()

    resp = await client.post(f"/api/approvals/{run['id']}/approve")
    assert resp.status_code == 200

    resp = await client.post(f"/api/approvals/{run['id']}/approve")
    assert resp.status_code == 404
