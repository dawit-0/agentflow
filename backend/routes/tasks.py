import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from database import get_db
from db import tasks as db_tasks, task_runs as db_task_runs, flows as db_flows
from db import task_dependencies as db_deps, task_run_output as db_output
from db import questions as db_questions, task_xcom as db_xcom
from db import flow_runs as db_flow_runs
from models import TaskCreate, TaskUpdate, TaskTrigger, DependencyAdd, QuickTaskCreate, DEFAULT_PERMISSIONS
import cron as cron_parser

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _parse_task_row(row):
    task = dict(row)
    try:
        task["permissions"] = json.loads(task.get("permissions") or "{}")
    except (json.JSONDecodeError, TypeError):
        task["permissions"] = DEFAULT_PERMISSIONS
    try:
        task["secret_keys"] = json.loads(task.get("secret_keys") or "[]")
    except (json.JSONDecodeError, TypeError):
        task["secret_keys"] = []
    return task


@router.get("")
async def list_tasks(flow_id: str = None, status: str = None):
    db = await get_db()
    try:
        rows = await db_tasks.list_all(db, flow_id=flow_id, status=status)
        return [_parse_task_row(r) for r in rows]
    finally:
        await db.close()


# DAG endpoint — must be before /{task_id} to avoid path conflict
@router.get("/dag")
async def get_dag(flow_id: str = None):
    db = await get_db()
    try:
        nodes = await db_tasks.get_dag_nodes(db, flow_id=flow_id)
        node_ids = {n["id"] for n in nodes}

        if node_ids:
            edges = await db_deps.get_edges_for_nodes(db, node_ids)
        else:
            edges = []

        return {"nodes": nodes, "edges": edges}
    finally:
        await db.close()


@router.post("/quick")
async def quick_create_task(body: QuickTaskCreate):
    """Create a single-task flow in one step."""
    flow_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    permissions = body.permissions if body.permissions else DEFAULT_PERMISSIONS
    permissions_json = json.dumps(permissions)
    db = await get_db()
    try:
        await db_flows.insert(db, flow_id, body.title)

        # Compute next_run_at if schedule provided
        next_run_at = None
        if body.schedule:
            now = datetime.now(timezone.utc)
            next_run = cron_parser.next_run_after(body.schedule, now)
            next_run_at = next_run.strftime("%Y-%m-%dT%H:%M:%SZ")

        await db_tasks.insert_quick(db, task_id, body.title, body.prompt,
                                     body.model, body.work_dir, flow_id,
                                     permissions_json, body.schedule, next_run_at,
                                     body.max_retries, body.retry_delay_seconds,
                                     sandbox=body.sandbox or "",
                                     secret_keys_json=json.dumps(body.secret_keys or []))

        # Trigger immediately if requested
        if body.trigger and not body.schedule:
            run_id = str(uuid.uuid4())
            flow_run = await db_flow_runs.create_partial(db, flow_id)
            await db_task_runs.insert(db, run_id, task_id, 1, trigger="manual",
                                      flow_run_id=flow_run["id"])

        await db.commit()
        row = await db_tasks.get_by_id(db, task_id)
        return _parse_task_row(row)
    finally:
        await db.close()


@router.get("/{task_id}")
async def get_task(task_id: str):
    db = await get_db()
    try:
        row = await db_tasks.get_by_id(db, task_id)
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        task = _parse_task_row(row)

        # Include latest run info
        latest_run = await db_task_runs.get_latest(db, task_id)
        task["latest_run"] = dict(latest_run) if latest_run else None

        return task
    finally:
        await db.close()


async def _check_circular_dependency(db, task_id: str, upstream_ids: list[str]) -> bool:
    visited = {task_id}
    queue = list(upstream_ids)
    while queue:
        current = queue.pop(0)
        if current in visited:
            return True
        visited.add(current)
        dep_ids = await db_deps.get_upstream(db, current)
        queue.extend(dep_ids)
    return False


@router.post("")
async def create_task(body: TaskCreate):
    task_id = str(uuid.uuid4())
    permissions = body.permissions if body.permissions else DEFAULT_PERMISSIONS
    permissions_json = json.dumps(permissions)
    db = await get_db()
    try:
        # Auto-create a flow if none provided
        flow_id = body.flow_id
        if not flow_id:
            flow_id = str(uuid.uuid4())
            await db_flows.insert(db, flow_id, body.title)

        depends_on = list(body.depends_on or [])

        if depends_on:
            if task_id in depends_on:
                return JSONResponse({"error": "task cannot depend on itself"}, status_code=400)
            for dep_id in depends_on:
                if not await db_tasks.exists(db, dep_id):
                    return JSONResponse({"error": f"dependency task {dep_id} not found"}, status_code=404)
            if await _check_circular_dependency(db, task_id, depends_on):
                return JSONResponse({"error": "circular dependency detected"}, status_code=400)

        # Compute next_run_at if schedule provided
        next_run_at = None
        if body.schedule:
            now = datetime.now(timezone.utc)
            next_run = cron_parser.next_run_after(body.schedule, now)
            next_run_at = next_run.strftime("%Y-%m-%dT%H:%M:%SZ")

        await db_tasks.insert(db, task_id, body.title, body.prompt, body.model,
                               body.priority, body.work_dir, flow_id, body.agent_id,
                               permissions_json, body.schedule, next_run_at,
                               body.max_retries, body.retry_delay_seconds,
                               sandbox=body.sandbox or "",
                               secret_keys_json=json.dumps(body.secret_keys or []))

        for dep_id in depends_on:
            if dep_id != task_id:
                await db_deps.insert_with_config(db, task_id, dep_id,
                                                  pass_output=body.pass_output,
                                                  max_output_chars=body.max_output_chars)

        # Trigger immediately if requested and no schedule
        if body.trigger and not body.schedule:
            run_id = str(uuid.uuid4())
            flow_run = await db_flow_runs.create_partial(db, flow_id)
            await db_task_runs.insert(db, run_id, task_id, 1, trigger="manual",
                                      flow_run_id=flow_run["id"])

        await db.commit()
        row = await db_tasks.get_by_id(db, task_id)
        return _parse_task_row(row)
    finally:
        await db.close()


@router.patch("/{task_id}")
async def update_task(task_id: str, body: TaskUpdate):
    db = await get_db()
    try:
        updates = []
        params = []
        data = body.model_dump(exclude_none=True)

        # Handle schedule_enabled as integer
        if "schedule_enabled" in data:
            data["schedule_enabled"] = 1 if data["schedule_enabled"] else 0

        # Handle permissions as JSON
        if "permissions" in data:
            data["permissions"] = json.dumps(data["permissions"])

        # Handle secret_keys as JSON
        if "secret_keys" in data:
            data["secret_keys"] = json.dumps(data["secret_keys"])

        for field, value in data.items():
            updates.append(f"{field} = ?")
            params.append(value)

        if not updates:
            return JSONResponse({"error": "no fields to update"}, status_code=400)

        # Recompute next_run_at if schedule changed
        if "schedule" in data and data["schedule"]:
            now = datetime.now(timezone.utc)
            next_run = cron_parser.next_run_after(data["schedule"], now)
            updates.append("next_run_at = ?")
            params.append(next_run.strftime("%Y-%m-%dT%H:%M:%SZ"))

        updates.append("updated_at = datetime('now')")
        await db_tasks.update_fields(db, task_id, updates, params)
        await db.commit()
        row = await db_tasks.get_by_id(db, task_id)
        return _parse_task_row(row)
    finally:
        await db.close()


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    db = await get_db()
    try:
        await db_deps.delete_for_task(db, task_id)
        await db_output.delete_by_task(db, task_id)
        await db_xcom.delete_by_task(db, task_id)
        await db_questions.delete_by_task(db, task_id)
        await db_task_runs.delete_by_task(db, task_id)
        await db_tasks.delete(db, task_id)
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/{task_id}/trigger")
async def trigger_task(task_id: str, body: TaskTrigger = None):
    db = await get_db()
    try:
        row = await db_tasks.get_by_id(db, task_id)
        if not row:
            return JSONResponse({"error": "task not found"}, status_code=404)

        run_number = await db_task_runs.next_run_number(db, task_id)
        run_id = str(uuid.uuid4())

        # A single-task trigger is a mid-graph execution: its own partial flow run
        flow_run = await db_flow_runs.create_partial(db, dict(row)["flow_id"])
        await db_task_runs.insert(db, run_id, task_id, run_number, trigger="manual",
                                  flow_run_id=flow_run["id"])
        await db.commit()

        run = await db_task_runs.get_by_id(db, run_id)
        return dict(run)
    finally:
        await db.close()


@router.post("/{task_id}/retry")
async def retry_task(task_id: str):
    """Retry the latest failed run for this task."""
    from main import orchestrator
    result = await orchestrator.retry_task_run(task_id)
    return result


@router.get("/{task_id}/runs")
async def list_task_runs(task_id: str):
    db = await get_db()
    try:
        rows = await db_task_runs.list_by_task(db, task_id)
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.get("/{task_id}/dependencies")
async def get_task_dependencies(task_id: str):
    db = await get_db()
    try:
        dep_ids = await db_deps.get_upstream(db, task_id)
        return {"task_id": task_id, "depends_on": dep_ids}
    finally:
        await db.close()


@router.post("/{task_id}/dependencies")
async def add_task_dependencies(task_id: str, body: DependencyAdd):
    db = await get_db()
    try:
        if not await db_tasks.exists(db, task_id):
            return JSONResponse({"error": "task not found"}, status_code=404)

        for dep_id in body.depends_on:
            if dep_id == task_id:
                return JSONResponse({"error": "task cannot depend on itself"}, status_code=400)
            if not await db_tasks.exists(db, dep_id):
                return JSONResponse({"error": f"dependency task {dep_id} not found"}, status_code=404)

        if await _check_circular_dependency(db, task_id, body.depends_on):
            return JSONResponse({"error": "circular dependency detected"}, status_code=400)

        for dep_id in body.depends_on:
            await db_deps.insert_with_config(db, task_id, dep_id,
                                              pass_output=body.pass_output,
                                              max_output_chars=body.max_output_chars)
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{task_id}/dependencies/{dep_id}")
async def remove_task_dependency(task_id: str, dep_id: str):
    db = await get_db()
    try:
        await db_deps.delete_one(db, task_id, dep_id)
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.get("/{task_id}/upstream-context")
async def get_upstream_context(task_id: str):
    """Preview what upstream context would be injected for this task."""
    db = await get_db()
    try:
        upstream_deps = await db_deps.get_upstream_with_config(db, task_id)
        sections = []
        for dep in upstream_deps:
            upstream_task_id = dep["depends_on_task_id"]
            pass_output = dep.get("pass_output", 1)
            max_chars = dep.get("max_output_chars", 4000)

            upstream_task = await db_tasks.get_by_id(db, upstream_task_id)
            task_title = dict(upstream_task)["title"] if upstream_task else upstream_task_id[:8]

            latest_run = await db_task_runs.get_latest_successful(db, upstream_task_id)
            result_text = ""
            if latest_run and pass_output:
                result_text = await db_output.get_result_text(latest_run["id"], max_chars)

            sections.append({
                "task_id": upstream_task_id,
                "task_title": task_title,
                "pass_output": bool(pass_output),
                "max_output_chars": max_chars,
                "has_output": bool(result_text.strip()),
                "output_preview": result_text[:500] if result_text else "",
                "output_length": len(result_text),
            })
        return {"task_id": task_id, "upstream_context": sections}
    finally:
        await db.close()


@router.get("/{task_id}/xcom")
async def get_task_xcom(task_id: str):
    """Get xcom values for the latest run of a task."""
    db = await get_db()
    try:
        latest_run = await db_task_runs.get_latest_successful(db, task_id)
        if not latest_run:
            return {"task_id": task_id, "xcom": []}
        xcom_entries = await db_xcom.get_all_for_run(db, latest_run["id"])
        return {"task_id": task_id, "run_id": latest_run["id"], "xcom": xcom_entries}
    finally:
        await db.close()
