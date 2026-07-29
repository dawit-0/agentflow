import os
import shutil
import sys
import tempfile
from unittest.mock import patch

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Isolate filesystem-backed task run output to a tmp dir for the test session.
_TEST_OUTPUT_DIR = tempfile.mkdtemp(prefix="agentflow-test-outputs-")
os.environ["AGENTFLOW_OUTPUT_DIR"] = _TEST_OUTPUT_DIR

# Shared in-memory DB URI so every get_db() call sees the same data
_TEST_DB_URI = "file:test_db?mode=memory&cache=shared"

# Keep one connection alive for the duration of the session so the
# shared in-memory database is not garbage-collected between calls.
from typing import Optional

_keeper_conn: Optional[aiosqlite.Connection] = None


async def _get_test_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(_TEST_DB_URI, uri=True)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def _init_test_db():
    """Create all tables in the shared in-memory DB."""
    db = await _get_test_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS flows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                schedule TEXT,
                schedule_enabled INTEGER DEFAULT 1,
                next_run_at TEXT,
                last_run_at TEXT,
                max_active_runs INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                archived INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS flow_runs (
                id TEXT PRIMARY KEY,
                flow_id TEXT NOT NULL REFERENCES flows(id),
                run_number INTEGER NOT NULL,
                trigger TEXT DEFAULT 'manual' CHECK(trigger IN ('manual','schedule','retry','resume')),
                partial INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running' CHECK(status IN ('queued','running','success','failed','cancelled')),
                created_at TEXT DEFAULT (datetime('now')),
                started_at TEXT,
                finished_at TEXT,
                total_cost_usd REAL DEFAULT 0,
                UNIQUE(flow_id, run_number)
            );
            CREATE INDEX IF NOT EXISTS idx_flow_runs_flow ON flow_runs(flow_id, run_number);
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                instructions TEXT DEFAULT '',
                context TEXT DEFAULT '[]',
                default_model TEXT DEFAULT 'claude-sonnet-4-20250514',
                default_permissions TEXT DEFAULT '{}',
                default_work_dir TEXT DEFAULT '',
                default_flow_id TEXT REFERENCES flows(id),
                default_sandbox TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT DEFAULT 'active' CHECK(status IN ('active','paused')),
                priority INTEGER DEFAULT 0,
                model TEXT DEFAULT 'claude-sonnet-4-20250514',
                work_dir TEXT DEFAULT '',
                flow_id TEXT REFERENCES flows(id),
                agent_id TEXT REFERENCES agents(id),
                permissions TEXT DEFAULT '{}',
                schedule TEXT,
                schedule_enabled INTEGER DEFAULT 1,
                next_run_at TEXT,
                last_run_at TEXT,
                max_retries INTEGER DEFAULT 0,
                retry_delay_seconds INTEGER DEFAULT 10,
                sandbox TEXT DEFAULT '',
                requires_approval INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS task_dependencies (
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                depends_on_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                pass_output INTEGER DEFAULT 1,
                max_output_chars INTEGER DEFAULT 4000,
                PRIMARY KEY (task_id, depends_on_task_id)
            );
            CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_deps_depends ON task_dependencies(depends_on_task_id);
            CREATE TABLE IF NOT EXISTS task_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id),
                run_number INTEGER NOT NULL,
                trigger TEXT DEFAULT 'manual' CHECK(trigger IN ('manual','schedule','dependency','retry')),
                status TEXT DEFAULT 'queued' CHECK(status IN ('queued','running','success','failed','cancelled')),
                pid INTEGER,
                exit_code INTEGER,
                cost_usd REAL DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                num_turns INTEGER DEFAULT 0,
                started_at TEXT DEFAULT (datetime('now')),
                finished_at TEXT,
                error_message TEXT,
                attempt_number INTEGER DEFAULT 1,
                retry_of_run_id TEXT REFERENCES task_runs(id),
                sandbox TEXT,
                container_name TEXT,
                flow_run_id TEXT REFERENCES flow_runs(id),
                not_before TEXT,
                approval_status TEXT,
                UNIQUE(task_id, run_number)
            );
            CREATE INDEX IF NOT EXISTS idx_runs_flow_run ON task_runs(flow_run_id, status);
            CREATE TABLE IF NOT EXISTS task_xcom (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_run_id TEXT NOT NULL REFERENCES task_runs(id),
                task_id TEXT NOT NULL REFERENCES tasks(id),
                key TEXT NOT NULL DEFAULT 'return_value',
                value TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(task_run_id, key)
            );
            CREATE INDEX IF NOT EXISTS idx_xcom_task ON task_xcom(task_id);
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                task_run_id TEXT NOT NULL REFERENCES task_runs(id),
                task_id TEXT NOT NULL REFERENCES tasks(id),
                question TEXT NOT NULL,
                answer TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending','answered','timeout')),
                created_at TEXT DEFAULT (datetime('now')),
                answered_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                body TEXT,
                task_id TEXT,
                task_run_id TEXT,
                flow_id TEXT,
                read_at TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(read_at, created_at);
            CREATE INDEX IF NOT EXISTS idx_runs_started ON task_runs(started_at);
            CREATE INDEX IF NOT EXISTS idx_runs_status_started ON task_runs(status, started_at);
            CREATE INDEX IF NOT EXISTS idx_runs_task_status ON task_runs(task_id, status);
        """)
        await db.commit()
    finally:
        await db.close()


async def _wipe_all_tables():
    """Delete all rows from every table between tests."""
    db = await _get_test_db()
    try:
        for table in (
            "task_xcom", "questions", "notifications",
            "task_runs", "task_dependencies", "tasks", "flow_runs", "agents", "flows",
            "settings",
        ):
            await db.execute(f"DELETE FROM {table}")
        await db.commit()
    finally:
        await db.close()


def _wipe_output_files():
    """Remove all task-run output files between tests."""
    for entry in os.scandir(_TEST_OUTPUT_DIR):
        try:
            os.remove(entry.path)
        except FileNotFoundError:
            pass


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_test_db():
    """Open a keeper connection and create tables once per test session."""
    global _keeper_conn
    _keeper_conn = await aiosqlite.connect(_TEST_DB_URI, uri=True)
    await _init_test_db()
    yield
    await _keeper_conn.close()
    shutil.rmtree(_TEST_OUTPUT_DIR, ignore_errors=True)


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    """Wipe all data between tests for isolation."""
    yield
    await _wipe_all_tables()
    _wipe_output_files()


@pytest_asyncio.fixture
async def db():
    """Direct DB connection for verifying data in tables."""
    conn = await _get_test_db()
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client that patches get_db to use the in-memory DB."""
    # Patch get_db in every module that imports it
    with (
        patch("database.get_db", _get_test_db),
        patch("routes.tasks.get_db", _get_test_db),
        patch("routes.task_runs.get_db", _get_test_db),
        patch("routes.flows.get_db", _get_test_db),
        patch("routes.agents.get_db", _get_test_db),
        patch("routes.analytics.get_db", _get_test_db),
        patch("routes.notifications.get_db", _get_test_db),
        patch("routes.approvals.get_db", _get_test_db),
        patch("orchestrator.get_db", _get_test_db),
    ):
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
