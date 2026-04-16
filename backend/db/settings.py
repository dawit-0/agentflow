from typing import Optional

import aiosqlite

DEFAULTS: dict = {
    "default_work_dir": "",
    "max_concurrent_runs": 5,
    "theme": "dark",
    "notify_on_task_failure": True,
    "notify_on_task_success": False,
    "notify_on_flow_completion": True,
    "notify_desktop_enabled": True,
    "notify_sound_enabled": False,
}


def _cast(key: str, raw: str):
    """Cast a stored string value back to the type implied by DEFAULTS."""
    default = DEFAULTS.get(key)
    # bool check MUST come before int check — isinstance(True, int) is True in Python.
    if isinstance(default, bool):
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default
    return raw


def _serialize(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


async def get_all(db: aiosqlite.Connection) -> dict:
    cursor = await db.execute("SELECT key, value FROM settings")
    rows = await cursor.fetchall()
    result = dict(DEFAULTS)
    for row in rows:
        key = row["key"]
        if key in DEFAULTS:
            result[key] = _cast(key, row["value"])
    return result


async def get(db: aiosqlite.Connection, key: str) -> Optional[object]:
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    if row:
        return _cast(key, row["value"])
    return DEFAULTS.get(key)


async def put(db: aiosqlite.Connection, key: str, value) -> None:
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, _serialize(value)),
    )
    await db.commit()


async def put_many(db: aiosqlite.Connection, data: dict) -> dict:
    for key, value in data.items():
        if key in DEFAULTS:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, _serialize(value)),
            )
    await db.commit()
    return await get_all(db)
