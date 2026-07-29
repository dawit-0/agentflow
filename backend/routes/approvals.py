"""Approval-gate endpoints: list pending approval requests and decide them.

Approve/reject go through the orchestrator (like retry/cancel) so the
decision is reflected immediately instead of waiting for the next poll
cycle, and so downstream cascade-cancel on rejection reuses the same
machinery as a normal run failure.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from database import get_db
from db import questions as db_questions
from models import ApprovalDecision

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("")
async def list_pending_approvals():
    db = await get_db()
    try:
        return await db_questions.list_pending(db)
    finally:
        await db.close()


@router.post("/{run_id}/approve")
async def approve_run(run_id: str, body: ApprovalDecision = None):
    from main import orchestrator
    result = await orchestrator.approve_run(run_id, comment=(body.comment if body else None))
    if result is None:
        return JSONResponse({"error": "no pending approval for this run"}, status_code=404)
    return result


@router.post("/{run_id}/reject")
async def reject_run(run_id: str, body: ApprovalDecision = None):
    from main import orchestrator
    result = await orchestrator.reject_run(run_id, comment=(body.comment if body else None))
    if result is None:
        return JSONResponse({"error": "no pending approval for this run"}, status_code=404)
    return result
