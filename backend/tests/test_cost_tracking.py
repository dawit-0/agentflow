"""Tests that total_cost_usd is captured from stream-json and persisted."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


class _FakeStream:
    """Minimal stdout/stderr stand-in for asyncio.subprocess.Process."""

    def __init__(self, data: bytes):
        self._data = data
        self._consumed = False

    async def read(self, n: int = -1) -> bytes:
        if self._consumed:
            return b""
        self._consumed = True
        return self._data


class _FakeProc:
    def __init__(self, stdout_bytes: bytes):
        self.pid = 99999
        self.returncode = 0
        self.stdin = AsyncMock()
        self.stdin.write = lambda _b: None  # sync write
        self.stdin.close = lambda: None
        self.stdout = _FakeStream(stdout_bytes)
        self.stderr = _FakeStream(b"")

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        pass


async def test_claude_provider_captures_total_cost_usd():
    from providers.claude_provider import ClaudeProvider

    stream = (
        json.dumps({"type": "assistant", "content": "hi"}) + "\n"
        + json.dumps({"type": "result", "total_cost_usd": 0.0123, "result": "done"}) + "\n"
    ).encode("utf-8")

    async def fake_exec(*args, **kwargs):
        return _FakeProc(stream)

    provider = ClaudeProvider()
    with patch("asyncio.create_subprocess_exec", new=fake_exec):
        events = []
        async for ev in provider.execute("p", "claude-sonnet-4-20250514", "/tmp", {}):
            events.append(ev)

    assert provider.total_cost_usd == pytest.approx(0.0123)


async def test_claude_provider_total_cost_defaults_to_zero_when_missing():
    from providers.claude_provider import ClaudeProvider

    stream = (json.dumps({"type": "assistant", "content": "hi"}) + "\n").encode("utf-8")

    async def fake_exec(*args, **kwargs):
        return _FakeProc(stream)

    provider = ClaudeProvider()
    with patch("asyncio.create_subprocess_exec", new=fake_exec):
        async for _ in provider.execute("p", "claude-sonnet-4-20250514", "/tmp", {}):
            pass

    assert provider.total_cost_usd == 0.0


async def test_set_finished_persists_cost(db):
    from db import task_runs as db_task_runs

    flow_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    await db.execute("INSERT INTO flows (id, name) VALUES (?, ?)", (flow_id, "f"))
    await db.execute(
        "INSERT INTO tasks (id, title, prompt, flow_id) VALUES (?, ?, ?, ?)",
        (task_id, "t", "p", flow_id),
    )
    await db_task_runs.insert(db, run_id, task_id, 1)
    await db.commit()

    await db_task_runs.set_finished(
        db, run_id, "success",
        exit_code=0, duration_ms=1500, num_turns=4, cost_usd=0.0567,
    )
    await db.commit()

    cursor = await db.execute("SELECT cost_usd FROM task_runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    assert row["cost_usd"] == pytest.approx(0.0567)
