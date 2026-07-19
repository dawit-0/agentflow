from fastapi import APIRouter
from fastapi.responses import JSONResponse

import database
from db import flow_runs as db_flow_runs

router = APIRouter(prefix="/api/flow-runs", tags=["flow-runs"])


@router.get("/{flow_run_id}")
async def get_flow_run(flow_run_id: str):
    """One flow run with its member task runs."""
    db = await database.get_db()
    try:
        flow_run = await db_flow_runs.get_by_id(db, flow_run_id)
        if not flow_run:
            return JSONResponse({"error": "not found"}, status_code=404)
        flow_run["task_runs"] = await db_flow_runs.get_task_runs(db, flow_run_id)
        return flow_run
    finally:
        await db.close()


@router.post("/{flow_run_id}/cancel")
async def cancel_flow_run(flow_run_id: str):
    from main import orchestrator
    ok = await orchestrator.cancel_flow_run(flow_run_id)
    if not ok:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True}
