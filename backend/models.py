from pydantic import BaseModel
from typing import Optional


PERMISSION_PRESETS = {
    "read-only": {
        "preset": "read-only",
        "file_read": True,
        "file_write": False,
        "bash": False,
        "web_search": False,
        "mcp": False,
    },
    "standard": {
        "preset": "standard",
        "file_read": True,
        "file_write": True,
        "bash": True,
        "web_search": False,
        "mcp": False,
    },
    "full": {
        "preset": "full",
        "file_read": True,
        "file_write": True,
        "bash": True,
        "web_search": True,
        "mcp": True,
    },
}

DEFAULT_PERMISSIONS = PERMISSION_PRESETS["standard"]


class TaskCreate(BaseModel):
    title: str
    prompt: str
    model: str = "claude-sonnet-4-20250514"
    priority: int = 0
    work_dir: str = ""
    flow_id: Optional[str] = None
    permissions: Optional[dict] = None
    schedule: Optional[str] = None
    agent_id: Optional[str] = None
    depends_on: Optional[list[str]] = None
    pass_output: bool = True
    max_output_chars: int = 4000
    max_retries: int = 0
    retry_delay_seconds: int = 10
    trigger: bool = False
    sandbox: Optional[str] = None
    secrets: Optional[list[str]] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    prompt: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    model: Optional[str] = None
    work_dir: Optional[str] = None
    flow_id: Optional[str] = None
    permissions: Optional[dict] = None
    schedule: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    max_retries: Optional[int] = None
    retry_delay_seconds: Optional[int] = None
    sandbox: Optional[str] = None
    secrets: Optional[list[str]] = None


class TaskTrigger(BaseModel):
    prompt_override: Optional[str] = None


class DependencyConfig(BaseModel):
    task_id: str
    pass_output: bool = True
    max_output_chars: int = 4000


class DependencyAdd(BaseModel):
    depends_on: list[str]
    pass_output: bool = True
    max_output_chars: int = 4000


class FlowCreate(BaseModel):
    name: str
    description: str = ""
    schedule: Optional[str] = None


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schedule: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    max_active_runs: Optional[int] = None


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    instructions: str = ""
    context: list[dict] = []
    default_model: str = "claude-sonnet-4-20250514"
    default_permissions: Optional[dict] = None
    default_work_dir: str = ""
    default_flow_id: Optional[str] = None
    default_sandbox: Optional[str] = None
    default_secrets: Optional[list[str]] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    context: Optional[list[dict]] = None
    default_model: Optional[str] = None
    default_permissions: Optional[dict] = None
    default_work_dir: Optional[str] = None
    default_flow_id: Optional[str] = None
    default_sandbox: Optional[str] = None
    default_secrets: Optional[list[str]] = None


class SpawnTask(BaseModel):
    title: str
    prompt: str = ""
    model: Optional[str] = None
    priority: int = 0
    work_dir: Optional[str] = None
    flow_id: Optional[str] = None
    permissions: Optional[dict] = None
    depends_on: Optional[list[str]] = None
    trigger: bool = True  # whether to immediately trigger a run
    sandbox: Optional[str] = None
    secrets: Optional[list[str]] = None


class QuickTaskCreate(BaseModel):
    title: str
    prompt: str
    model: str = "claude-sonnet-4-20250514"
    work_dir: str = ""
    permissions: Optional[dict] = None
    schedule: Optional[str] = None
    max_retries: int = 0
    retry_delay_seconds: int = 10
    trigger: bool = True
    sandbox: Optional[str] = None
    secrets: Optional[list[str]] = None


class AnswerCreate(BaseModel):
    answer: str


class SecretCreate(BaseModel):
    name: str
    value: str
    description: str = ""


class SecretUpdate(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None
