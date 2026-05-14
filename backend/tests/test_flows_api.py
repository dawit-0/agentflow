import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_flow(client, name="Test Flow", **kwargs):
    payload = {"name": name, **kwargs}
    resp = await client.post("/api/flows", json=payload)
    assert resp.status_code == 200
    return resp.json()


# ── Tests ────────────────────────────────────────────────────────────────────

async def test_create_flow(client, db):
    data = await _create_flow(client, name="My Flow", description="A test flow")
    assert data["name"] == "My Flow"
    assert data["description"] == "A test flow"
    assert data["archived"] == 0
    assert data["id"]

    # Verify row exists in DB
    cursor = await db.execute("SELECT * FROM flows WHERE id = ?", (data["id"],))
    row = await cursor.fetchone()
    assert row is not None
    assert row["name"] == "My Flow"
    assert row["description"] == "A test flow"
    assert row["archived"] == 0


async def test_list_flows(client):
    await _create_flow(client, name="Flow A")
    await _create_flow(client, name="Flow B")
    resp = await client.get("/api/flows")
    assert resp.status_code == 200
    flows = resp.json()
    assert len(flows) == 2


async def test_list_flows_excludes_archived(client):
    flow = await _create_flow(client, name="Archived Flow")
    await client.delete(f"/api/flows/{flow['id']}")
    resp = await client.get("/api/flows")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


async def test_get_flow(client):
    flow = await _create_flow(client)
    resp = await client.get(f"/api/flows/{flow['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == flow["id"]


async def test_update_flow(client):
    flow = await _create_flow(client, name="Original")
    resp = await client.patch(f"/api/flows/{flow['id']}", json={"name": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"


async def test_archive_flow(client, db):
    flow = await _create_flow(client)
    resp = await client.delete(f"/api/flows/{flow['id']}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify soft delete — row still exists but archived=1
    cursor = await db.execute("SELECT archived FROM flows WHERE id = ?", (flow["id"],))
    row = await cursor.fetchone()
    assert row is not None
    assert row["archived"] == 1


async def test_archive_flow_cancels_active_runs(client, db):
    """Archiving a flow should cancel any queued/running task runs."""
    flow = await _create_flow(client)
    # Create a task and trigger the flow to produce a queued run
    await client.post("/api/tasks", json={
        "title": "Task A",
        "prompt": "do something",
        "flow_id": flow["id"],
    })
    await client.post(f"/api/flows/{flow['id']}/trigger")

    # Verify there is a queued run
    cursor = await db.execute(
        """SELECT COUNT(*) FROM task_runs tr JOIN tasks t ON tr.task_id = t.id
           WHERE t.flow_id = ? AND tr.status = 'queued'""",
        (flow["id"],),
    )
    assert (await cursor.fetchone())[0] == 1

    # Remember the task run IDs before archiving
    cursor = await db.execute("SELECT id FROM task_runs")
    run_ids_before = [row["id"] for row in await cursor.fetchall()]
    assert len(run_ids_before) == 1

    # Archive the flow — runs get cancelled then deleted along with tasks
    resp = await client.delete(f"/api/flows/{flow['id']}")
    assert resp.status_code == 200

    # Task runs should be fully cleaned up
    cursor = await db.execute("SELECT COUNT(*) FROM task_runs")
    assert (await cursor.fetchone())[0] == 0

    # Tasks should also be deleted
    cursor = await db.execute("SELECT COUNT(*) FROM tasks")
    assert (await cursor.fetchone())[0] == 0


async def test_archive_flow_deletes_tasks(client, db):
    """Archiving a flow should delete its tasks."""
    flow = await _create_flow(client)
    await client.post("/api/tasks", json={
        "title": "Task A",
        "prompt": "do something",
        "flow_id": flow["id"],
    })
    await client.post("/api/tasks", json={
        "title": "Task B",
        "prompt": "do something else",
        "flow_id": flow["id"],
    })

    # Verify tasks exist
    cursor = await db.execute(
        "SELECT COUNT(*) FROM tasks WHERE flow_id = ?", (flow["id"],),
    )
    assert (await cursor.fetchone())[0] == 2

    # Archive the flow
    await client.delete(f"/api/flows/{flow['id']}")

    # Tasks should be deleted
    cursor = await db.execute(
        "SELECT COUNT(*) FROM tasks WHERE flow_id = ?", (flow["id"],),
    )
    assert (await cursor.fetchone())[0] == 0


async def test_archive_flow_clears_agent_default_flow(client, db):
    """Archiving a flow should clear agent default_flow_id references."""
    flow = await _create_flow(client)
    # Create an agent pointing at this flow
    resp = await client.post("/api/agents", json={
        "name": "Test Agent",
        "default_flow_id": flow["id"],
    })
    agent = resp.json()

    # Archive the flow
    await client.delete(f"/api/flows/{flow['id']}")

    # Agent's default_flow_id should be cleared
    cursor = await db.execute(
        "SELECT default_flow_id FROM agents WHERE id = ?", (agent["id"],),
    )
    row = await cursor.fetchone()
    assert row["default_flow_id"] is None


async def test_archive_flow_removes_task_dependencies(client, db):
    """Archiving a flow should clean up task_dependencies rows."""
    flow = await _create_flow(client)
    resp_a = await client.post("/api/tasks", json={
        "title": "Task A",
        "prompt": "do A",
        "flow_id": flow["id"],
    })
    task_a = resp_a.json()
    resp_b = await client.post("/api/tasks", json={
        "title": "Task B",
        "prompt": "do B",
        "flow_id": flow["id"],
        "depends_on": [task_a["id"]],
    })
    task_b = resp_b.json()

    # Verify dependency exists
    cursor = await db.execute("SELECT COUNT(*) FROM task_dependencies")
    assert (await cursor.fetchone())[0] == 1

    # Archive the flow
    await client.delete(f"/api/flows/{flow['id']}")

    # Dependencies should be cleaned up
    cursor = await db.execute("SELECT COUNT(*) FROM task_dependencies")
    assert (await cursor.fetchone())[0] == 0


async def test_create_flow_with_schedule(client):
    data = await _create_flow(client, name="Scheduled", schedule="0 9 * * *")
    assert data["schedule"] == "0 9 * * *"
    assert data["next_run_at"] is not None


async def test_last_run_at_reflects_task_runs(client, db):
    """last_run_at should be derived from task_runs, not just scheduler ticks."""
    flow = await _create_flow(client, name="Manual Flow")

    # Initially no runs — last_run_at should be null.
    resp = await client.get(f"/api/flows/{flow['id']}")
    assert resp.json()["last_run_at"] is None

    # Manually trigger the flow (no schedule involved).
    await client.post("/api/tasks", json={
        "title": "Task A",
        "prompt": "do something",
        "flow_id": flow["id"],
    })
    await client.post(f"/api/flows/{flow['id']}/trigger")

    # Detail and list endpoints should both now report a last_run_at.
    detail = (await client.get(f"/api/flows/{flow['id']}")).json()
    assert detail["last_run_at"] is not None

    listed = (await client.get("/api/flows")).json()
    target = next(f for f in listed if f["id"] == flow["id"])
    assert target["last_run_at"] is not None


async def test_trigger_flow(client, db):
    """Triggering a flow should queue runs for its root tasks."""
    flow = await _create_flow(client)
    # Create two root tasks in this flow
    for title in ("Root A", "Root B"):
        await client.post("/api/tasks", json={
            "title": title,
            "prompt": "do something",
            "flow_id": flow["id"],
        })

    resp = await client.post(f"/api/flows/{flow['id']}/trigger")
    assert resp.status_code == 200
    body = resp.json()
    assert body["triggered"] == 2
    assert len(body["runs"]) == 2

    # Verify task_runs rows created in DB
    cursor = await db.execute(
        "SELECT COUNT(*) FROM task_runs tr JOIN tasks t ON tr.task_id = t.id WHERE t.flow_id = ?",
        (flow["id"],),
    )
    assert (await cursor.fetchone())[0] == 2
