from typing import Optional

import aiosqlite


async def list_all(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    cursor = await db.execute("SELECT * FROM agents ORDER BY created_at DESC")
    return await cursor.fetchall()


async def get_by_id(db: aiosqlite.Connection, agent_id: str) -> Optional[aiosqlite.Row]:
    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    return await cursor.fetchone()


async def insert(db: aiosqlite.Connection, agent_id: str, name: str,
                  description: str, instructions: str, context_json: str,
                  default_model: str, permissions_json: str,
                  default_work_dir: str,
                  default_flow_id: Optional[str],
                  default_sandbox: str = "") -> None:
    await db.execute(
        """INSERT INTO agents (id, name, description, instructions, context, default_model, default_permissions, default_work_dir, default_flow_id, default_sandbox)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (agent_id, name, description, instructions, context_json,
         default_model, permissions_json, default_work_dir, default_flow_id,
         default_sandbox),
    )


async def update_fields(db: aiosqlite.Connection, agent_id: str,
                          updates: list[str], params: list) -> None:
    updates.append("updated_at = datetime('now')")
    params.append(agent_id)
    await db.execute(
        f"UPDATE agents SET {', '.join(updates)} WHERE id = ?",
        params,
    )


async def delete(db: aiosqlite.Connection, agent_id: str) -> None:
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
