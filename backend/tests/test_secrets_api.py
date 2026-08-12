import pytest

from crypto import decrypt
from secrets_template import redact_secret_values, resolve_secrets

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_secret(client, name="API_TOKEN", value="sekret-value-123", **kwargs):
    payload = {"name": name, "value": value, **kwargs}
    resp = await client.post("/api/secrets", json=payload)
    assert resp.status_code == 200
    return resp.json()


# ── CRUD ─────────────────────────────────────────────────────────────────────

async def test_create_secret_never_returns_value(client, db):
    data = await _create_secret(client, name="github_token", value="ghp_abc123")
    assert data["name"] == "GITHUB_TOKEN"  # normalized to uppercase
    assert "value" not in data
    assert "value_encrypted" not in data

    cursor = await db.execute("SELECT value_encrypted FROM secrets WHERE id = ?", (data["id"],))
    row = await cursor.fetchone()
    assert row["value_encrypted"] != "ghp_abc123"
    assert decrypt(row["value_encrypted"]) == "ghp_abc123"


async def test_list_secrets_never_leaks_value(client):
    await _create_secret(client, name="A", value="value-one")
    await _create_secret(client, name="B", value="value-two")
    resp = await client.get("/api/secrets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for row in data:
        assert "value" not in row
        assert "value_encrypted" not in row


async def test_create_duplicate_name_rejected(client):
    await _create_secret(client, name="DUP")
    resp = await client.post("/api/secrets", json={"name": "dup", "value": "x"})
    assert resp.status_code == 409


async def test_create_invalid_name_rejected(client):
    resp = await client.post("/api/secrets", json={"name": "1-bad-name", "value": "x"})
    assert resp.status_code == 400


async def test_create_empty_value_rejected(client):
    resp = await client.post("/api/secrets", json={"name": "EMPTY", "value": ""})
    assert resp.status_code == 400


async def test_update_secret_value(client, db):
    secret = await _create_secret(client, value="old-value")
    resp = await client.patch(f"/api/secrets/{secret['id']}", json={"value": "new-value"})
    assert resp.status_code == 200
    assert "value" not in resp.json()

    cursor = await db.execute("SELECT value_encrypted FROM secrets WHERE id = ?", (secret["id"],))
    row = await cursor.fetchone()
    assert decrypt(row["value_encrypted"]) == "new-value"


async def test_update_secret_rename_conflict(client):
    await _create_secret(client, name="FIRST")
    second = await _create_secret(client, name="SECOND")
    resp = await client.patch(f"/api/secrets/{second['id']}", json={"name": "first"})
    assert resp.status_code == 409


async def test_update_nonexistent_secret(client):
    resp = await client.patch("/api/secrets/bad-id", json={"description": "x"})
    assert resp.status_code == 404


async def test_delete_secret(client, db):
    secret = await _create_secret(client)
    resp = await client.delete(f"/api/secrets/{secret['id']}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    cursor = await db.execute("SELECT COUNT(*) FROM secrets WHERE id = ?", (secret["id"],))
    assert (await cursor.fetchone())[0] == 0


# ── Placeholder resolution ──────────────────────────────────────────────────

async def test_resolve_secrets_substitutes_placeholder(client, db):
    await _create_secret(client, name="API_KEY", value="sk-12345")
    text, missing, values = await resolve_secrets(db, "Use {{secret.API_KEY}} to call the API")
    assert missing == []
    assert values == {"API_KEY": "sk-12345"}
    assert text == "Use sk-12345 to call the API"


async def test_resolve_secrets_case_insensitive_reference(client, db):
    await _create_secret(client, name="TOKEN", value="tok-999")
    text, missing, values = await resolve_secrets(db, "auth: {{secret.token}}")
    assert missing == []
    assert text == "auth: tok-999"


async def test_resolve_secrets_reports_missing_and_leaves_text_untouched(db):
    text, missing, values = await resolve_secrets(db, "token: {{secret.NOPE}}")
    assert missing == ["NOPE"]
    assert values == {}
    assert text == "token: {{secret.NOPE}}"


async def test_resolve_secrets_no_placeholders_is_noop(db):
    text, missing, values = await resolve_secrets(db, "just a plain prompt")
    assert text == "just a plain prompt"
    assert missing == []
    assert values == {}


# ── Output redaction ─────────────────────────────────────────────────────────

async def test_redact_secret_values_masks_matches():
    content = "Response: sk-12345 done"
    redacted = redact_secret_values(content, {"API_KEY": "sk-12345"})
    assert redacted == "Response: ***API_KEY*** done"


async def test_redact_secret_values_skips_short_values():
    content = "the cat sat"
    redacted = redact_secret_values(content, {"SHORT": "at"})
    assert redacted == content


async def test_redact_secret_values_noop_without_secrets():
    content = "nothing to see here"
    assert redact_secret_values(content, {}) == content


# ── Task execution guard ─────────────────────────────────────────────────────

async def test_task_referencing_missing_secret_fails_fast(client, db):
    """A task whose prompt references an undefined secret should fail with a
    clear config error, without ever queuing a provider run."""
    flow = await client.post("/api/flows", json={"name": "Flow"})
    flow_id = flow.json()["id"]

    task = await client.post("/api/tasks", json={
        "title": "Needs a secret",
        "prompt": "Deploy using {{secret.DEPLOY_TOKEN}}",
        "flow_id": flow_id,
    })
    assert task.status_code == 200
    task_id = task.json()["id"]

    triggered = await client.post(f"/api/tasks/{task_id}/trigger")
    assert triggered.status_code == 200
    run_id = triggered.json()["id"]

    from orchestrator import Orchestrator

    class _FakeSio:
        async def emit(self, *args, **kwargs):
            pass

    orch = Orchestrator(_FakeSio())
    run_row = await db.execute("SELECT * FROM task_runs WHERE id = ?", (run_id,))
    run = dict(await run_row.fetchone())
    run["prompt"] = task.json()["prompt"]
    run["model"] = task.json()["model"]
    run["work_dir"] = task.json()["work_dir"]
    run["permissions"] = "{}"
    run["task_sandbox"] = ""

    await orch._execute_run(run_id, run)

    cursor = await db.execute("SELECT status, error_message FROM task_runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    assert row["status"] == "failed"
    assert "DEPLOY_TOKEN" in row["error_message"]
