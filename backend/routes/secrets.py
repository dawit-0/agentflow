import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from database import get_db
from db import secrets as db_secrets
from models import SecretCreate, SecretUpdate

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


@router.get("")
async def list_secrets():
    db = await get_db()
    try:
        rows = await db_secrets.list_all(db)
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.post("")
async def create_secret(body: SecretCreate):
    db = await get_db()
    try:
        if await db_secrets.name_exists(db, body.name):
            return JSONResponse({"error": f"a secret named {body.name} already exists"}, status_code=409)

        secret_id = str(uuid.uuid4())
        await db_secrets.insert(db, secret_id, body.name, body.description, body.value)
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

        if body.value is not None:
            if not body.value:
                return JSONResponse({"error": "value must not be empty"}, status_code=400)
            await db_secrets.update_value(db, secret_id, body.value)
        if body.description is not None:
            await db_secrets.update_description(db, secret_id, body.description)

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
