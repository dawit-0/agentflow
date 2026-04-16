"""Read-only aggregation endpoints for the observability dashboard."""

from typing import Optional

from fastapi import APIRouter, Query

from database import get_db
from db import analytics as db_analytics

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary")
async def analytics_summary(since: Optional[str] = Query(None)) -> dict:
    db = await get_db()
    try:
        return await db_analytics.summary(db, since)
    finally:
        await db.close()


@router.get("/runs_by_day")
async def analytics_runs_by_day(since: Optional[str] = Query(None)) -> list[dict]:
    db = await get_db()
    try:
        return await db_analytics.runs_by_day(db, since)
    finally:
        await db.close()


@router.get("/top_failures")
async def analytics_top_failures(
    since: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
) -> list[dict]:
    db = await get_db()
    try:
        return await db_analytics.top_failing_tasks(db, since, limit)
    finally:
        await db.close()


@router.get("/duration_histogram")
async def analytics_duration_histogram(since: Optional[str] = Query(None)) -> list[dict]:
    db = await get_db()
    try:
        return await db_analytics.duration_histogram(db, since)
    finally:
        await db.close()


@router.get("/recent_failures")
async def analytics_recent_failures(limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    db = await get_db()
    try:
        return await db_analytics.recent_failures(db, limit)
    finally:
        await db.close()
