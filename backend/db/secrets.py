from typing import Optional

import aiosqlite


async def insert(db: aiosqlite.Connection, id: str, name: str, description: str,
                 value_encrypted: str) -> None:
    await db.execute(
        "INSERT INTO secrets (id, name, description, value_encrypted) VALUES (?, ?, ?, ?)",
        (id, name, description, value_encrypted),
    )


async def list_all(db: aiosqlite.Connection) -> list:
    cursor = await db.execute(
        "SELECT id, name, description, created_at, updated_at, last_used_at "
        "FROM secrets ORDER BY name"
    )
    return await cursor.fetchall()


async def get_by_id(db: aiosqlite.Connection, id: str):
    cursor = await db.execute("SELECT * FROM secrets WHERE id = ?", (id,))
    return await cursor.fetchone()


async def get_by_name(db: aiosqlite.Connection, name: str):
    cursor = await db.execute("SELECT * FROM secrets WHERE name = ?", (name,))
    return await cursor.fetchone()


async def name_exists(db: aiosqlite.Connection, name: str, exclude_id: Optional[str] = None) -> bool:
    if exclude_id:
        cursor = await db.execute(
            "SELECT 1 FROM secrets WHERE name = ? AND id != ?", (name, exclude_id))
    else:
        cursor = await db.execute("SELECT 1 FROM secrets WHERE name = ?", (name,))
    return await cursor.fetchone() is not None


async def update(db: aiosqlite.Connection, id: str, **fields) -> None:
    if not fields:
        return
    set_parts = []
    values = []
    for key, value in fields.items():
        set_parts.append(f"{key} = ?")
        values.append(value)
    set_parts.append("updated_at = datetime('now')")
    values.append(id)
    await db.execute(f"UPDATE secrets SET {', '.join(set_parts)} WHERE id = ?", values)


async def delete(db: aiosqlite.Connection, id: str) -> None:
    await db.execute("DELETE FROM secrets WHERE id = ?", (id,))


async def touch_last_used(db: aiosqlite.Connection, names: list[str]) -> None:
    if not names:
        return
    placeholders = ",".join("?" for _ in names)
    await db.execute(
        f"UPDATE secrets SET last_used_at = datetime('now') WHERE name IN ({placeholders})",
        names,
    )
