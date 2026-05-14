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


def _read_filtered_sync(
    run_id: str,
    after_seq: int | None,
    tail: int | None,
) -> tuple[list[dict], int]:
    """Read the run's output file, optionally filtering by ``after_seq`` /
    keeping only the last ``tail`` matching entries. Returns ``(rows,
    last_seq)`` where ``last_seq`` is the maximum ``seq`` present in the file
    (0 if the file is empty / missing) — useful for clients deciding whether
    more entries exist beyond what they've already seen.
    """
    path = _file_for(run_id)
    if not path.exists():
        return [], 0
    rows: list[dict] = []
    last_seq = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            seq = row.get("seq", 0)
            if isinstance(seq, int) and seq > last_seq:
                last_seq = seq
            if after_seq is not None and isinstance(seq, int) and seq <= after_seq:
                continue
            rows.append(row)
    if tail is not None and tail >= 0 and len(rows) > tail:
        rows = rows[-tail:]
    return rows, last_seq


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


async def list_by_run_paginated(
    run_id: str,
    after_seq: int | None = None,
    tail: int | None = None,
) -> dict:
    """Return ``{rows, last_seq}`` for the run's output, optionally filtered.

    - ``after_seq``: only return entries with ``seq`` strictly greater than
      this value. Used by the client to fetch entries appended since its
      last poll/tail.
    - ``tail``: keep only the last ``tail`` entries that pass the filter.
      Used for the initial load of a long-running run so the UI doesn't have
      to render the entire history up front.
    """
    rows, last_seq = await asyncio.to_thread(
        _read_filtered_sync, run_id, after_seq, tail
    )
    for row in rows:
        row["task_run_id"] = run_id
    return {"rows": rows, "last_seq": last_seq}


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
