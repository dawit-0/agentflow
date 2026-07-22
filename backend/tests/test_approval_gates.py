"""Approval-gate tasks: human-in-the-loop checkpoints inside a flow.

An approval-gate task never invokes a provider. Once its upstream
dependencies succeed, its run starts in 'awaiting_approval' and the flow
stays paused there until a human approves (cascades downstream, like a
success) or rejects via the existing cancel endpoint (cascades cancel,
like a failure).
"""

import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────

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


async def _trigger_flow(client, flow_id):
    resp = await client.post(f"/api/flows/{flow_id}/trigger")
    assert resp.status_code == 200
    return resp.json()


async def _set_run_status(db, run_id, status):
    await db.execute(
        "UPDATE task_runs SET status = ?, finished_at = datetime('now') WHERE id = ?",
        (status, run_id),
    )
    await db.commit()


async def _get_run(db, run_id):
    cursor = await db.execute("SELECT * FROM task_runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _runs_for_task(db, task_id):
    cursor = await db.execute(
        "SELECT * FROM task_runs WHERE task_id = ? ORDER BY run_number", (task_id,)
    )
    return [dict(r) for r in await cursor.fetchall()]


async def _runs_in_flow_run(db, flow_run_id):
    cursor = await db.execute(
        "SELECT * FROM task_runs WHERE flow_run_id = ? ORDER BY started_at", (flow_run_id,)
    )
    return [dict(r) for r in await cursor.fetchall()]


async def _get_flow_run(db, flow_run_id):
    cursor = await db.execute("SELECT * FROM flow_runs WHERE id = ?", (flow_run_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


# ── Task type persistence ────────────────────────────────────────────────────

async def test_create_task_defaults_to_agent_type(client, db):
    task = await _create_task(client)
    assert task["task_type"] == "agent"

    cursor = await db.execute("SELECT task_type FROM tasks WHERE id = ?", (task["id"],))
    row = await cursor.fetchone()
    assert row["task_type"] == "agent"


async def test_create_approval_task(client, db):
    task = await _create_task(client, task_type="approval")
    assert task["task_type"] == "approval"

    cursor = await db.execute("SELECT task_type FROM tasks WHERE id = ?", (task["id"],))
    row = await cursor.fetchone()
    assert row["task_type"] == "approval"


async def test_update_task_type(client, db):
    task = await _create_task(client)
    resp = await client.patch(f"/api/tasks/{task['id']}", json={"task_type": "approval"})
    assert resp.status_code == 200
    assert resp.json()["task_type"] == "approval"


# ── Cascade into an approval gate ────────────────────────────────────────────

async def test_cascade_creates_awaiting_approval_run(client, db):
    """When an approval-gate task's deps are met, its run starts in
    'awaiting_approval' instead of 'queued' — it must not be picked up by
    the dispatcher's normal queued-run poll."""
    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    gate = await _create_task(client, title="Gate", flow_id=flow["id"],
                              task_type="approval", depends_on=[root["id"]])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    root_run = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, root_run["id"], "success")

    orch = _orch()
    await orch._cascade_trigger_downstream(db, root["id"], fr["id"])
    await db.commit()

    gate_runs = await _runs_for_task(db, gate["id"])
    assert len(gate_runs) == 1
    assert gate_runs[0]["status"] == "awaiting_approval"

    from db import task_runs as db_task_runs
    ready = await db_task_runs.get_queued_ready(db, 10)
    assert gate["id"] not in {r["task_id"] for r in ready}


async def test_root_approval_task_starts_awaiting_approval(client, db):
    """An approval gate with no dependencies (a flow root) starts waiting on
    a human immediately — it never gets dispatched to a provider."""
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    runs = await _runs_in_flow_run(db, fr["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "awaiting_approval"


# ── Approve ──────────────────────────────────────────────────────────────────

async def test_approve_cascades_downstream(client, db):
    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    gate = await _create_task(client, title="Gate", flow_id=flow["id"],
                              task_type="approval", depends_on=[root["id"]])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[gate["id"]])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    root_run = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, root_run["id"], "success")

    orch = _orch()
    await orch._cascade_trigger_downstream(db, root["id"], fr["id"])
    await db.commit()

    resp = await client.post(f"/api/tasks/{gate['id']}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    gate_runs = await _runs_for_task(db, gate["id"])
    assert gate_runs[0]["status"] == "success"

    down_runs = await _runs_for_task(db, down["id"])
    assert len(down_runs) == 1
    assert down_runs[0]["status"] == "queued"
    assert down_runs[0]["trigger"] == "dependency"


async def test_approve_with_no_pending_approval_returns_400(client, db):
    task = await _create_task(client, task_type="approval")
    resp = await client.post(f"/api/tasks/{task['id']}/approve")
    assert resp.status_code == 400


async def test_approve_is_idempotent_once_resolved(client, db):
    """A second approve call after the first has already resolved the run
    is a no-op (no pending approval left to act on)."""
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")
    await _trigger_flow(client, flow["id"])

    first = await client.post(f"/api/tasks/{gate['id']}/approve")
    assert first.status_code == 200

    second = await client.post(f"/api/tasks/{gate['id']}/approve")
    assert second.status_code == 400


# ── Reject (via the existing cancel endpoint) ────────────────────────────────

async def test_reject_cascades_cancel_downstream(client, db):
    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    gate = await _create_task(client, title="Gate", flow_id=flow["id"],
                              task_type="approval", depends_on=[root["id"]])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[gate["id"]])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    root_run = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, root_run["id"], "success")

    orch = _orch()
    await orch._cascade_trigger_downstream(db, root["id"], fr["id"])
    await db.commit()

    resp = await client.post(f"/api/tasks/{gate['id']}/cancel")
    assert resp.status_code == 200

    gate_runs = await _runs_for_task(db, gate["id"])
    assert gate_runs[0]["status"] == "cancelled"

    # Downstream never got a run in the first place (deps never became met),
    # so there's nothing to cascade-cancel — confirm it simply never ran.
    down_runs = await _runs_for_task(db, down["id"])
    assert down_runs == []

    flow_run = await _get_flow_run(db, fr["id"])
    assert flow_run["status"] == "failed"


# ── Flow-run lifecycle stays paused ──────────────────────────────────────────

async def test_flow_run_not_finalized_while_awaiting_approval(client, db):
    """A pending approval keeps the flow run open — it must not be silently
    marked successful while a human decision is still outstanding."""
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]

    orch = _orch()
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()

    flow_run = await _get_flow_run(db, fr["id"])
    assert flow_run["status"] == "running"


async def test_flow_run_succeeds_after_approval(client, db):
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")
    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]

    resp = await client.post(f"/api/tasks/{gate['id']}/approve")
    assert resp.status_code == 200

    flow_run = await _get_flow_run(db, fr["id"])
    assert flow_run["status"] == "success"
