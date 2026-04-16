import asyncio
import time
from contextlib import asynccontextmanager

import socketio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger("server")

from database import init_db, get_db
from orchestrator import Orchestrator
from routes.tasks import router as tasks_router
from routes.task_runs import router as task_runs_router
from routes.flows import router as flows_router
from routes.agents import router as agents_router
from routes.debug import router as debug_router
from routes.models import router as models_router
from routes.settings import router as settings_router
from routes.analytics import router as analytics_router
from routes.notifications import router as notifications_router

# Socket.IO
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

orchestrator = Orchestrator(sio)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    from db import settings as db_settings

    await init_db()

    # Load max_concurrent_runs from saved settings
    db = await get_db()
    try:
        val = await db_settings.get(db, "max_concurrent_runs")
        if val is not None:
            try:
                orchestrator.update_max_concurrent(int(val))
            except (ValueError, TypeError):
                pass
    finally:
        await db.close()

    await orchestrator.start()
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set — OpenAI/Codex models will not work until it is configured")
    yield
    await orchestrator.stop()


# FastAPI
app = FastAPI(title="AgentFlow", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(task_runs_router)
app.include_router(flows_router)
app.include_router(agents_router)
app.include_router(debug_router)
app.include_router(models_router)
app.include_router(settings_router)
app.include_router(analytics_router)
app.include_router(notifications_router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    if request.url.path.startswith("/socket.io"):
        return await call_next(request)
    start = time.time()
    response = await call_next(request)
    ms = int((time.time() - start) * 1000)
    level = "WARNING" if response.status_code >= 400 else "INFO"
    getattr(logger, level.lower())(
        "%s %s -> %s (%dms)", request.method, request.url.path, response.status_code, ms
    )
    return response


# Cancel task run endpoint that needs orchestrator
@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    await orchestrator.cancel_task_run(task_id)
    return {"ok": True}


# Socket.IO events
@sio.event
async def connect(sid, environ):
    logger.info("client connected: %s", sid)


@sio.event
async def disconnect(sid):
    logger.info("client disconnected: %s", sid)


# Mount Socket.IO
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# Serve frontend static files in production
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(socket_app, host="0.0.0.0", port=3000)
