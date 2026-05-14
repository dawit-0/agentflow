import json
import os

import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


def _write_output_lines(run_id: str, count: int) -> None:
    """Append ``count`` fake output records to the run's jsonl file."""
    path = os.path.join(os.environ["AGENTFLOW_OUTPUT_DIR"], f"{run_id}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        for seq in range(1, count + 1):
            f.write(json.dumps({
                "seq": seq,
                "type": "text",
                "content": f"line {seq}",
                "timestamp": "2026-05-14T00:00:00Z",
            }) + "\n")


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


async def test_get_run_output_tail(client):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])
    _write_output_lines(run["id"], 50)

    resp = await client.get(f"/api/task-runs/{run['id']}/output", params={"tail": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_seq"] == 50
    rows = body["rows"]
    assert len(rows) == 10
    assert rows[0]["seq"] == 41
    assert rows[-1]["seq"] == 50
    assert all(r["task_run_id"] == run["id"] for r in rows)


async def test_get_run_output_after_seq(client):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])
    _write_output_lines(run["id"], 5)

    resp = await client.get(f"/api/task-runs/{run['id']}/output", params={"after_seq": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_seq"] == 5
    assert [r["seq"] for r in body["rows"]] == [4, 5]


async def test_get_run_output_after_seq_no_new(client):
    """When the client is fully caught up, after_seq returns no rows."""
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])
    _write_output_lines(run["id"], 3)

    resp = await client.get(f"/api/task-runs/{run['id']}/output", params={"after_seq": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == []
    assert body["last_seq"] == 3


async def test_get_run_output_after_seq_and_tail_compose(client):
    """tail keeps only the last N of the after_seq-filtered rows."""
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])
    _write_output_lines(run["id"], 20)

    resp = await client.get(
        f"/api/task-runs/{run['id']}/output",
        params={"after_seq": 5, "tail": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [r["seq"] for r in body["rows"]] == [18, 19, 20]
    assert body["last_seq"] == 20


async def test_get_run_output_no_params_returns_full_list(client):
    """Back-compat: no params still returns a plain JSON array, not the paged shape."""
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])
    _write_output_lines(run["id"], 3)

    resp = await client.get(f"/api/task-runs/{run['id']}/output")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert [r["seq"] for r in body] == [1, 2, 3]
