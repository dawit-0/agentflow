from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from database import get_db
from db import settings as db_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    default_work_dir: Optional[str] = None
    max_concurrent_runs: Optional[int] = None
    theme: Optional[str] = None
    notify_on_task_failure: Optional[bool] = None
    notify_on_task_success: Optional[bool] = None
    notify_on_flow_completion: Optional[bool] = None
    notify_desktop_enabled: Optional[bool] = None
    notify_sound_enabled: Optional[bool] = None


@router.get("")
async def get_settings():
    db = await get_db()
    try:
        return await db_settings.get_all(db)
    finally:
        await db.close()


@router.patch("")
async def update_settings(body: SettingsUpdate):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data:
        return await get_settings()

    # Validate max_concurrent_runs
    if "max_concurrent_runs" in data:
        val = data["max_concurrent_runs"]
        if val < 1 or val > 20:
            from fastapi import HTTPException
            raise HTTPException(400, "max_concurrent_runs must be between 1 and 20")

    # Validate theme
    if "theme" in data:
        if data["theme"] not in ("dark", "light"):
            from fastapi import HTTPException
            raise HTTPException(400, "theme must be 'dark' or 'light'")

    db = await get_db()
    try:
        result = await db_settings.put_many(db, data)

        # If max_concurrent_runs changed, update the orchestrator
        if "max_concurrent_runs" in data:
            from main import orchestrator
            orchestrator.update_max_concurrent(data["max_concurrent_runs"])

        return result
    finally:
        await db.close()
