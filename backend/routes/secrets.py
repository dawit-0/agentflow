import re
import uuid

from fastapi import APIRouter, HTTPException

from crypto import encrypt
from database import get_db
from db import secrets as db_secrets
from models import SecretCreate, SecretUpdate

router = APIRouter(prefix="/api/secrets", tags=["secrets"])

# Uppercase env-var-style names so `{{secret.NAME}}` reads unambiguously in a prompt.
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _validate_name(raw: str) -> str:
    name = raw.strip().upper()
    if not NAME_RE.match(name):
        raise HTTPException(
            400,
            "Name must start with a letter and contain only uppercase letters, numbers, and underscores",
        )
    return name


def _serialize(row) -> dict:
    d = dict(row)
    d.pop("value_encrypted", None)
    return d


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
    name = _validate_name(body.name)
    if not body.value:
        raise HTTPException(400, "Value is required")

    db = await get_db()
    try:
        if await db_secrets.name_exists(db, name):
            raise HTTPException(409, f"A secret named '{name}' already exists")

        secret_id = str(uuid.uuid4())
        await db_secrets.insert(db, secret_id, name, body.description, encrypt(body.value))
        await db.commit()
        row = await db_secrets.get_by_id(db, secret_id)
        return _serialize(row)
    finally:
        await db.close()


@router.patch("/{secret_id}")
async def update_secret(secret_id: str, body: SecretUpdate):
    db = await get_db()
    try:
        existing = await db_secrets.get_by_id(db, secret_id)
        if not existing:
            raise HTTPException(404, "Secret not found")

        fields = {}
        if body.name is not None:
            name = _validate_name(body.name)
            if await db_secrets.name_exists(db, name, exclude_id=secret_id):
                raise HTTPException(409, f"A secret named '{name}' already exists")
            fields["name"] = name
        if body.description is not None:
            fields["description"] = body.description
        if body.value is not None:
            if not body.value:
                raise HTTPException(400, "Value cannot be empty")
            fields["value_encrypted"] = encrypt(body.value)

        if fields:
            await db_secrets.update(db, secret_id, **fields)
            await db.commit()

        row = await db_secrets.get_by_id(db, secret_id)
        return _serialize(row)
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
