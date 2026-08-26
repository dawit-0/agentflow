import re
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from database import get_db
from db import secrets as db_secrets
from models import SecretCreate, SecretUpdate

router = APIRouter(prefix="/api/secrets", tags=["secrets"])

# Enforced as env var names: uppercase letters, digits, underscores; can't start with a digit.
_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


@router.get("")
async def list_secrets():
    """List secrets — never includes decrypted values."""
    db = await get_db()
    try:
        rows = await db_secrets.list_all(db)
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.post("")
async def create_secret(body: SecretCreate):
    key = body.key.strip().upper()
    if not _KEY_RE.match(key):
        return JSONResponse(
            {"error": "key must be uppercase letters, digits, and underscores, and can't start with a digit"},
            status_code=400,
        )
    if not body.value:
        return JSONResponse({"error": "value is required"}, status_code=400)

    db = await get_db()
    try:
        if await db_secrets.exists_by_key(db, key):
            return JSONResponse({"error": f"a secret named {key} already exists"}, status_code=409)

        secret_id = str(uuid.uuid4())
        await db_secrets.insert(db, secret_id, key, body.value, body.description)
        await db.commit()
        row = await db_secrets.get_by_id(db, secret_id)
        return dict(row)
    finally:
        await db.close()


@router.patch("/{secret_id}")
async def update_secret(secret_id: str, body: SecretUpdate):
    db = await get_db()
    try:
        row = await db_secrets.get_by_id(db, secret_id)
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        if body.value is None and body.description is None:
            return JSONResponse({"error": "no fields to update"}, status_code=400)

        await db_secrets.update(db, secret_id, value=body.value, description=body.description)
        await db.commit()
        row = await db_secrets.get_by_id(db, secret_id)
        return dict(row)
    finally:
        await db.close()


@router.delete("/{secret_id}")
async def delete_secret(secret_id: str):
    db = await get_db()
    try:
        await db_secrets.delete(db, secret_id)
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()
