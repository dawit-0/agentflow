"""Claude CLI subprocess provider."""

import asyncio
import json
from typing import AsyncIterator, Optional

from .base import BaseProvider, ProviderEvent
from .sandbox import SandboxConfig, docker_run_prefix


def _build_allowed_tools(permissions: dict) -> list[str]:
    """Map permission flags to Claude CLI --allowedTools values."""
    tools: list[str] = []
    if permissions.get("file_read", True):
        tools.extend(["Read", "Glob", "Grep"])
    if permissions.get("file_write", False):
        tools.extend(["Edit", "Write"])
    if permissions.get("bash", False):
        tools.append("Bash")
    if permissions.get("web_search", False):
        tools.extend(["WebSearch", "WebFetch"])
    if permissions.get("mcp", False):
        tools.append("mcp__*")
    return tools


def _build_claude_cmd(model: str, permissions: dict) -> list[str]:
    """The inner ``claude …`` invocation. Same args work host- and container-side."""
    cmd = [
        "claude",
        "--print",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
    ]
    for tool in _build_allowed_tools(permissions):
        cmd.extend(["--allowedTools", tool])
    return cmd


class ClaudeProvider(BaseProvider):
    """Execute a prompt via the ``claude`` CLI subprocess.

    When ``sandbox.enabled`` is True, the subprocess is ``docker run`` wrapping
    the same ``claude`` command. The streaming JSON protocol on stdout is
    identical in both modes.
    """

    def __init__(self) -> None:
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.pid: Optional[int] = None
        self.container_name: Optional[str] = None
        self.total_cost_usd: float = 0.0

    async def execute(
        self,
        prompt: str,
        model: str,
        work_dir: str,
        permissions: dict,
        sandbox: Optional[SandboxConfig] = None,
    ) -> AsyncIterator[ProviderEvent]:
        claude_cmd = _build_claude_cmd(model, permissions)
        spawn_cwd: Optional[str] = None
        sandbox_event_extra: dict = {}

        if sandbox and sandbox.enabled:
            container_name = sandbox.container_name or "agentflow-run"
            self.container_name = container_name
            cmd = docker_run_prefix(sandbox, work_dir, permissions, container_name) + claude_cmd
            sandbox_event_extra = {
                "sandbox": "docker",
                "image": sandbox.image,
                "container_name": container_name,
            }
        else:
            cmd = claude_cmd
            spawn_cwd = work_dir or None

        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=spawn_cwd,
        )
        # Feed prompt via stdin so special characters / quoting are never an issue
        self.proc.stdin.write(prompt.encode("utf-8"))
        self.proc.stdin.close()
        self.pid = self.proc.pid

        yield ProviderEvent(
            type="event",
            content=json.dumps({
                "event": "subprocess_started",
                "pid": self.proc.pid,
                **sandbox_event_extra,
            }),
        )

        # Stream stdout line-by-line
        assert self.proc.stdout is not None
        buffer = ""
        while True:
            chunk = await self.proc.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                content = line
                output_type = "text"

                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        output_type = parsed.get("type", "text")
                        if parsed.get("type") == "result":
                            cost = parsed.get("total_cost_usd")
                            if isinstance(cost, (int, float)):
                                self.total_cost_usd = float(cost)
                        if "content" in parsed:
                            content = parsed["content"]
                        elif "result" in parsed:
                            content = parsed["result"]
                        else:
                            content = line
                except json.JSONDecodeError:
                    pass

                yield ProviderEvent(type=output_type, content=content)

        await self.proc.wait()
        exit_code = self.proc.returncode

        stderr_data = ""
        if self.proc.stderr:
            stderr_bytes = await self.proc.stderr.read()
            stderr_data = stderr_bytes.decode("utf-8", errors="replace").strip()

        yield ProviderEvent(
            type="event",
            content=json.dumps({
                "event": "subprocess_exited",
                "exit_code": exit_code,
            }),
        )

        # Attach exit metadata so the orchestrator can read it
        self.exit_code = exit_code
        self.stderr_data = stderr_data

    async def cancel(self) -> None:
        # When sandboxed, the host process is the `docker` client. Stopping the
        # container kills the workload; the docker client exits in turn.
        if self.container_name:
            try:
                stop = await asyncio.create_subprocess_exec(
                    "docker", "stop", "--time=5", self.container_name,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await stop.wait()
            except Exception:
                pass

        if self.proc:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass
