from typing import Optional

import aiosqlite

import crypto


async def list_all(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    cursor = await db.execute(
        "SELECT id, name, description, created_at, updated_at FROM secrets ORDER BY name ASC"
    )
    return await cursor.fetchall()


async def get_by_id(db: aiosqlite.Connection, secret_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(
        "SELECT id, name, description, created_at, updated_at FROM secrets WHERE id = ?",
        (secret_id,),
    )
    return await cursor.fetchone()


async def name_exists(db: aiosqlite.Connection, name: str, exclude_id: Optional[str] = None) -> bool:
    if exclude_id:
        cursor = await db.execute(
            "SELECT id FROM secrets WHERE name = ? AND id != ?", (name, exclude_id)
        )
    else:
        cursor = await db.execute("SELECT id FROM secrets WHERE name = ?", (name,))
    return await cursor.fetchone() is not None


async def insert(db: aiosqlite.Connection, secret_id: str, name: str,
                  description: str, value: str) -> None:
    await db.execute(
        """INSERT INTO secrets (id, name, description, value_encrypted)
           VALUES (?, ?, ?, ?)""",
        (secret_id, name, description, crypto.encrypt(value)),
    )


async def update_fields(db: aiosqlite.Connection, secret_id: str,
                         updates: list[str], params: list) -> None:
    updates.append("updated_at = datetime('now')")
    params.append(secret_id)
    await db.execute(
        f"UPDATE secrets SET {', '.join(updates)} WHERE id = ?",
        params,
    )


async def delete(db: aiosqlite.Connection, secret_id: str) -> None:
    await db.execute("DELETE FROM secrets WHERE id = ?", (secret_id,))


async def get_values_by_names(db: aiosqlite.Connection, names: list[str]) -> dict[str, str]:
    """Decrypt and return {name: value} for the given secret names. Internal use
    only (orchestrator) — never expose decrypted values over the API."""
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    cursor = await db.execute(
        f"SELECT name, value_encrypted FROM secrets WHERE name IN ({placeholders})",
        names,
    )
    rows = await cursor.fetchall()
    result = {}
    for row in rows:
        try:
            result[row["name"]] = crypto.decrypt(row["value_encrypted"])
        except Exception:
            continue
    return result
