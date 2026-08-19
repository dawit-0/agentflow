import pytest

import crypto_utils
from db import secrets as db_secrets

pytestmark = pytest.mark.asyncio


class _StubSio:
    async def emit(self, event, data=None):
        pass


def _orch():
    from orchestrator import Orchestrator
    return Orchestrator(_StubSio())


async def _create_secret(client, name="GITHUB_TOKEN", value="ghp_abc123", **kwargs):
    resp = await client.post("/api/secrets", json={"name": name, "value": value, **kwargs})
    assert resp.status_code == 200
    return resp.json()


async def test_create_secret_never_returns_value(client, db):
    data = await _create_secret(client, description="for CI")
    assert data["name"] == "GITHUB_TOKEN"
    assert data["description"] == "for CI"
    assert "value" not in data
    assert "encrypted_value" not in data

    # The DB row holds an encrypted value, not the plaintext.
    cursor = await db.execute("SELECT encrypted_value FROM secrets WHERE id = ?", (data["id"],))
    row = await cursor.fetchone()
    assert row["encrypted_value"] != "ghp_abc123"
    assert crypto_utils.decrypt(row["encrypted_value"]) == "ghp_abc123"


async def test_list_secrets_omits_values(client):
    await _create_secret(client, name="API_KEY", value="secret-value")
    resp = await client.get("/api/secrets")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "API_KEY"
    assert "value" not in items[0]
    assert "encrypted_value" not in items[0]


async def test_duplicate_name_rejected(client):
    await _create_secret(client, name="DUP")
    resp = await client.post("/api/secrets", json={"name": "DUP", "value": "x"})
    assert resp.status_code == 409


@pytest.mark.parametrize("bad_name", ["1BAD", "has space", "has-dash", ""])
async def test_invalid_name_rejected(client, bad_name):
    resp = await client.post("/api/secrets", json={"name": bad_name, "value": "x"})
    assert resp.status_code == 422


async def test_empty_value_rejected(client):
    resp = await client.post("/api/secrets", json={"name": "EMPTY", "value": ""})
    assert resp.status_code == 422


async def test_rotate_value(client, db):
    secret = await _create_secret(client, value="old-value")
    resp = await client.patch(f"/api/secrets/{secret['id']}", json={"value": "new-value"})
    assert resp.status_code == 200

    cursor = await db.execute("SELECT encrypted_value FROM secrets WHERE id = ?", (secret["id"],))
    row = await cursor.fetchone()
    assert crypto_utils.decrypt(row["encrypted_value"]) == "new-value"


async def test_update_description_only(client):
    secret = await _create_secret(client)
    resp = await client.patch(f"/api/secrets/{secret['id']}", json={"description": "rotated key"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "rotated key"


async def test_delete_secret(client):
    secret = await _create_secret(client)
    resp = await client.delete(f"/api/secrets/{secret['id']}")
    assert resp.status_code == 200
    resp = await client.get("/api/secrets")
    assert resp.json() == []


async def test_update_nonexistent_secret(client):
    resp = await client.patch("/api/secrets/nope", json={"value": "x"})
    assert resp.status_code == 404


async def test_get_values_by_names_decrypts_and_skips_missing(client, db):
    await _create_secret(client, name="TOKEN_A", value="value-a")
    await _create_secret(client, name="TOKEN_B", value="value-b")

    values = await db_secrets.get_values_by_names(db, ["TOKEN_A", "TOKEN_B", "MISSING"])
    assert values == {"TOKEN_A": "value-a", "TOKEN_B": "value-b"}


async def test_task_secret_names_round_trip(client):
    await _create_secret(client, name="DEPLOY_TOKEN", value="tok")
    resp = await client.post(
        "/api/tasks",
        json={"title": "T", "prompt": "p", "secret_names": ["DEPLOY_TOKEN"]},
    )
    assert resp.status_code == 200
    task = resp.json()
    assert task["secret_names"] == ["DEPLOY_TOKEN"]

    resp = await client.get(f"/api/tasks/{task['id']}")
    assert resp.json()["secret_names"] == ["DEPLOY_TOKEN"]


async def test_agent_default_secret_names_used_on_spawn(client):
    await _create_secret(client, name="AGENT_TOKEN", value="tok")
    resp = await client.post(
        "/api/agents",
        json={"name": "Deployer", "default_secret_names": ["AGENT_TOKEN"]},
    )
    assert resp.status_code == 200
    agent = resp.json()
    assert agent["default_secret_names"] == ["AGENT_TOKEN"]

    resp = await client.post(
        f"/api/agents/{agent['id']}/spawn",
        json={"title": "Spawned", "trigger": False},
    )
    assert resp.status_code == 200
    assert resp.json()["secret_names"] == ["AGENT_TOKEN"]

    # An explicit override on spawn wins over the agent default.
    resp = await client.post(
        f"/api/agents/{agent['id']}/spawn",
        json={"title": "Spawned2", "trigger": False, "secret_names": []},
    )
    assert resp.status_code == 200
    assert resp.json()["secret_names"] == []


async def test_orchestrator_resolves_secrets_env_for_queued_run(client, db):
    await _create_secret(client, name="DEPLOY_TOKEN", value="tok-123")

    resp = await client.post(
        "/api/tasks",
        json={"title": "T", "prompt": "p", "secret_names": ["DEPLOY_TOKEN"], "trigger": True},
    )
    task = resp.json()

    from db import task_runs as db_task_runs
    ready = await db_task_runs.get_queued_ready(db, 10)
    run = next(r for r in ready if r["task_id"] == task["id"])

    orch = _orch()
    env = await orch._resolve_secrets_env(db, run)
    assert env == {"DEPLOY_TOKEN": "tok-123"}


async def test_orchestrator_resolves_empty_env_when_no_secrets_selected(client, db):
    resp = await client.post("/api/tasks", json={"title": "T", "prompt": "p", "trigger": True})
    task = resp.json()

    from db import task_runs as db_task_runs
    ready = await db_task_runs.get_queued_ready(db, 10)
    run = next(r for r in ready if r["task_id"] == task["id"])

    orch = _orch()
    env = await orch._resolve_secrets_env(db, run)
    assert env == {}
