"""Sandbox configuration and Docker command construction."""

import os
import shutil
import subprocess
import tempfile
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


def prepare_auth_dir() -> str:
    """Create a per-run host directory holding just the credentials the
    container needs. Returns the host path; caller must ``shutil.rmtree`` it.

    Layout:
        <tmp>/claude_home/.credentials.json   ← mounted at /home/agent/.claude
        <tmp>/.claude.json                    ← mounted at /home/agent/.claude.json

    Credentials are sourced (in order):
        1. macOS keychain entry ``Claude Code-credentials`` (security CLI)
        2. ``~/.claude/.credentials.json`` on disk (Linux/CI)

    If neither is present the directory is still created — the container can
    fall back to ``ANTHROPIC_API_KEY`` if the host has one set.
    """
    tmpdir = tempfile.mkdtemp(prefix="agentflow-auth-")
    claude_home = os.path.join(tmpdir, "claude_home")
    os.makedirs(claude_home, mode=0o700)
    os.chmod(tmpdir, 0o700)

    creds_written = False

    # 1. macOS keychain
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            cred_path = os.path.join(claude_home, ".credentials.json")
            with open(cred_path, "w") as f:
                f.write(result.stdout.strip())
            os.chmod(cred_path, 0o600)
            creds_written = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2. File-based credentials
    if not creds_written:
        host_creds = os.path.expanduser("~/.claude/.credentials.json")
        if os.path.isfile(host_creds):
            cred_path = os.path.join(claude_home, ".credentials.json")
            shutil.copyfile(host_creds, cred_path)
            os.chmod(cred_path, 0o600)

    # ~/.claude.json — config file; copy host version if present, else stub
    host_dot_claude = os.path.expanduser("~/.claude.json")
    dot_claude_path = os.path.join(tmpdir, ".claude.json")
    if os.path.isfile(host_dot_claude):
        shutil.copyfile(host_dot_claude, dot_claude_path)
    else:
        with open(dot_claude_path, "w") as f:
            f.write("{}")
    os.chmod(dot_claude_path, 0o600)

    return tmpdir


def prepare_env_file(env: dict[str, str]) -> str:
    """Write secret env vars to a private tmpfile for ``docker run --env-file``.

    Passing secrets via ``-e KEY=VALUE`` on the ``docker`` command line would
    leak them to anything reading the host's process list (``ps aux``); an
    env file avoids that. Caller must delete the file once the container has
    started (``docker run`` reads it at container creation, not afterward).
    """
    fd, path = tempfile.mkstemp(prefix="agentflow-env-")
    with os.fdopen(fd, "w") as f:
        for key, value in env.items():
            # Docker env-file format has no quoting — newlines aren't representable.
            f.write(f"{key}={value.replace(chr(10), ' ')}\n")
    os.chmod(path, 0o600)
    return path


def docker_run_prefix(
    cfg: SandboxConfig,
    work_dir: str,
    permissions: dict,
    container_name: str,
    auth_dir: Optional[str] = None,
    env_file: Optional[str] = None,
) -> list[str]:
    """Build the ``docker run …`` prefix that wraps the inner command.

    Network: ``host`` if web_search or mcp is enabled (so local MCP servers and
    captive networks work), otherwise ``bridge``. We never use ``none`` —
    the Claude CLI must reach api.anthropic.com to do anything.

    Work dir: bind-mounted rw if file_write else ro.

    Auth dir: a host tmpdir from :func:`prepare_auth_dir` containing the
    credentials. Its ``claude_home`` subdir is mounted rw at
    ``/home/agent/.claude`` (the CLI writes session and project state there).
    The auth dir is required when sandbox is enabled; pass ``None`` only in
    tests.
    """
    network = "host" if (permissions.get("web_search") or permissions.get("mcp")) else "bridge"

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

    if auth_dir:
        claude_home = os.path.join(auth_dir, "claude_home")
        dot_claude = os.path.join(auth_dir, ".claude.json")
        # rw so the CLI can write session/project state — auth_dir is a
        # per-run tmpdir, so writes do not leak between runs.
        cmd.extend(["-v", f"{claude_home}:/home/agent/.claude"])
        cmd.extend(["-v", f"{dot_claude}:/home/agent/.claude.json"])

    cmd.extend(["-e", "HOME=/home/agent"])

    # Pass through API key if the host has one set (file-based fallback path).
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])

    if env_file:
        cmd.extend(["--env-file", env_file])

    cmd.append(cfg.image)
    return cmd
