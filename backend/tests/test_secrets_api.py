"""Tests for /api/secrets CRUD and encrypted storage."""

import pytest

pytestmark = pytest.mark.asyncio


async def _create_secret(client, key="GITHUB_TOKEN", value="ghp_supersecret", **kwargs):
    payload = {"key": key, "value": value, **kwargs}
    resp = await client.post("/api/secrets", json=payload)
    assert resp.status_code == 200
    return resp.json()


async def test_create_secret_never_returns_value(client):
    data = await _create_secret(client, description="GitHub PAT")
    assert data["key"] == "GITHUB_TOKEN"
    assert data["description"] == "GitHub PAT"
    assert "value" not in data
    assert "value_encrypted" not in data


async def test_value_is_encrypted_at_rest(client, db):
    data = await _create_secret(client, value="ghp_supersecret")
    cursor = await db.execute("SELECT value_encrypted FROM secrets WHERE id = ?", (data["id"],))
    row = await cursor.fetchone()
    assert row is not None
    assert "ghp_supersecret" not in row["value_encrypted"]

    from db import secrets as db_secrets
    values = await db_secrets.get_values_for_keys(db, ["GITHUB_TOKEN"])
    assert values == {"GITHUB_TOKEN": "ghp_supersecret"}


async def test_list_secrets_excludes_values(client):
    await _create_secret(client, key="A", value="1")
    await _create_secret(client, key="B", value="2")

    resp = await client.get("/api/secrets")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    for row in rows:
        assert "value" not in row
        assert "value_encrypted" not in row


async def test_create_rejects_duplicate_key(client):
    await _create_secret(client, key="DUP")
    resp = await client.post("/api/secrets", json={"key": "DUP", "value": "x"})
    assert resp.status_code == 409


async def test_create_normalizes_key_case(client):
    data = await _create_secret(client, key="my_token", value="x")
    assert data["key"] == "MY_TOKEN"


async def test_create_rejects_invalid_key(client):
    resp = await client.post("/api/secrets", json={"key": "1_BAD", "value": "x"})
    assert resp.status_code == 400
    resp = await client.post("/api/secrets", json={"key": "bad key!", "value": "x"})
    assert resp.status_code == 400


async def test_create_rejects_empty_value(client):
    resp = await client.post("/api/secrets", json={"key": "EMPTY", "value": ""})
    assert resp.status_code == 400


async def test_update_secret_value(client, db):
    data = await _create_secret(client, value="old")
    resp = await client.patch(f"/api/secrets/{data['id']}", json={"value": "new"})
    assert resp.status_code == 200

    from db import secrets as db_secrets
    values = await db_secrets.get_values_for_keys(db, ["GITHUB_TOKEN"])
    assert values["GITHUB_TOKEN"] == "new"


async def test_update_secret_description_only(client):
    data = await _create_secret(client)
    resp = await client.patch(f"/api/secrets/{data['id']}", json={"description": "renamed"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "renamed"


async def test_update_missing_secret_404(client):
    resp = await client.patch("/api/secrets/does-not-exist", json={"value": "x"})
    assert resp.status_code == 404


async def test_delete_secret(client, db):
    data = await _create_secret(client)
    resp = await client.delete(f"/api/secrets/{data['id']}")
    assert resp.status_code == 200

    resp = await client.get("/api/secrets")
    assert resp.json() == []


async def test_get_values_for_keys_skips_missing(client, db):
    await _create_secret(client, key="EXISTS", value="v")

    from db import secrets as db_secrets
    values = await db_secrets.get_values_for_keys(db, ["EXISTS", "DOES_NOT_EXIST"])
    assert values == {"EXISTS": "v"}


async def test_get_values_for_keys_empty_list(db):
    from db import secrets as db_secrets
    assert await db_secrets.get_values_for_keys(db, []) == {}
