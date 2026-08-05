import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import crypto
from database import get_db
from db import secrets as db_secrets
from models import SecretCreate, SecretUpdate

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


@router.get("")
async def list_secrets():
    """List secret metadata. Values are never returned by the API."""
    db = await get_db()
    try:
        rows = await db_secrets.list_all(db)
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.post("")
async def create_secret(body: SecretCreate):
    name = body.name.strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    if not body.value:
        return JSONResponse({"error": "value is required"}, status_code=400)

    db = await get_db()
    try:
        if await db_secrets.name_exists(db, name):
            return JSONResponse({"error": f"a secret named '{name}' already exists"}, status_code=409)

        secret_id = str(uuid.uuid4())
        await db_secrets.insert(db, secret_id, name, body.description, body.value)
        await db.commit()
        row = await db_secrets.get_by_id(db, secret_id)
        return dict(row)
    finally:
        await db.close()


@router.patch("/{secret_id}")
async def update_secret(secret_id: str, body: SecretUpdate):
    db = await get_db()
    try:
        existing = await db_secrets.get_by_id(db, secret_id)
        if not existing:
            return JSONResponse({"error": "not found"}, status_code=404)

        updates = []
        params = []

        if body.name is not None:
            name = body.name.strip()
            if not name:
                return JSONResponse({"error": "name cannot be empty"}, status_code=400)
            if await db_secrets.name_exists(db, name, exclude_id=secret_id):
                return JSONResponse({"error": f"a secret named '{name}' already exists"}, status_code=409)
            updates.append("name = ?")
            params.append(name)

        if body.description is not None:
            updates.append("description = ?")
            params.append(body.description)

        if body.value is not None:
            if not body.value:
                return JSONResponse({"error": "value cannot be empty"}, status_code=400)
            updates.append("value_encrypted = ?")
            params.append(crypto.encrypt(body.value))

        if not updates:
            return JSONResponse({"error": "no fields to update"}, status_code=400)

        await db_secrets.update_fields(db, secret_id, updates, params)
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
