"""Sandbox configuration and Docker command construction."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class SandboxConfig:
    """Resolved sandbox config for one run. ``mode == ""`` means host execution."""

    mode: str = ""  # "" or "docker"
    image: str = "agentflow/claude-sandbox:latest"
    memory: str = "4g"
    cpus: str = "2"
    container_name: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.mode == "docker"


def docker_run_prefix(
    cfg: SandboxConfig,
    work_dir: str,
    permissions: dict,
    container_name: str,
) -> list[str]:
    """Build the ``docker run …`` prefix that wraps the inner command.

    Network: host if web_search or mcp is enabled, else none.
    Volume: work_dir bind-mounted rw if file_write else ro. ``~/.claude`` is
    mounted read-only inside the container so the CLI can re-use host auth.
    """
    network = "host" if (permissions.get("web_search") or permissions.get("mcp")) else "none"

    cmd: list[str] = [
        "docker", "run",
        "--rm",
        "-i",
        "--name", container_name,
        "--network", network,
        "--memory", cfg.memory,
        "--cpus", cfg.cpus,
        "--pids-limit", "512",
    ]

    if work_dir:
        mount_mode = "rw" if permissions.get("file_write") else "ro"
        cmd.extend(["-v", f"{work_dir}:{work_dir}:{mount_mode}"])
        cmd.extend(["-w", work_dir])

    claude_dir = os.path.expanduser("~/.claude")
    if os.path.isdir(claude_dir):
        cmd.extend(["-v", f"{claude_dir}:/home/agent/.claude:ro"])

    cmd.extend(["-e", "HOME=/home/agent"])

    cmd.append(cfg.image)
    return cmd
