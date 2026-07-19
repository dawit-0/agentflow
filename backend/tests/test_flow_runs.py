"""Flow runs: first-class DAG-run semantics.

Every task_run belongs to a flow_run; dependency readiness, data passing,
cascade cancel, and completion detection are scoped to that flow_run.
"""

import os
import sqlite3
import tempfile
from unittest.mock import patch

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


async def _trigger_task(client, task_id):
    resp = await client.post(f"/api/tasks/{task_id}/trigger")
    assert resp.status_code == 200
    return resp.json()


async def _set_run_status(db, run_id, status, cost=0.0):
    await db.execute(
        "UPDATE task_runs SET status = ?, finished_at = datetime('now'), cost_usd = ? WHERE id = ?",
        (status, cost, run_id),
    )
    await db.commit()


async def _get_flow_run(db, flow_run_id):
    cursor = await db.execute("SELECT * FROM flow_runs WHERE id = ?", (flow_run_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _get_run(db, run_id):
    cursor = await db.execute("SELECT * FROM task_runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _runs_in_flow_run(db, flow_run_id):
    cursor = await db.execute(
        "SELECT * FROM task_runs WHERE flow_run_id = ? ORDER BY started_at", (flow_run_id,)
    )
    return [dict(r) for r in await cursor.fetchall()]


# ── Schema & migration ───────────────────────────────────────────────────────

async def test_init_db_creates_flow_runs_schema():
    """init_db creates flow_runs and the new columns, and is idempotent."""
    import database

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "fresh.db")
        with patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await database.init_db()  # idempotent

        conn = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert "flow_runs" in tables

            fr_cols = {r[1] for r in conn.execute("PRAGMA table_info(flow_runs)")}
            assert {"id", "flow_id", "run_number", "trigger", "partial",
                    "status", "started_at", "finished_at", "total_cost_usd"} <= fr_cols

            tr_cols = {r[1] for r in conn.execute("PRAGMA table_info(task_runs)")}
            assert "flow_run_id" in tr_cols
            assert "not_before" in tr_cols

            flow_cols = {r[1] for r in conn.execute("PRAGMA table_info(flows)")}
            assert "max_active_runs" in flow_cols
        finally:
            conn.close()


async def test_init_db_migrates_existing_db():
    """A pre-flow_runs database gets the new columns on init_db."""
    import database

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "old.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE flows (id TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE task_runs (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                run_number INTEGER NOT NULL, status TEXT DEFAULT 'queued',
                started_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO flows VALUES ('f1', 'Old Flow');
            INSERT INTO task_runs (id, task_id, run_number, status)
            VALUES ('r1', 't1', 1, 'success');
        """)
        conn.commit()
        conn.close()

        with patch.object(database, "DB_PATH", db_path):
            await database.init_db()

        conn = sqlite3.connect(db_path)
        try:
            tr_cols = {r[1] for r in conn.execute("PRAGMA table_info(task_runs)")}
            assert "flow_run_id" in tr_cols
            assert "not_before" in tr_cols
            flow_cols = {r[1] for r in conn.execute("PRAGMA table_info(flows)")}
            assert "max_active_runs" in flow_cols
            # legacy row untouched
            row = conn.execute("SELECT flow_run_id FROM task_runs WHERE id='r1'").fetchone()
            assert row[0] is None
        finally:
            conn.close()


# ── Flow trigger creates flow runs ───────────────────────────────────────────

async def test_trigger_flow_creates_flow_run(client, db):
    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])

    body = await _trigger_flow(client, flow["id"])
    assert "flow_run" in body
    fr = body["flow_run"]
    assert fr["flow_id"] == flow["id"]
    assert fr["run_number"] == 1
    assert fr["status"] == "running"
    assert fr["trigger"] == "manual"
    assert not fr["partial"]

    # Root task run is attached to the flow run
    runs = await _runs_in_flow_run(db, fr["id"])
    assert len(runs) == 1
    assert runs[0]["task_id"] == root["id"]
    assert runs[0]["status"] == "queued"


async def test_flow_run_numbers_increment(client, db):
    flow = await _create_flow(client)
    await _create_task(client, title="Root", flow_id=flow["id"])

    fr1 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    fr2 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    assert fr1["run_number"] == 1
    assert fr2["run_number"] == 2


async def test_trigger_flow_respects_max_active_runs(client, db):
    """Second trigger while a run is active queues the flow_run (default max_active_runs=1)."""
    flow = await _create_flow(client)
    await _create_task(client, title="Root", flow_id=flow["id"])

    body1 = await _trigger_flow(client, flow["id"])
    body2 = await _trigger_flow(client, flow["id"])

    assert body1["flow_run"]["status"] == "running"
    assert body2["flow_run"]["status"] == "queued"
    assert body2["triggered"] == 0
    # queued flow_run has no task_runs yet
    assert await _runs_in_flow_run(db, body2["flow_run"]["id"]) == []


async def test_trigger_flow_overlap_allowed_when_max_active_runs_raised(client, db):
    flow = await _create_flow(client)
    await _create_task(client, title="Root", flow_id=flow["id"])
    resp = await client.patch(f"/api/flows/{flow['id']}", json={"max_active_runs": 2})
    assert resp.status_code == 200

    body1 = await _trigger_flow(client, flow["id"])
    body2 = await _trigger_flow(client, flow["id"])
    assert body1["flow_run"]["status"] == "running"
    assert body2["flow_run"]["status"] == "running"


# ── Single-task triggers create partial flow runs ────────────────────────────

async def test_trigger_task_creates_partial_flow_run(client, db):
    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    assert run["flow_run_id"] is not None
    fr = await _get_flow_run(db, run["flow_run_id"])
    assert fr["partial"] == 1
    assert fr["status"] == "running"


async def test_create_task_with_trigger_creates_partial_flow_run(client, db):
    task = await _create_task(client, trigger=True)
    cursor = await db.execute(
        "SELECT * FROM task_runs WHERE task_id = ?", (task["id"],)
    )
    run = dict(await cursor.fetchone())
    assert run["flow_run_id"] is not None
    fr = await _get_flow_run(db, run["flow_run_id"])
    assert fr["partial"] == 1


# ── Scheduler creates flow runs ──────────────────────────────────────────────

async def test_flow_schedule_creates_flow_run(client, db):
    flow = await _create_flow(client, schedule="0 * * * *")
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    await db.execute(
        "UPDATE flows SET next_run_at = '2020-01-01T00:00:00Z' WHERE id = ?",
        (flow["id"],),
    )
    await db.commit()

    orch = _orch()
    await orch._check_flow_schedules()

    cursor = await db.execute(
        "SELECT * FROM flow_runs WHERE flow_id = ?", (flow["id"],)
    )
    frs = [dict(r) for r in await cursor.fetchall()]
    assert len(frs) == 1
    assert frs[0]["trigger"] == "schedule"
    assert frs[0]["status"] == "running"
    runs = await _runs_in_flow_run(db, frs[0]["id"])
    assert [r["task_id"] for r in runs] == [root["id"]]


async def test_task_schedule_creates_partial_flow_run(client, db):
    task = await _create_task(client, schedule="0 * * * *")
    await db.execute(
        "UPDATE tasks SET next_run_at = '2020-01-01T00:00:00Z' WHERE id = ?",
        (task["id"],),
    )
    await db.commit()

    orch = _orch()
    await orch._check_task_schedules()

    cursor = await db.execute(
        "SELECT * FROM task_runs WHERE task_id = ?", (task["id"],)
    )
    run = dict(await cursor.fetchone())
    assert run["flow_run_id"] is not None
    fr = await _get_flow_run(db, run["flow_run_id"])
    assert fr["partial"] == 1
    assert fr["trigger"] == "schedule"


# ── Cascade inherits the flow run ────────────────────────────────────────────

async def test_cascade_inherits_flow_run_id(client, db):
    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[root["id"]])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    root_run = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, root_run["id"], "success")

    orch = _orch()
    await orch._cascade_trigger_downstream(db, root["id"], fr["id"])
    await db.commit()

    runs = await _runs_in_flow_run(db, fr["id"])
    down_runs = [r for r in runs if r["task_id"] == down["id"]]
    assert len(down_runs) == 1
    assert down_runs[0]["trigger"] == "dependency"
    assert down_runs[0]["status"] == "queued"


# ── Readiness is scoped to the flow run ──────────────────────────────────────

async def test_ready_scoped_to_flow_run(client, db):
    """R1's downstream is dispatchable on R1's root success even while R2's
    root is still queued (the old global latest-run check would block it)."""
    from db import task_runs as db_task_runs

    flow = await _create_flow(client)
    await client.patch(f"/api/flows/{flow['id']}", json={"max_active_runs": 2})
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[root["id"]])

    fr1 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    r1_root = (await _runs_in_flow_run(db, fr1["id"]))[0]
    await _set_run_status(db, r1_root["id"], "success")

    orch = _orch()
    await orch._cascade_trigger_downstream(db, root["id"], fr1["id"])
    await db.commit()

    # Second flow run: its root run is queued — the global "latest run" of root
    fr2 = (await _trigger_flow(client, flow["id"]))["flow_run"]

    ready = await db_task_runs.get_queued_ready(db, 10)
    ready_pairs = {(r["task_id"], r["flow_run_id"]) for r in ready}
    assert (down["id"], fr1["id"]) in ready_pairs   # R1 downstream: dep met in R1
    assert (root["id"], fr2["id"]) in ready_pairs   # R2 root: no deps


async def test_downstream_not_ready_from_stale_upstream_success(client, db):
    """A downstream run in a full (non-partial) flow run must wait for its
    upstream *in that run* — success from a previous run doesn't count."""
    import uuid
    from db import task_runs as db_task_runs

    flow = await _create_flow(client)
    await client.patch(f"/api/flows/{flow['id']}", json={"max_active_runs": 2})
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[root["id"]])

    # R1: root succeeded (global latest success exists)
    fr1 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    r1_root = (await _runs_in_flow_run(db, fr1["id"]))[0]
    await _set_run_status(db, r1_root["id"], "success")

    # R2: contains ONLY a queued downstream run (root hasn't run in R2)
    fr2 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    down_run_id = str(uuid.uuid4())
    run_number = await db_task_runs.next_run_number(db, down["id"])
    await db_task_runs.insert(db, down_run_id, down["id"], run_number,
                              trigger="dependency", flow_run_id=fr2["id"])
    # remove R2's root run so the only R2 member is the downstream
    r2_runs = await _runs_in_flow_run(db, fr2["id"])
    for r in r2_runs:
        if r["task_id"] == root["id"]:
            await db.execute("DELETE FROM task_runs WHERE id = ?", (r["id"],))
    await db.commit()

    ready = await db_task_runs.get_queued_ready(db, 10)
    assert down_run_id not in {r["id"] for r in ready}


async def test_partial_run_falls_back_to_global_success(client, db):
    """Manually triggering a mid-graph task (partial run) uses the upstream's
    global latest success to satisfy the dependency."""
    from db import task_runs as db_task_runs

    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[root["id"]])

    root_run = await _trigger_task(client, root["id"])
    await _set_run_status(db, root_run["id"], "success")

    down_run = await _trigger_task(client, down["id"])  # partial flow run

    ready = await db_task_runs.get_queued_ready(db, 10)
    assert down_run["id"] in {r["id"] for r in ready}


async def test_not_before_defers_dispatch(client, db):
    from db import task_runs as db_task_runs

    task = await _create_task(client)
    run = await _trigger_task(client, task["id"])

    await db.execute(
        "UPDATE task_runs SET not_before = datetime('now', '+60 seconds') WHERE id = ?",
        (run["id"],),
    )
    await db.commit()
    ready = await db_task_runs.get_queued_ready(db, 10)
    assert run["id"] not in {r["id"] for r in ready}

    await db.execute(
        "UPDATE task_runs SET not_before = datetime('now', '-1 seconds') WHERE id = ?",
        (run["id"],),
    )
    await db.commit()
    ready = await db_task_runs.get_queued_ready(db, 10)
    assert run["id"] in {r["id"] for r in ready}


async def test_legacy_runs_still_dispatch(client, db):
    """Runs with flow_run_id NULL (pre-migration) use the old global semantics."""
    import uuid
    from db import task_runs as db_task_runs

    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[root["id"]])

    # Legacy-style rows: no flow_run_id
    root_run_id, down_run_id = str(uuid.uuid4()), str(uuid.uuid4())
    await db_task_runs.insert(db, root_run_id, root["id"], 1)
    await db_task_runs.insert(db, down_run_id, down["id"], 1)
    await _set_run_status(db, root_run_id, "success")

    ready = await db_task_runs.get_queued_ready(db, 10)
    assert down_run_id in {r["id"] for r in ready}


# ── Data passing is scoped to the flow run ───────────────────────────────────

async def test_prompt_context_scoped_to_flow_run(client, db):
    """Downstream in R1 sees R1's upstream output even after R2 produced newer output."""
    from db import task_run_output as db_output

    flow = await _create_flow(client)
    await client.patch(f"/api/flows/{flow['id']}", json={"max_active_runs": 2})
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[root["id"]])

    fr1 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    r1_root = (await _runs_in_flow_run(db, fr1["id"]))[0]
    await db_output.insert(r1_root["id"], 1, "result", "OUTPUT-FROM-R1")
    await _set_run_status(db, r1_root["id"], "success")

    fr2 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    r2_root = (await _runs_in_flow_run(db, fr2["id"]))[0]
    await db_output.insert(r2_root["id"], 1, "result", "OUTPUT-FROM-R2")
    await _set_run_status(db, r2_root["id"], "success")

    orch = _orch()
    prompt = await orch._build_prompt_with_context(db, down["id"], "base", fr1["id"])
    assert "OUTPUT-FROM-R1" in prompt
    assert "OUTPUT-FROM-R2" not in prompt


async def test_prompt_context_partial_fallback(client, db):
    """A partial run's downstream falls back to the upstream's global latest output."""
    from db import task_run_output as db_output

    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[root["id"]])

    root_run = await _trigger_task(client, root["id"])
    await db_output.insert(root_run["id"], 1, "result", "GLOBAL-OUTPUT")
    await _set_run_status(db, root_run["id"], "success")

    down_run = await _trigger_task(client, down["id"])  # partial

    orch = _orch()
    prompt = await orch._build_prompt_with_context(
        db, down["id"], "base", down_run["flow_run_id"])
    assert "GLOBAL-OUTPUT" in prompt


# ── Retries: durable not_before, flow_run inheritance ────────────────────────

async def test_auto_retry_inserts_not_before_run(client, db):
    task = await _create_task(client, max_retries=2, retry_delay_seconds=30)
    run = await _trigger_task(client, task["id"])
    await _set_run_status(db, run["id"], "failed")

    orch = _orch()
    retried = await orch._maybe_auto_retry(db, run["id"], task["id"])
    await db.commit()
    assert retried is True

    cursor = await db.execute(
        """SELECT *, (not_before > datetime('now')) AS deferred
           FROM task_runs WHERE task_id = ? AND trigger = 'retry'""",
        (task["id"],),
    )
    retry_run = dict(await cursor.fetchone())
    assert retry_run["status"] == "queued"
    assert retry_run["attempt_number"] == 2
    assert retry_run["retry_of_run_id"] == run["id"]
    assert retry_run["flow_run_id"] == run["flow_run_id"]
    assert retry_run["deferred"] == 1  # not_before is in the future


async def test_auto_retry_exhausted(client, db):
    task = await _create_task(client, max_retries=1)
    run = await _trigger_task(client, task["id"])
    await db.execute(
        "UPDATE task_runs SET status='failed', attempt_number=1 WHERE id = ?",
        (run["id"],),
    )
    await db.commit()

    orch = _orch()
    retried = await orch._maybe_auto_retry(db, run["id"], task["id"])
    assert retried is False


async def test_manual_retry_inherits_and_reopens_flow_run(client, db):
    flow = await _create_flow(client)
    task = await _create_task(client, title="Root", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    run = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, run["id"], "failed")

    orch = _orch()
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()
    assert (await _get_flow_run(db, fr["id"]))["status"] == "failed"

    # orchestrator.get_db is patched to the shared test DB by the client fixture
    await orch.retry_task_run(task["id"])

    runs = await _runs_in_flow_run(db, fr["id"])
    assert len(runs) == 2  # original + retry in the same flow run
    assert (await _get_flow_run(db, fr["id"]))["status"] == "running"


# ── Finalization ─────────────────────────────────────────────────────────────

async def test_finalize_success(client, db):
    flow = await _create_flow(client)
    a = await _create_task(client, title="A", flow_id=flow["id"])
    b = await _create_task(client, title="B", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    for r in await _runs_in_flow_run(db, fr["id"]):
        await _set_run_status(db, r["id"], "success", cost=0.5)

    orch = _orch()
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()

    fr_row = await _get_flow_run(db, fr["id"])
    assert fr_row["status"] == "success"
    assert fr_row["finished_at"] is not None
    assert fr_row["total_cost_usd"] == pytest.approx(1.0)


async def test_finalize_failed(client, db):
    flow = await _create_flow(client)
    await _create_task(client, title="A", flow_id=flow["id"])
    await _create_task(client, title="B", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    runs = await _runs_in_flow_run(db, fr["id"])
    await _set_run_status(db, runs[0]["id"], "success")
    await _set_run_status(db, runs[1]["id"], "failed")

    orch = _orch()
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()
    assert (await _get_flow_run(db, fr["id"]))["status"] == "failed"


async def test_finalize_uses_latest_attempt_per_task(client, db):
    """A task that failed then succeeded on retry counts as success."""
    import uuid
    from db import task_runs as db_task_runs

    flow = await _create_flow(client)
    task = await _create_task(client, title="A", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    run1 = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, run1["id"], "failed")

    retry_id = str(uuid.uuid4())
    rn = await db_task_runs.next_run_number(db, task["id"])
    await db_task_runs.insert(db, retry_id, task["id"], rn, trigger="retry",
                              attempt_number=2, retry_of_run_id=run1["id"],
                              flow_run_id=fr["id"])
    await _set_run_status(db, retry_id, "success")

    orch = _orch()
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()
    assert (await _get_flow_run(db, fr["id"]))["status"] == "success"


async def test_finalize_waits_for_active_runs(client, db):
    flow = await _create_flow(client)
    await _create_task(client, title="A", flow_id=flow["id"])
    await _create_task(client, title="B", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    runs = await _runs_in_flow_run(db, fr["id"])
    await _set_run_status(db, runs[0]["id"], "success")
    # runs[1] still queued

    orch = _orch()
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()
    assert (await _get_flow_run(db, fr["id"]))["status"] == "running"


async def test_finalize_waits_for_pending_retry(client, db):
    """A queued retry with a future not_before keeps the flow run open."""
    flow = await _create_flow(client)
    task = await _create_task(client, title="A", flow_id=flow["id"],
                              max_retries=2, retry_delay_seconds=60)

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    run = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, run["id"], "failed")

    orch = _orch()
    assert await orch._maybe_auto_retry(db, run["id"], task["id"]) is True
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()
    assert (await _get_flow_run(db, fr["id"]))["status"] == "running"


async def test_finalize_emits_notification(client, db):
    from db import settings as db_settings

    await db_settings.put(db, "notify_on_flow_completion", "1")
    await db.commit()

    flow = await _create_flow(client, name="Notified Flow")
    await _create_task(client, title="A", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    run = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, run["id"], "success")

    orch = _orch()
    await orch._finalize_flow_run(db, fr["id"])
    # Finalizing again is a no-op (already terminal) — no duplicate notification
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()

    cursor = await db.execute(
        "SELECT COUNT(*) FROM notifications WHERE flow_id = ?", (flow["id"],)
    )
    assert (await cursor.fetchone())[0] == 1


# ── Queued flow run promotion ────────────────────────────────────────────────

async def test_promote_queued_flow_run(client, db):
    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])

    fr1 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    fr2 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    assert fr2["status"] == "queued"

    # Finish and finalize R1
    run = (await _runs_in_flow_run(db, fr1["id"]))[0]
    await _set_run_status(db, run["id"], "success")
    orch = _orch()
    await orch._finalize_flow_run(db, fr1["id"])
    await db.commit()

    await orch._promote_queued_flow_runs(db)
    await db.commit()

    fr2_row = await _get_flow_run(db, fr2["id"])
    assert fr2_row["status"] == "running"
    runs = await _runs_in_flow_run(db, fr2["id"])
    assert [r["task_id"] for r in runs] == [root["id"]]


# ── Cascade cancel is scoped ─────────────────────────────────────────────────

async def test_cascade_cancel_scoped_to_flow_run(client, db):
    import uuid
    from db import task_runs as db_task_runs

    flow = await _create_flow(client)
    await client.patch(f"/api/flows/{flow['id']}", json={"max_active_runs": 2})
    root = await _create_task(client, title="Root", flow_id=flow["id"])
    down = await _create_task(client, title="Down", flow_id=flow["id"],
                              depends_on=[root["id"]])

    fr1 = (await _trigger_flow(client, flow["id"]))["flow_run"]
    fr2 = (await _trigger_flow(client, flow["id"]))["flow_run"]

    # Queue a downstream run in each flow run
    d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
    rn = await db_task_runs.next_run_number(db, down["id"])
    await db_task_runs.insert(db, d1, down["id"], rn, trigger="dependency",
                              flow_run_id=fr1["id"])
    await db_task_runs.insert(db, d2, down["id"], rn + 1, trigger="dependency",
                              flow_run_id=fr2["id"])
    await db.commit()

    orch = _orch()
    await orch._cascade_cancel_downstream(db, root["id"], fr1["id"])
    await db.commit()

    assert (await _get_run(db, d1))["status"] == "cancelled"
    assert (await _get_run(db, d2))["status"] == "queued"


# ── API endpoints ────────────────────────────────────────────────────────────

async def test_list_flow_runs_endpoint(client, db):
    flow = await _create_flow(client)
    await _create_task(client, title="A", flow_id=flow["id"])
    await _create_task(client, title="B", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    runs = await _runs_in_flow_run(db, fr["id"])
    await _set_run_status(db, runs[0]["id"], "success")

    resp = await client.get(f"/api/flows/{flow['id']}/runs")
    assert resp.status_code == 200
    listed = resp.json()
    assert len(listed) == 1
    assert listed[0]["id"] == fr["id"]
    assert listed[0]["total_tasks"] == 2
    assert listed[0]["succeeded_tasks"] == 1


async def test_get_flow_run_detail(client, db):
    flow = await _create_flow(client)
    root = await _create_task(client, title="Root", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    resp = await client.get(f"/api/flow-runs/{fr['id']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == fr["id"]
    assert len(detail["task_runs"]) == 1
    assert detail["task_runs"][0]["task_id"] == root["id"]


async def test_get_flow_run_not_found(client):
    resp = await client.get("/api/flow-runs/nonexistent")
    assert resp.status_code == 404


async def test_cancel_flow_run_endpoint(client, db):
    flow = await _create_flow(client)
    await _create_task(client, title="A", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    resp = await client.post(f"/api/flow-runs/{fr['id']}/cancel")
    assert resp.status_code == 200

    assert (await _get_flow_run(db, fr["id"]))["status"] == "cancelled"
    for r in await _runs_in_flow_run(db, fr["id"]):
        assert r["status"] == "cancelled"


async def test_flow_retry_creates_new_flow_run(client, db):
    flow = await _create_flow(client)
    await _create_task(client, title="Root", flow_id=flow["id"])

    fr1 = (await _trigger_flow(client, flow["id"]))["flow_run"]

    resp = await client.post(f"/api/flows/{flow['id']}/retry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["flow_run"]["id"] != fr1["id"]
    assert body["flow_run"]["trigger"] == "retry"
    # the superseded active flow run is cancelled
    assert (await _get_flow_run(db, fr1["id"]))["status"] == "cancelled"


async def test_flow_resume_reopens_flow_run(client, db):
    flow = await _create_flow(client)
    task = await _create_task(client, title="Root", flow_id=flow["id"])

    fr = (await _trigger_flow(client, flow["id"]))["flow_run"]
    run = (await _runs_in_flow_run(db, fr["id"]))[0]
    await _set_run_status(db, run["id"], "failed")

    orch = _orch()
    await orch._finalize_flow_run(db, fr["id"])
    await db.commit()
    assert (await _get_flow_run(db, fr["id"]))["status"] == "failed"

    resp = await client.post(f"/api/flows/{flow['id']}/resume")
    assert resp.status_code == 200
    assert resp.json()["retried"] == 1

    # retry run joined the original flow run, which is running again
    runs = await _runs_in_flow_run(db, fr["id"])
    assert len(runs) == 2
    assert (await _get_flow_run(db, fr["id"]))["status"] == "running"


async def test_archive_flow_deletes_flow_runs(client, db):
    flow = await _create_flow(client)
    await _create_task(client, title="Root", flow_id=flow["id"])
    await _trigger_flow(client, flow["id"])

    resp = await client.delete(f"/api/flows/{flow['id']}")
    assert resp.status_code == 200

    cursor = await db.execute(
        "SELECT COUNT(*) FROM flow_runs WHERE flow_id = ?", (flow["id"],)
    )
    assert (await cursor.fetchone())[0] == 0
