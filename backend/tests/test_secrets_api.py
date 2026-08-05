import pytest

import crypto


pytestmark = pytest.mark.asyncio


# ── CRUD API ─────────────────────────────────────────────────────────────

async def _create_secret(client, name="GITHUB_TOKEN", value="ghp_abc123", **kwargs):
    resp = await client.post("/api/secrets", json={"name": name, "value": value, **kwargs})
    assert resp.status_code == 200
    return resp.json()


async def test_create_secret_never_returns_value(client):
    data = await _create_secret(client, description="for opening PRs")
    assert data["name"] == "GITHUB_TOKEN"
    assert data["description"] == "for opening PRs"
    assert "value" not in data
    assert "value_encrypted" not in data


async def test_value_stored_encrypted_in_db(client, db):
    data = await _create_secret(client, value="ghp_plaintext_should_not_appear")
    cursor = await db.execute("SELECT value_encrypted FROM secrets WHERE id = ?", (data["id"],))
    row = await cursor.fetchone()
    assert row is not None
    assert "ghp_plaintext_should_not_appear" not in row["value_encrypted"]
    assert crypto.decrypt(row["value_encrypted"]) == "ghp_plaintext_should_not_appear"


async def test_list_secrets_excludes_value(client):
    await _create_secret(client, name="A", value="secret-a")
    await _create_secret(client, name="B", value="secret-b")
    resp = await client.get("/api/secrets")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    for item in items:
        assert "value" not in item
        assert "value_encrypted" not in item


async def test_duplicate_name_rejected(client):
    await _create_secret(client, name="DUP")
    resp = await client.post("/api/secrets", json={"name": "DUP", "value": "x"})
    assert resp.status_code == 409


async def test_create_requires_value(client):
    resp = await client.post("/api/secrets", json={"name": "NOVAL", "value": ""})
    assert resp.status_code == 400


async def test_update_secret_description(client):
    data = await _create_secret(client)
    resp = await client.patch(f"/api/secrets/{data['id']}", json={"description": "rotated"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "rotated"
    assert "value" not in resp.json()


async def test_rotate_secret_value(client, db):
    data = await _create_secret(client, value="old-value")
    resp = await client.patch(f"/api/secrets/{data['id']}", json={"value": "new-value"})
    assert resp.status_code == 200

    cursor = await db.execute("SELECT value_encrypted FROM secrets WHERE id = ?", (data["id"],))
    row = await cursor.fetchone()
    assert crypto.decrypt(row["value_encrypted"]) == "new-value"


async def test_delete_secret(client, db):
    data = await _create_secret(client)
    resp = await client.delete(f"/api/secrets/{data['id']}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    cursor = await db.execute("SELECT COUNT(*) FROM secrets WHERE id = ?", (data["id"],))
    assert (await cursor.fetchone())[0] == 0


# ── Task/agent wiring ───────────────────────────────────────────────────────

async def test_task_stores_secret_refs(client):
    await _create_secret(client, name="API_KEY", value="v")
    resp = await client.post("/api/tasks", json={
        "title": "Uses secret",
        "prompt": "do the thing",
        "secrets": ["API_KEY"],
        "trigger": False,
    })
    assert resp.status_code == 200
    assert resp.json()["secrets"] == ["API_KEY"]


async def test_agent_default_secrets_flow_into_spawned_task(client):
    await _create_secret(client, name="DEPLOY_TOKEN", value="v")
    agent_resp = await client.post("/api/agents", json={
        "name": "Deployer",
        "default_secrets": ["DEPLOY_TOKEN"],
    })
    assert agent_resp.status_code == 200
    agent = agent_resp.json()
    assert agent["default_secrets"] == ["DEPLOY_TOKEN"]

    spawn_resp = await client.post(f"/api/agents/{agent['id']}/spawn", json={
        "title": "Deploy",
        "trigger": False,
    })
    assert spawn_resp.status_code == 200
    assert spawn_resp.json()["secrets"] == ["DEPLOY_TOKEN"]


async def test_spawn_overrides_agent_default_secrets(client):
    await _create_secret(client, name="A", value="a")
    await _create_secret(client, name="B", value="b")
    agent_resp = await client.post("/api/agents", json={"name": "Agent", "default_secrets": ["A"]})
    agent = agent_resp.json()

    spawn_resp = await client.post(f"/api/agents/{agent['id']}/spawn", json={
        "title": "Override", "trigger": False, "secrets": ["B"],
    })
    assert spawn_resp.json()["secrets"] == ["B"]
