"""Notification CRUD endpoints."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from database import get_db
from db import notifications as db_notifications

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
) -> list[dict]:
    db = await get_db()
    try:
        return await db_notifications.list_recent(db, limit=limit, unread_only=unread_only)
    finally:
        await db.close()


@router.get("/unread_count")
async def get_unread_count() -> dict:
    db = await get_db()
    try:
        return {"unread_count": await db_notifications.unread_count(db)}
    finally:
        await db.close()


@router.post("/{nid}/read")
async def mark_notification_read(nid: str):
    db = await get_db()
    try:
        await db_notifications.mark_read(db, nid)
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/read_all")
async def mark_all_notifications_read():
    db = await get_db()
    try:
        affected = await db_notifications.mark_all_read(db)
        await db.commit()
        return {"ok": True, "marked": affected}
    finally:
        await db.close()
