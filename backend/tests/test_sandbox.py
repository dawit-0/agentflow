"""Unit tests for the Docker sandbox command builder."""

from providers.sandbox import SandboxConfig, docker_run_prefix


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


def test_restricted_permissions_use_no_network_and_ro_mount():
    cmd = docker_run_prefix(
        _cfg(),
        "/tmp/work",
        {"file_read": True, "file_write": False, "bash": False, "web_search": False, "mcp": False},
        "agentflow-test",
    )
    assert cmd[cmd.index("--network") + 1] == "none"
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
    # Still no network — neither web_search nor mcp
    assert cmd[cmd.index("--network") + 1] == "none"


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
