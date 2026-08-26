from typing import Optional

import aiosqlite

from crypto_utils import decrypt, encrypt

# Columns exposed by the API — value_encrypted is intentionally excluded.
_PUBLIC_COLUMNS = "id, key, description, created_at, updated_at"


async def list_all(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    cursor = await db.execute(f"SELECT {_PUBLIC_COLUMNS} FROM secrets ORDER BY key ASC")
    return await cursor.fetchall()


async def get_by_id(db: aiosqlite.Connection, secret_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(f"SELECT {_PUBLIC_COLUMNS} FROM secrets WHERE id = ?", (secret_id,))
    return await cursor.fetchone()


async def get_by_key(db: aiosqlite.Connection, key: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(f"SELECT {_PUBLIC_COLUMNS} FROM secrets WHERE key = ?", (key,))
    return await cursor.fetchone()


async def exists_by_key(db: aiosqlite.Connection, key: str) -> bool:
    cursor = await db.execute("SELECT 1 FROM secrets WHERE key = ?", (key,))
    return await cursor.fetchone() is not None


async def insert(db: aiosqlite.Connection, secret_id: str, key: str, value: str,
                  description: str = "") -> None:
    await db.execute(
        "INSERT INTO secrets (id, key, value_encrypted, description) VALUES (?, ?, ?, ?)",
        (secret_id, key, encrypt(value), description),
    )


async def update(db: aiosqlite.Connection, secret_id: str,
                  value: Optional[str] = None, description: Optional[str] = None) -> None:
    updates = ["updated_at = datetime('now')"]
    params: list = []
    if value is not None:
        updates.append("value_encrypted = ?")
        params.append(encrypt(value))
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    params.append(secret_id)
    await db.execute(f"UPDATE secrets SET {', '.join(updates)} WHERE id = ?", params)


async def delete(db: aiosqlite.Connection, secret_id: str) -> None:
    await db.execute("DELETE FROM secrets WHERE id = ?", (secret_id,))


async def get_values_for_keys(db: aiosqlite.Connection, keys: list[str]) -> dict[str, str]:
    """Resolve and decrypt secret values for the given key names.

    Keys that no longer exist (e.g. a secret was deleted after a task
    referenced it) are silently skipped rather than failing the run.
    """
    if not keys:
        return {}
    placeholders = ", ".join("?" for _ in keys)
    cursor = await db.execute(
        f"SELECT key, value_encrypted FROM secrets WHERE key IN ({placeholders})", keys
    )
    rows = await cursor.fetchall()
    return {row["key"]: decrypt(row["value_encrypted"]) for row in rows}
