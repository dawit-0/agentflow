from fastapi import APIRouter
from database import get_db
from db import task_runs as db_task_runs, task_run_output as db_output
from db import task_xcom as db_xcom

router = APIRouter(prefix="/api/task-runs", tags=["task-runs"])


@router.get("")
async def list_task_runs(task_id: str = None):
    db = await get_db()
    try:
        rows = await db_task_runs.list_all(db, task_id=task_id)
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.get("/{run_id}")
async def get_task_run(run_id: str):
    db = await get_db()
    try:
        row = await db_task_runs.get_by_id(db, run_id)
        if not row:
            return {"error": "not found"}, 404
        return dict(row)
    finally:
        await db.close()


@router.get("/{run_id}/output")
async def get_task_run_output(run_id: str):
    return await db_output.list_by_run(run_id)


@router.get("/{run_id}/xcom")
async def get_run_xcom(run_id: str):
    """Get xcom values for a specific task run."""
    db = await get_db()
    try:
        entries = await db_xcom.get_all_for_run(db, run_id)
        return {"run_id": run_id, "xcom": entries}
    finally:
        await db.close()
