"""Unit tests for the Docker sandbox command builder."""

import json
import os

from providers.sandbox import SandboxConfig, docker_run_prefix, prepare_auth_dir


def _cfg(**kw) -> SandboxConfig:
    base = dict(
        mode="docker",
        image="agentflow/test:latest",
        memory="2g",
        cpus="1",
        container_name="agentflow-test",
    )
    base.update(kw)
    return SandboxConfig(**base)


def test_enabled_only_when_mode_is_docker():
    assert _cfg().enabled is True
    assert SandboxConfig(mode="").enabled is False


def test_restricted_permissions_use_bridge_network_and_ro_mount():
    cmd = docker_run_prefix(
        _cfg(),
        "/tmp/work",
        {"file_read": True, "file_write": False, "bash": False, "web_search": False, "mcp": False},
        "agentflow-test",
    )
    # The Claude CLI must reach api.anthropic.com, so the default is bridge,
    # never `none`.
    assert cmd[cmd.index("--network") + 1] == "bridge"
    assert "/tmp/work:/tmp/work:ro" in cmd
    assert "-w" in cmd
    assert cmd[cmd.index("-w") + 1] == "/tmp/work"


def test_file_write_uses_rw_mount():
    cmd = docker_run_prefix(
        _cfg(),
        "/home/me/repo",
        {"file_read": True, "file_write": True, "bash": True, "web_search": False, "mcp": False},
        "agentflow-test",
    )
    assert "/home/me/repo:/home/me/repo:rw" in cmd
    # bridge by default — neither web_search nor mcp asked for host network
    assert cmd[cmd.index("--network") + 1] == "bridge"


def test_web_search_enables_host_network():
    cmd = docker_run_prefix(
        _cfg(),
        "/work",
        {"file_read": True, "file_write": True, "bash": True, "web_search": True, "mcp": False},
        "agentflow-test",
    )
    assert cmd[cmd.index("--network") + 1] == "host"


def test_mcp_enables_host_network():
    cmd = docker_run_prefix(
        _cfg(),
        "/work",
        {"file_read": True, "file_write": False, "bash": False, "web_search": False, "mcp": True},
        "agentflow-test",
    )
    assert cmd[cmd.index("--network") + 1] == "host"


def test_empty_work_dir_omits_volume_and_workdir():
    cmd = docker_run_prefix(_cfg(), "", {"file_read": True}, "agentflow-test")
    # No bind-mounted work_dir
    assert not any(":/" in arg and arg.startswith("/tmp") for arg in cmd)
    assert "-w" not in cmd


def test_resource_caps_and_container_name_present():
    cmd = docker_run_prefix(_cfg(memory="8g", cpus="4"), "/w", {"file_read": True}, "agentflow-xyz")
    assert "--memory" in cmd and cmd[cmd.index("--memory") + 1] == "8g"
    assert "--cpus" in cmd and cmd[cmd.index("--cpus") + 1] == "4"
    assert "--pids-limit" in cmd
    assert "--rm" in cmd
    assert "-i" in cmd
    assert cmd[cmd.index("--name") + 1] == "agentflow-xyz"
    # Image is the final positional arg before the inner command (caller appends claude_cmd)
    assert cmd[-1] == "agentflow/test:latest"


def test_auth_dir_mounts_credentials_rw(tmp_path):
    auth_dir = str(tmp_path / "auth")
    os.makedirs(os.path.join(auth_dir, "claude_home"))
    with open(os.path.join(auth_dir, ".claude.json"), "w") as f:
        f.write("{}")

    cmd = docker_run_prefix(_cfg(), "/w", {"file_read": True}, "agentflow-test", auth_dir=auth_dir)

    # Credentials dir is mounted rw (no :ro suffix) so the CLI can write
    # session/project state without silently failing.
    assert f"{auth_dir}/claude_home:/home/agent/.claude" in cmd
    assert f"{auth_dir}/.claude.json:/home/agent/.claude.json" in cmd


def test_secrets_passed_as_env_flags():
    cmd = docker_run_prefix(
        _cfg(), "/w", {"file_read": True}, "agentflow-test",
        secrets={"GITHUB_TOKEN": "ghp_abc123", "DB_PASSWORD": "hunter2"},
    )
    assert "-e" in cmd
    assert "GITHUB_TOKEN=ghp_abc123" in cmd
    assert "DB_PASSWORD=hunter2" in cmd


def test_no_secrets_means_no_extra_env_flags():
    cmd = docker_run_prefix(_cfg(), "/w", {"file_read": True}, "agentflow-test")
    assert "GITHUB_TOKEN" not in " ".join(cmd)


def test_prepare_auth_dir_writes_required_files(tmp_path, monkeypatch):
    # Point HOME at a temp dir so we don't depend on the developer's real home
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    auth_dir = prepare_auth_dir()
    try:
        assert os.path.isdir(os.path.join(auth_dir, "claude_home"))
        # .claude.json stub written even when host has no config
        with open(os.path.join(auth_dir, ".claude.json")) as f:
            assert json.loads(f.read()) == {}
    finally:
        import shutil
        shutil.rmtree(auth_dir, ignore_errors=True)
