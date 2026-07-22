import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "agentflow.db")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
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
                flow_id TEXT NOT NULL REFERENCES flows(id),
                agent_id TEXT REFERENCES agents(id),
                permissions TEXT DEFAULT '{}',
                schedule TEXT,
                schedule_enabled INTEGER DEFAULT 1,
                next_run_at TEXT,
                last_run_at TEXT,
                max_retries INTEGER DEFAULT 0,
                retry_delay_seconds INTEGER DEFAULT 10,
                task_type TEXT DEFAULT 'agent',
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

            CREATE TABLE IF NOT EXISTS task_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id),
                run_number INTEGER NOT NULL,
                trigger TEXT DEFAULT 'manual' CHECK(trigger IN ('manual','schedule','dependency','retry')),
                status TEXT DEFAULT 'queued' CHECK(status IN ('queued','running','success','failed','cancelled','awaiting_approval')),
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
                flow_run_id TEXT REFERENCES flow_runs(id),
                not_before TEXT,
                UNIQUE(task_id, run_number)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

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

        # Migrate existing databases: add new columns if missing
        for col, default in [("pass_output", "1"), ("max_output_chars", "4000")]:
            try:
                await db.execute(f"ALTER TABLE task_dependencies ADD COLUMN {col} INTEGER DEFAULT {default}")
                await db.commit()
            except Exception:
                pass  # column already exists

        for table, col, ddl in [
            ("tasks", "sandbox", "ALTER TABLE tasks ADD COLUMN sandbox TEXT DEFAULT ''"),
            ("agents", "default_sandbox", "ALTER TABLE agents ADD COLUMN default_sandbox TEXT DEFAULT ''"),
            ("task_runs", "sandbox", "ALTER TABLE task_runs ADD COLUMN sandbox TEXT"),
            ("task_runs", "container_name", "ALTER TABLE task_runs ADD COLUMN container_name TEXT"),
            ("flows", "max_active_runs", "ALTER TABLE flows ADD COLUMN max_active_runs INTEGER DEFAULT 1"),
            ("task_runs", "flow_run_id", "ALTER TABLE task_runs ADD COLUMN flow_run_id TEXT REFERENCES flow_runs(id)"),
            ("task_runs", "not_before", "ALTER TABLE task_runs ADD COLUMN not_before TEXT"),
            ("tasks", "task_type", "ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'agent'"),
        ]:
            try:
                await db.execute(ddl)
                await db.commit()
            except Exception:
                pass  # column already exists

        # Index on a migrated column — must run after the ALTERs above
        try:
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_flow_run ON task_runs(flow_run_id, status)"
            )
            await db.commit()
        except Exception:
            pass

        await _migrate_task_runs_approval_status(db)

    finally:
        await db.close()


async def _migrate_task_runs_approval_status(db: aiosqlite.Connection) -> None:
    """Add 'awaiting_approval' to task_runs.status, for approval-gate tasks.

    SQLite can't alter a CHECK constraint in place, so an existing table is
    rebuilt (SQLite's documented ALTER-table-via-rename procedure). Fresh
    databases already get the new constraint from the CREATE TABLE above and
    are skipped here.
    """
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='task_runs'"
    )
    row = await cursor.fetchone()
    if not row or not row[0] or "awaiting_approval" in row[0]:
        return

    # Only carry over columns that actually exist on this DB's task_runs —
    # very old databases may predate columns added by earlier migrations
    # (sandbox, flow_run_id, ...); anything missing just gets the new
    # table's column default.
    old_cols_cursor = await db.execute("PRAGMA table_info(task_runs)")
    old_cols = {r[1] for r in await old_cols_cursor.fetchall()}
    full_columns = [
        "id", "task_id", "run_number", "trigger", "status", "pid", "exit_code",
        "cost_usd", "duration_ms", "num_turns", "started_at", "finished_at",
        "error_message", "attempt_number", "retry_of_run_id", "flow_run_id",
        "not_before", "sandbox", "container_name",
    ]
    carry_over = ", ".join(c for c in full_columns if c in old_cols)

    await db.execute("PRAGMA foreign_keys=OFF")
    try:
        await db.execute("ALTER TABLE task_runs RENAME TO task_runs_old")
        await db.execute("""
            CREATE TABLE task_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id),
                run_number INTEGER NOT NULL,
                trigger TEXT DEFAULT 'manual' CHECK(trigger IN ('manual','schedule','dependency','retry')),
                status TEXT DEFAULT 'queued' CHECK(status IN ('queued','running','success','failed','cancelled','awaiting_approval')),
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
                flow_run_id TEXT REFERENCES flow_runs(id),
                not_before TEXT,
                sandbox TEXT,
                container_name TEXT,
                UNIQUE(task_id, run_number)
            )
        """)
        await db.execute(
            f"INSERT INTO task_runs ({carry_over}) SELECT {carry_over} FROM task_runs_old"
        )
        await db.execute("DROP TABLE task_runs_old")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON task_runs(started_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_runs_status_started ON task_runs(status, started_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_runs_task_status ON task_runs(task_id, status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_runs_flow_run ON task_runs(flow_run_id, status)")
        await db.commit()
    finally:
        await db.execute("PRAGMA foreign_keys=ON")
