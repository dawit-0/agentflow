from fastapi import APIRouter
from fastapi.responses import JSONResponse
from database import get_db
from db import task_runs as db_task_runs, task_run_output as db_output
from db import task_xcom as db_xcom, questions as db_questions
from models import ApprovalAnswer

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
async def get_task_run_output(
    run_id: str,
    after_seq: int | None = None,
    tail: int | None = None,
):
    """Return output entries for a run.

    Without query params, returns the full event list as a JSON array
    (back-compat with older clients). With ``after_seq`` or ``tail``, returns
    ``{"rows": [...], "last_seq": <int>}`` so the client can paginate
    backwards or fetch only new entries during a live tail.
    """
    if after_seq is None and tail is None:
        return await db_output.list_by_run(run_id)
    return await db_output.list_by_run_paginated(
        run_id, after_seq=after_seq, tail=tail
    )


@router.get("/{run_id}/xcom")
async def get_run_xcom(run_id: str):
    """Get xcom values for a specific task run."""
    db = await get_db()
    try:
        entries = await db_xcom.get_all_for_run(db, run_id)
        return {"run_id": run_id, "xcom": entries}
    finally:
        await db.close()


@router.get("/{run_id}/question")
async def get_run_question(run_id: str):
    """Get the latest approval-gate question for a run, if any."""
    db = await get_db()
    try:
        row = await db_questions.get_latest_for_run(db, run_id)
        return {"run_id": run_id, "question": dict(row) if row else None}
    finally:
        await db.close()


@router.post("/{run_id}/answer")
async def answer_run(run_id: str, body: ApprovalAnswer):
    """Resolve a paused approval-gate run with a human decision."""
    if body.decision not in ("approve", "reject"):
        return JSONResponse({"error": "decision must be 'approve' or 'reject'"}, status_code=400)

    from main import orchestrator
    try:
        return await orchestrator.answer_approval(run_id, body.decision, body.note)
    except LookupError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
