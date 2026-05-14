"""Filesystem-backed storage for task run output streams.

Each task run's output is appended to ``<OUTPUT_DIR>/<run_id>.jsonl`` as one
JSON record per line. The DB only references the run via ``task_runs.id``;
the file path is derived from that ID.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


def _default_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "run_outputs"


def _output_dir() -> Path:
    override = os.environ.get("AGENTFLOW_OUTPUT_DIR")
    return Path(override) if override else _default_dir()


def _file_for(run_id: str) -> Path:
    return _output_dir() / f"{run_id}.jsonl"


def _append_sync(run_id: str, seq: int, output_type: str, content: str) -> None:
    path = _file_for(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "seq": seq,
        "type": output_type,
        "content": content,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_sync(run_id: str) -> list[dict]:
    path = _file_for(run_id)
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _delete_sync(run_id: str) -> None:
    try:
        _file_for(run_id).unlink()
    except FileNotFoundError:
        pass


async def insert(run_id: str, seq: int, output_type: str, content: str) -> None:
    await asyncio.to_thread(_append_sync, run_id, seq, output_type, content)


async def list_by_run(run_id: str) -> list[dict]:
    rows = await asyncio.to_thread(_read_sync, run_id)
    for row in rows:
        row["task_run_id"] = run_id
    return rows


async def get_result_text(run_id: str, max_chars: int = 4000) -> str:
    """Concatenate assistant/text/result entries, truncated to ``max_chars``."""
    rows = await asyncio.to_thread(_read_sync, run_id)
    parts: list[str] = []
    total = 0
    for row in rows:
        if row.get("type") not in ("assistant", "text", "result"):
            continue
        content = row.get("content", "")
        if total + len(content) > max_chars:
            parts.append(content[: max_chars - total])
            break
        parts.append(content)
        total += len(content)
    return "\n".join(parts)


async def delete_by_run(run_id: str) -> None:
    await asyncio.to_thread(_delete_sync, run_id)


async def delete_by_task(db: aiosqlite.Connection, task_id: str) -> None:
    cursor = await db.execute(
        "SELECT id FROM task_runs WHERE task_id = ?", (task_id,)
    )
    run_ids = [r[0] for r in await cursor.fetchall()]
    for run_id in run_ids:
        await delete_by_run(run_id)


async def delete_by_flow(db: aiosqlite.Connection, flow_id: str) -> None:
    cursor = await db.execute(
        """SELECT tr.id FROM task_runs tr
           JOIN tasks t ON t.id = tr.task_id
           WHERE t.flow_id = ?""",
        (flow_id,),
    )
    run_ids = [r[0] for r in await cursor.fetchall()]
    for run_id in run_ids:
        await delete_by_run(run_id)
