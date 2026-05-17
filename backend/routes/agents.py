import json
import uuid
from fastapi import APIRouter
from database import get_db
from db import agents as db_agents, flows as db_flows, tasks as db_tasks
from db import task_runs as db_task_runs, task_dependencies as db_deps
from models import AgentCreate, AgentUpdate, SpawnTask, DEFAULT_PERMISSIONS

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _parse_agent_row(row):
    agent = dict(row)
    try:
        agent["context"] = json.loads(agent.get("context") or "[]")
    except (json.JSONDecodeError, TypeError):
        agent["context"] = []
    try:
        agent["default_permissions"] = json.loads(agent.get("default_permissions") or "{}")
    except (json.JSONDecodeError, TypeError):
        agent["default_permissions"] = {}
    return agent


def _format_context(context: list[dict]) -> str:
    parts = []
    for item in context:
        t = item.get("type", "")
        if t == "file":
            parts.append(f"[File: {item.get('path', '')}]")
        elif t == "url":
            parts.append(f"[Reference: {item.get('url', '')}]")
        elif t == "text":
            parts.append(item.get("content", ""))
    return "\n\n".join(parts)


@router.get("")
async def list_agents():
    db = await get_db()
    try:
        rows = await db_agents.list_all(db)
        return [_parse_agent_row(r) for r in rows]
    finally:
        await db.close()


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    db = await get_db()
    try:
        row = await db_agents.get_by_id(db, agent_id)
        if not row:
            return {"error": "not found"}, 404
        return _parse_agent_row(row)
    finally:
        await db.close()


@router.post("")
async def create_agent(body: AgentCreate):
    agent_id = str(uuid.uuid4())
    permissions = body.default_permissions if body.default_permissions else {}
    db = await get_db()
    try:
        await db_agents.insert(
            db, agent_id, body.name, body.description, body.instructions,
            json.dumps(body.context), body.default_model,
            json.dumps(permissions), body.default_work_dir, body.default_flow_id,
            default_sandbox=body.default_sandbox or "",
        )
        await db.commit()
        row = await db_agents.get_by_id(db, agent_id)
        return _parse_agent_row(row)
    finally:
        await db.close()


@router.patch("/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate):
    db = await get_db()
    try:
        updates = []
        params = []
        for field, value in body.model_dump(exclude_none=True).items():
            updates.append(f"{field} = ?")
            if field in ("context", "default_permissions"):
                params.append(json.dumps(value))
            else:
                params.append(value)
        if not updates:
            return {"error": "no fields to update"}
        await db_agents.update_fields(db, agent_id, updates, params)
        await db.commit()
        row = await db_agents.get_by_id(db, agent_id)
        return _parse_agent_row(row)
    finally:
        await db.close()


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    db = await get_db()
    try:
        await db_agents.delete(db, agent_id)
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/{agent_id}/spawn")
async def spawn_task(agent_id: str, body: SpawnTask):
    db = await get_db()
    try:
        row = await db_agents.get_by_id(db, agent_id)
        if not row:
            return {"error": "agent not found"}, 404
        agent = _parse_agent_row(row)

        # Build merged prompt
        parts = []
        if agent["instructions"]:
            parts.append(agent["instructions"])
        context_text = _format_context(agent["context"])
        if context_text:
            parts.append("--- Context ---\n" + context_text)
        if body.prompt:
            parts.append("--- Task ---\n" + body.prompt)
        merged_prompt = "\n\n".join(parts)

        # Use agent defaults, let user overrides take precedence
        model = body.model or agent["default_model"]
        permissions = body.permissions if body.permissions else (agent["default_permissions"] or DEFAULT_PERMISSIONS)
        work_dir = body.work_dir if body.work_dir is not None else agent["default_work_dir"]
        flow_id = body.flow_id if body.flow_id is not None else agent["default_flow_id"]
        sandbox = body.sandbox if body.sandbox is not None else (agent.get("default_sandbox") or "")

        # Auto-create a flow if none provided
        if not flow_id:
            flow_id = str(uuid.uuid4())
            await db_flows.insert(db, flow_id, body.title)

        task_id = str(uuid.uuid4())
        permissions_json = json.dumps(permissions)

        await db_tasks.insert_spawned(db, task_id, body.title, merged_prompt,
                                       model, body.priority, work_dir, flow_id,
                                       permissions_json, agent_id,
                                       sandbox=sandbox)

        # Insert dependency rows
        depends_on = list(body.depends_on or [])
        for dep_id in depends_on:
            if dep_id != task_id:
                await db_deps.insert(db, task_id, dep_id)

        # Optionally trigger a run immediately
        run = None
        if body.trigger:
            run_id = str(uuid.uuid4())
            await db_task_runs.insert(db, run_id, task_id, 1, trigger="manual")
            run = {"id": run_id, "task_id": task_id, "run_number": 1}

        await db.commit()
        task_row = await db_tasks.get_by_id(db, task_id)
        task_result = dict(task_row)
        try:
            task_result["permissions"] = json.loads(task_result.get("permissions") or "{}")
        except (json.JSONDecodeError, TypeError):
            task_result["permissions"] = DEFAULT_PERMISSIONS
        if run:
            task_result["triggered_run"] = run
        return task_result
    finally:
        await db.close()
