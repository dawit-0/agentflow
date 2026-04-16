"""Aggregation queries over task_runs for the observability dashboard."""

from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite


def _default_since(days: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _percentile(sorted_values: list[int], p: float) -> int:
    if not sorted_values:
        return 0
    k = (len(sorted_values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return int(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


async def summary(db: aiosqlite.Connection, since: Optional[str] = None) -> dict:
    since = since or _default_since()

    cursor = await db.execute(
        """SELECT
               COUNT(*) AS total_runs,
               COALESCE(SUM(CASE WHEN status='success'   THEN 1 ELSE 0 END), 0) AS success_count,
               COALESCE(SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END), 0) AS failed_count,
               COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END), 0) AS cancelled_count,
               COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
               COALESCE(AVG(CASE WHEN status='success' THEN duration_ms END), 0) AS avg_duration_ms
           FROM task_runs
           WHERE started_at >= ?""",
        (since,),
    )
    row = dict(await cursor.fetchone())

    cursor = await db.execute(
        """SELECT duration_ms FROM task_runs
           WHERE status='success' AND started_at >= ?
           ORDER BY duration_ms""",
        (since,),
    )
    durations = [r[0] for r in await cursor.fetchall()]

    total = row["total_runs"] or 0
    success = row["success_count"] or 0
    return {
        "since": since,
        "total_runs": total,
        "success_count": success,
        "failed_count": row["failed_count"] or 0,
        "cancelled_count": row["cancelled_count"] or 0,
        "success_rate": (success / total) if total else 0.0,
        "total_cost_usd": float(row["total_cost_usd"] or 0),
        "avg_duration_ms": int(row["avg_duration_ms"] or 0),
        "p50_duration_ms": _percentile(durations, 0.50),
        "p95_duration_ms": _percentile(durations, 0.95),
    }


async def runs_by_day(db: aiosqlite.Connection, since: Optional[str] = None) -> list[dict]:
    since = since or _default_since()
    cursor = await db.execute(
        """SELECT DATE(started_at) AS date,
                  COUNT(*) AS total,
                  SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success,
                  SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END) AS failed,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd
           FROM task_runs
           WHERE started_at >= ?
           GROUP BY DATE(started_at)
           ORDER BY date ASC""",
        (since,),
    )
    return [
        {
            "date": row["date"],
            "total": row["total"],
            "success": row["success"] or 0,
            "failed": row["failed"] or 0,
            "cost_usd": float(row["cost_usd"] or 0),
        }
        for row in await cursor.fetchall()
    ]


async def top_failing_tasks(db: aiosqlite.Connection, since: Optional[str] = None,
                             limit: int = 10) -> list[dict]:
    since = since or _default_since()
    cursor = await db.execute(
        """SELECT t.id AS task_id, t.title,
                  COUNT(*) AS failure_count,
                  MAX(tr.finished_at) AS last_failure_at
           FROM task_runs tr
           JOIN tasks t ON t.id = tr.task_id
           WHERE tr.status = 'failed' AND tr.started_at >= ?
           GROUP BY t.id, t.title
           ORDER BY failure_count DESC, last_failure_at DESC
           LIMIT ?""",
        (since, limit),
    )
    return [dict(r) for r in await cursor.fetchall()]


DURATION_BUCKETS = [
    ("<10s", 0, 10_000),
    ("10-30s", 10_000, 30_000),
    ("30-60s", 30_000, 60_000),
    ("1-5m", 60_000, 300_000),
    (">5m", 300_000, None),
]


async def duration_histogram(db: aiosqlite.Connection, since: Optional[str] = None) -> list[dict]:
    since = since or _default_since()
    results = []
    for label, lo, hi in DURATION_BUCKETS:
        if hi is None:
            query = (
                "SELECT COUNT(*) FROM task_runs "
                "WHERE status='success' AND started_at >= ? AND duration_ms >= ?"
            )
            params: tuple = (since, lo)
        else:
            query = (
                "SELECT COUNT(*) FROM task_runs "
                "WHERE status='success' AND started_at >= ? "
                "AND duration_ms >= ? AND duration_ms < ?"
            )
            params = (since, lo, hi)
        cursor = await db.execute(query, params)
        count = (await cursor.fetchone())[0] or 0
        results.append({"bucket": label, "count": count})
    return results


async def recent_failures(db: aiosqlite.Connection, limit: int = 20) -> list[dict]:
    cursor = await db.execute(
        """SELECT tr.id AS run_id, tr.task_id, tr.run_number,
                  tr.finished_at, tr.duration_ms, tr.error_message,
                  t.title AS task_title
           FROM task_runs tr
           JOIN tasks t ON t.id = tr.task_id
           WHERE tr.status = 'failed'
           ORDER BY tr.finished_at DESC
           LIMIT ?""",
        (limit,),
    )
    rows = []
    for r in await cursor.fetchall():
        d = dict(r)
        if d.get("error_message") and len(d["error_message"]) > 300:
            d["error_message"] = d["error_message"][:300] + "..."
        rows.append(d)
    return rows
