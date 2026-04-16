"""Tests for /api/analytics/* aggregation endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _make_flow(db, name: str = "F") -> str:
    fid = str(uuid.uuid4())
    await db.execute("INSERT INTO flows (id, name) VALUES (?, ?)", (fid, name))
    await db.commit()
    return fid


async def _make_task(db, flow_id: str, title: str = "T") -> str:
    tid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO tasks (id, title, prompt, flow_id) VALUES (?, ?, ?, ?)",
        (tid, title, "p", flow_id),
    )
    await db.commit()
    return tid


async def _insert_run(
    db,
    task_id: str,
    *,
    status: str = "success",
    duration_ms: int = 1000,
    cost_usd: float = 0.01,
    started_at: datetime | None = None,
    error_message: str | None = None,
) -> str:
    rid = str(uuid.uuid4())
    cursor = await db.execute(
        "SELECT COALESCE(MAX(run_number), 0) + 1 FROM task_runs WHERE task_id = ?",
        (task_id,),
    )
    run_number = (await cursor.fetchone())[0]
    started = (started_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
    finished = (started_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")

    await db.execute(
        """INSERT INTO task_runs
             (id, task_id, run_number, status, duration_ms, cost_usd,
              started_at, finished_at, error_message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (rid, task_id, run_number, status, duration_ms, cost_usd,
         started, finished, error_message),
    )
    await db.commit()
    return rid


# ── Tests ────────────────────────────────────────────────────────────────────

async def test_summary_empty_db_returns_zeros(client):
    resp = await client.get("/api/analytics/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_runs"] == 0
    assert data["success_count"] == 0
    assert data["failed_count"] == 0
    assert data["success_rate"] == 0.0
    assert data["total_cost_usd"] == 0.0
    assert data["p50_duration_ms"] == 0
    assert data["p95_duration_ms"] == 0


async def test_summary_counts_and_cost(client, db):
    flow = await _make_flow(db)
    task = await _make_task(db, flow)
    for _ in range(3):
        await _insert_run(db, task, status="success", duration_ms=1000, cost_usd=0.05)
    for _ in range(2):
        await _insert_run(db, task, status="failed", duration_ms=500, cost_usd=0.01)

    resp = await client.get("/api/analytics/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_runs"] == 5
    assert data["success_count"] == 3
    assert data["failed_count"] == 2
    assert data["success_rate"] == pytest.approx(0.6)
    assert data["total_cost_usd"] == pytest.approx(0.17, abs=1e-6)


async def test_summary_respects_since(client, db):
    flow = await _make_flow(db)
    task = await _make_task(db, flow)
    old = datetime.now(timezone.utc) - timedelta(days=40)
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    await _insert_run(db, task, status="success", started_at=old)
    await _insert_run(db, task, status="success", started_at=recent)

    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    resp = await client.get("/api/analytics/summary", params={"since": since})
    assert resp.status_code == 200
    assert resp.json()["total_runs"] == 1


async def test_runs_by_day_groups_by_date(client, db):
    flow = await _make_flow(db)
    task = await _make_task(db, flow)
    d1 = datetime.now(timezone.utc) - timedelta(days=2)
    d2 = datetime.now(timezone.utc) - timedelta(days=1)
    await _insert_run(db, task, status="success", started_at=d1, cost_usd=0.1)
    await _insert_run(db, task, status="failed", started_at=d1, cost_usd=0.05)
    await _insert_run(db, task, status="success", started_at=d2, cost_usd=0.2)

    resp = await client.get("/api/analytics/runs_by_day")
    assert resp.status_code == 200
    days = resp.json()
    assert len(days) == 2
    assert days[0]["date"] < days[1]["date"]
    day_one = days[0]
    assert day_one["total"] == 2
    assert day_one["success"] == 1
    assert day_one["failed"] == 1
    assert day_one["cost_usd"] == pytest.approx(0.15)


async def test_top_failing_tasks_ordered(client, db):
    flow = await _make_flow(db)
    t_most = await _make_task(db, flow, title="most-fails")
    t_mid = await _make_task(db, flow, title="mid-fails")
    t_none = await _make_task(db, flow, title="no-fails")
    for _ in range(3):
        await _insert_run(db, t_most, status="failed")
    for _ in range(1):
        await _insert_run(db, t_mid, status="failed")
    await _insert_run(db, t_none, status="success")

    resp = await client.get("/api/analytics/top_failures", params={"limit": 10})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["task_id"] == t_most
    assert rows[0]["failure_count"] == 3
    assert rows[1]["task_id"] == t_mid


async def test_duration_histogram_buckets(client, db):
    flow = await _make_flow(db)
    task = await _make_task(db, flow)
    # One run per bucket
    for ms in (5_000, 20_000, 45_000, 120_000, 600_000):
        await _insert_run(db, task, status="success", duration_ms=ms)

    resp = await client.get("/api/analytics/duration_histogram")
    assert resp.status_code == 200
    hist = {row["bucket"]: row["count"] for row in resp.json()}
    assert hist == {"<10s": 1, "10-30s": 1, "30-60s": 1, "1-5m": 1, ">5m": 1}


async def test_recent_failures_excludes_successes(client, db):
    flow = await _make_flow(db)
    task = await _make_task(db, flow)
    await _insert_run(db, task, status="success")
    await _insert_run(db, task, status="failed", error_message="boom")

    resp = await client.get("/api/analytics/recent_failures", params={"limit": 10})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["error_message"] == "boom"
    assert "task_title" in rows[0]


async def test_recent_failures_truncates_long_error(client, db):
    flow = await _make_flow(db)
    task = await _make_task(db, flow)
    long_err = "x" * 1000
    await _insert_run(db, task, status="failed", error_message=long_err)

    resp = await client.get("/api/analytics/recent_failures")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows[0]["error_message"]) <= 303  # 300 + "..."
    assert rows[0]["error_message"].endswith("...")
