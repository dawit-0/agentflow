import os

import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_task(client, title="Task"):
    resp = await client.post("/api/tasks", json={"title": title, "prompt": "do it"})
    assert resp.status_code == 200
    return resp.json()


async def _trigger_task(client, task_id):
    resp = await client.post(f"/api/tasks/{task_id}/trigger")
    assert resp.status_code == 200
    return resp.json()


# ── Tests ────────────────────────────────────────────────────────────────────

async def test_list_all_runs(client, db):
    t1 = await _create_task(client, title="T1")
    t2 = await _create_task(client, title="T2")
    await _trigger_task(client, t1["id"])
    await _trigger_task(client, t2["id"])

    resp = await client.get("/api/task-runs")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # Verify actual row count in DB
    cursor = await db.execute("SELECT COUNT(*) FROM task_runs")
    assert (await cursor.fetchone())[0] == 2


async def test_list_runs_filtered_by_task(client):
    t1 = await _create_task(client, title="T1")
    t2 = await _create_task(client, title="T2")
    await _trigger_task(client, t1["id"])
    await _trigger_task(client, t2["id"])

    resp = await client.get("/api/task-runs", params={"task_id": t1["id"]})
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["task_id"] == t1["id"]


async def test_get_run_by_id(client):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    resp = await client.get(f"/api/task-runs/{run['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == run["id"]
    assert resp.json()["task_id"] == task["id"]


async def test_get_run_output_empty(client):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    resp = await client.get(f"/api/task-runs/{run['id']}/output")
    assert resp.status_code == 200
    assert resp.json() == []

    # No output file should have been created on disk yet.
    output_path = os.path.join(os.environ["AGENTFLOW_OUTPUT_DIR"], f"{run['id']}.jsonl")
    assert not os.path.exists(output_path)
