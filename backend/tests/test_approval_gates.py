import pytest


pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_flow(client, name="Test Flow", **kwargs):
    payload = {"name": name, **kwargs}
    resp = await client.post("/api/flows", json=payload)
    assert resp.status_code == 200
    return resp.json()


async def _create_task(client, title="Task", prompt="do it", **kwargs):
    payload = {"title": title, "prompt": prompt, **kwargs}
    resp = await client.post("/api/tasks", json=payload)
    assert resp.status_code == 200
    return resp.json()


async def _trigger_task(client, task_id):
    resp = await client.post(f"/api/tasks/{task_id}/trigger")
    assert resp.status_code == 200
    return resp.json()


async def _simulate_dispatch(db, run_id, task_id, question_text="Proceed?"):
    """Simulate what the orchestrator's poll loop does when it dispatches a
    queued approval run: flip it to running and open a pending question."""
    await db.execute(
        "UPDATE task_runs SET status = 'running', started_at = datetime('now') WHERE id = ?",
        (run_id,),
    )
    import uuid
    qid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO questions (id, task_run_id, task_id, question) VALUES (?, ?, ?, ?)",
        (qid, run_id, task_id, question_text),
    )
    await db.commit()
    return qid


# ── Task creation ────────────────────────────────────────────────────────────

async def test_create_approval_task(client, db):
    """Approval-gate tasks persist their type and default resolution."""
    task = await _create_task(
        client, task_type="approval", approval_timeout_seconds=3600,
        approval_default="approve",
    )
    assert task["task_type"] == "approval"
    assert task["approval_timeout_seconds"] == 3600
    assert task["approval_default"] == "approve"

    cursor = await db.execute(
        "SELECT task_type, approval_timeout_seconds, approval_default FROM tasks WHERE id = ?",
        (task["id"],),
    )
    row = await cursor.fetchone()
    assert row["task_type"] == "approval"
    assert row["approval_timeout_seconds"] == 3600
    assert row["approval_default"] == "approve"


async def test_create_task_defaults_to_agent(client):
    """Plain tasks default to task_type='agent'."""
    task = await _create_task(client)
    assert task["task_type"] == "agent"
    assert task["approval_default"] == "reject"


async def test_create_task_rejects_bad_task_type(client):
    resp = await client.post("/api/tasks", json={
        "title": "x", "prompt": "y", "task_type": "not-a-type",
    })
    assert resp.status_code == 400


# ── Answering a pending gate ─────────────────────────────────────────────────

async def test_answer_approve_succeeds_run_and_cascades(client, db):
    """Approving a gate marks the run 'success' and queues the downstream task."""
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval",
                               prompt="Deploy to prod?")
    downstream = await _create_task(client, title="Deploy", flow_id=flow["id"],
                                     depends_on=[gate["id"]])

    run = await _trigger_task(client, gate["id"])
    await _simulate_dispatch(db, run["id"], gate["id"], "Deploy to prod?")

    resp = await client.post(f"/api/task-runs/{run['id']}/answer", json={"decision": "approve"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"

    cursor = await db.execute("SELECT status FROM task_runs WHERE id = ?", (run["id"],))
    row = await cursor.fetchone()
    assert row["status"] == "success"

    cursor = await db.execute(
        "SELECT status, answer FROM questions WHERE task_run_id = ?", (run["id"],)
    )
    q = await cursor.fetchone()
    assert q["status"] == "answered"
    assert q["answer"] == "approve"

    # Downstream task should have been cascaded into a queued run
    cursor = await db.execute(
        "SELECT status FROM task_runs WHERE task_id = ?", (downstream["id"],)
    )
    d = await cursor.fetchone()
    assert d is not None
    assert d["status"] == "queued"


async def test_answer_reject_fails_run_and_blocks_downstream(client, db):
    """Rejecting a gate marks the run 'failed' and downstream never queues."""
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")
    downstream = await _create_task(client, title="Deploy", flow_id=flow["id"],
                                     depends_on=[gate["id"]])

    run = await _trigger_task(client, gate["id"])
    await _simulate_dispatch(db, run["id"], gate["id"])

    resp = await client.post(f"/api/task-runs/{run['id']}/answer",
                              json={"decision": "reject", "note": "Not ready"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"

    cursor = await db.execute(
        "SELECT status, error_message FROM task_runs WHERE id = ?", (run["id"],)
    )
    row = await cursor.fetchone()
    assert row["status"] == "failed"
    assert "Not ready" in row["error_message"]

    cursor = await db.execute(
        "SELECT COUNT(*) FROM task_runs WHERE task_id = ?", (downstream["id"],)
    )
    assert (await cursor.fetchone())[0] == 0


async def test_answer_stores_note_as_xcom_for_downstream(client, db):
    """The human's decision/note is written to output + xcom, reusable as upstream context."""
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")

    run = await _trigger_task(client, gate["id"])
    await _simulate_dispatch(db, run["id"], gate["id"])

    resp = await client.post(f"/api/task-runs/{run['id']}/answer",
                              json={"decision": "approve", "note": "Looks good"})
    assert resp.status_code == 200

    cursor = await db.execute(
        "SELECT value FROM task_xcom WHERE task_run_id = ? AND key = 'return_value'", (run["id"],)
    )
    xcom = await cursor.fetchone()
    assert xcom is not None
    assert "Looks good" in xcom["value"]


async def test_answer_invalid_decision_rejected(client, db):
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")
    run = await _trigger_task(client, gate["id"])
    await _simulate_dispatch(db, run["id"], gate["id"])

    resp = await client.post(f"/api/task-runs/{run['id']}/answer", json={"decision": "maybe"})
    assert resp.status_code == 400


async def test_answer_run_with_no_pending_question_404s(client, db):
    """A run that isn't an awaiting-input approval gate can't be answered."""
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    resp = await client.post(f"/api/task-runs/{run['id']}/answer", json={"decision": "approve"})
    assert resp.status_code == 404


async def test_answer_already_answered_run_404s(client, db):
    """Answering twice fails the second time — no pending question is left."""
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")
    run = await _trigger_task(client, gate["id"])
    await _simulate_dispatch(db, run["id"], gate["id"])

    resp1 = await client.post(f"/api/task-runs/{run['id']}/answer", json={"decision": "approve"})
    assert resp1.status_code == 200

    resp2 = await client.post(f"/api/task-runs/{run['id']}/answer", json={"decision": "approve"})
    assert resp2.status_code == 404


# ── Question lookup ──────────────────────────────────────────────────────────

async def test_get_run_question(client, db):
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")
    run = await _trigger_task(client, gate["id"])
    await _simulate_dispatch(db, run["id"], gate["id"], "Ship it?")

    resp = await client.get(f"/api/task-runs/{run['id']}/question")
    assert resp.status_code == 200
    body = resp.json()
    assert body["question"]["question"] == "Ship it?"
    assert body["question"]["status"] == "pending"


async def test_get_run_question_none(client):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    resp = await client.get(f"/api/task-runs/{run['id']}/question")
    assert resp.status_code == 200
    assert resp.json()["question"] is None


# ── DAG / task views surface pending state ──────────────────────────────────

async def test_dag_marks_waiting_input(client, db):
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")
    run = await _trigger_task(client, gate["id"])
    await _simulate_dispatch(db, run["id"], gate["id"])

    resp = await client.get("/api/tasks/dag")
    node = next(n for n in resp.json()["nodes"] if n["id"] == gate["id"])
    assert node["waiting_input"] is True
    assert node["task_type"] == "approval"


async def test_get_task_includes_pending_question(client, db):
    flow = await _create_flow(client)
    gate = await _create_task(client, title="Gate", flow_id=flow["id"], task_type="approval")
    run = await _trigger_task(client, gate["id"])
    await _simulate_dispatch(db, run["id"], gate["id"], "Approve budget?")

    resp = await client.get(f"/api/tasks/{gate['id']}")
    body = resp.json()
    assert body["pending_question"]["question"] == "Approve budget?"
