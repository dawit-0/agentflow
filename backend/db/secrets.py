from typing import Optional

import aiosqlite

import crypto_utils

# Public columns only — encrypted_value never leaves this module.
_PUBLIC_COLS = "id, name, description, created_at, updated_at, last_used_at"


async def list_all(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    cursor = await db.execute(f"SELECT {_PUBLIC_COLS} FROM secrets ORDER BY name ASC")
    return await cursor.fetchall()


async def get_by_id(db: aiosqlite.Connection, secret_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute(f"SELECT {_PUBLIC_COLS} FROM secrets WHERE id = ?", (secret_id,))
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
        "INSERT INTO secrets (id, name, description, encrypted_value) VALUES (?, ?, ?, ?)",
        (secret_id, name, description, crypto_utils.encrypt(value)),
    )


async def update_value(db: aiosqlite.Connection, secret_id: str, value: str) -> None:
    await db.execute(
        "UPDATE secrets SET encrypted_value = ?, updated_at = datetime('now') WHERE id = ?",
        (crypto_utils.encrypt(value), secret_id),
    )


async def update_description(db: aiosqlite.Connection, secret_id: str, description: str) -> None:
    await db.execute(
        "UPDATE secrets SET description = ?, updated_at = datetime('now') WHERE id = ?",
        (description, secret_id),
    )


async def delete(db: aiosqlite.Connection, secret_id: str) -> None:
    await db.execute("DELETE FROM secrets WHERE id = ?", (secret_id,))


async def get_values_by_names(db: aiosqlite.Connection, names: list[str]) -> dict[str, str]:
    """Decrypt and return {name: value} for the given secret names, silently
    skipping any that no longer exist (e.g. deleted after a task referenced
    them). Stamps last_used_at for the ones found."""
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    cursor = await db.execute(
        f"SELECT id, name, encrypted_value FROM secrets WHERE name IN ({placeholders})",
        names,
    )
    rows = await cursor.fetchall()
    values: dict[str, str] = {}
    for row in rows:
        values[row["name"]] = crypto_utils.decrypt(row["encrypted_value"])
        await db.execute(
            "UPDATE secrets SET last_used_at = datetime('now') WHERE id = ?", (row["id"],)
        )
    return values
