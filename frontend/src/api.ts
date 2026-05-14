const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return res.json();
}

export interface Permissions {
  preset: string;
  file_read: boolean;
  file_write: boolean;
  bash: boolean;
  web_search: boolean;
  mcp: boolean;
}

export const PERMISSION_PRESETS: Record<string, Permissions> = {
  "read-only": {
    preset: "read-only",
    file_read: true,
    file_write: false,
    bash: false,
    web_search: false,
    mcp: false,
  },
  standard: {
    preset: "standard",
    file_read: true,
    file_write: true,
    bash: true,
    web_search: false,
    mcp: false,
  },
  full: {
    preset: "full",
    file_read: true,
    file_write: true,
    bash: true,
    web_search: true,
    mcp: true,
  },
};

export interface Task {
  id: string;
  title: string;
  prompt: string;
  status: "active" | "paused";
  priority: number;
  model: string;
  work_dir: string;
  flow_id: string;
  agent_id: string | null;
  permissions: Permissions;
  schedule: string | null;
  schedule_enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
  latest_run?: TaskRun | null;
}

export interface TaskRun {
  id: string;
  task_id: string;
  run_number: number;
  trigger: "manual" | "schedule" | "dependency" | "retry";
  status: "queued" | "running" | "success" | "failed" | "cancelled";
  pid: number | null;
  exit_code: number | null;
  cost_usd: number;
  duration_ms: number;
  num_turns: number;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
  attempt_number: number;
  retry_of_run_id: string | null;
}

export interface TaskRunOutput {
  task_run_id: string;
  seq: number;
  type: string;
  content: string;
  timestamp: string;
}

export interface DagNode {
  id: string;
  title: string;
  status: string;
  model: string;
  schedule: string | null;
  max_retries: number;
  retry_delay_seconds: number;
  latest_run_status: string | null;
  latest_run_number: number | null;
  attempt_number: number | null;
  latest_run_trigger: string | null;
  created_at: string;
  updated_at: string;
}

export interface DagEdge {
  source: string;
  target: string;
  pass_output?: boolean;
}

export interface UpstreamContextItem {
  task_id: string;
  task_title: string;
  pass_output: boolean;
  max_output_chars: number;
  has_output: boolean;
  output_preview: string;
  output_length: number;
}

export interface DagGraph {
  nodes: DagNode[];
  edges: DagEdge[];
}

export interface Flow {
  id: string;
  name: string;
  description: string;
  schedule: string | null;
  schedule_enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
}

export interface ContextItem {
  type: "file" | "url" | "text";
  path?: string;
  url?: string;
  content?: string;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  instructions: string;
  context: ContextItem[];
  default_model: string;
  default_permissions: Permissions;
  default_work_dir: string;
  default_flow_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Model {
  value: string;
  label: string;
  provider: string;
}

export interface Settings {
  default_work_dir: string;
  max_concurrent_runs: number;
  theme: "dark" | "light";
  notify_on_task_failure: boolean;
  notify_on_task_success: boolean;
  notify_on_flow_completion: boolean;
  notify_desktop_enabled: boolean;
  notify_sound_enabled: boolean;
}

export interface AnalyticsSummary {
  since: string;
  total_runs: number;
  success_count: number;
  failed_count: number;
  cancelled_count: number;
  success_rate: number;
  total_cost_usd: number;
  avg_duration_ms: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
}

export interface DayBucket {
  date: string;
  total: number;
  success: number;
  failed: number;
  cost_usd: number;
}

export interface TopFailingTask {
  task_id: string;
  title: string;
  failure_count: number;
  last_failure_at: string | null;
}

export interface DurationBucket {
  bucket: string;
  count: number;
}

export interface RecentFailure {
  run_id: string;
  task_id: string;
  task_title: string;
  run_number: number;
  finished_at: string | null;
  duration_ms: number;
  error_message: string | null;
}

export type NotificationKind =
  | "task_failed"
  | "task_succeeded"
  | "flow_completed"
  | "flow_failed";

export interface AppNotification {
  id: string;
  kind: NotificationKind;
  severity: "info" | "warning" | "error";
  title: string;
  body: string | null;
  task_id: string | null;
  task_run_id: string | null;
  flow_id: string | null;
  read_at: string | null;
  created_at: string;
}

export interface DebugStatus {
  orchestrator: {
    running: boolean;
    active_runs: number;
    active_run_ids: string[];
    max_concurrent: number;
    poll_interval_seconds: number;
  };
  queued_runs: number;
  recent_failures: Array<{
    run_id: string;
    task_id: string;
    error_message: string | null;
    finished_at: string | null;
  }>;
  system: {
    python_version: string;
    uptime_seconds: number;
    db_size_bytes: number;
  };
}

export const api = {
  tasks: {
    list: (flowId?: string) =>
      request<Task[]>(`/tasks${flowId ? `?flow_id=${flowId}` : ""}`),
    get: (id: string) => request<Task>(`/tasks/${id}`),
    create: (data: {
      title: string;
      prompt: string;
      model?: string;
      priority?: number;
      work_dir?: string;
      flow_id?: string;
      permissions?: Permissions;
      schedule?: string;
      agent_id?: string;
      depends_on?: string[];
      pass_output?: boolean;
      max_output_chars?: number;
      max_retries?: number;
      retry_delay_seconds?: number;
    }) => request<Task>("/tasks", { method: "POST", body: JSON.stringify(data) }),
    update: (
      id: string,
      data: Partial<{
        title: string;
        prompt: string;
        status: string;
        priority: number;
        model: string;
        work_dir: string;
        flow_id: string;
        permissions: Permissions;
        schedule: string;
        schedule_enabled: boolean;
      }>
    ) =>
      request<Task>(`/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    trigger: (id: string) =>
      request<TaskRun>(`/tasks/${id}/trigger`, { method: "POST" }),
    cancel: (id: string) =>
      request<{ ok: boolean }>(`/tasks/${id}/cancel`, { method: "POST" }),
    retry: (id: string) =>
      request<{ id: string; task_id: string; run_number: number }>(
        `/tasks/${id}/retry`,
        { method: "POST" }
      ),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/tasks/${id}`, { method: "DELETE" }),
    runs: (id: string) => request<TaskRun[]>(`/tasks/${id}/runs`),
    dag: (flowId?: string) =>
      request<DagGraph>(`/tasks/dag${flowId ? `?flow_id=${flowId}` : ""}`),
    dependencies: (id: string) =>
      request<{ task_id: string; depends_on: string[] }>(`/tasks/${id}/dependencies`),
    addDependencies: (taskId: string, dependsOn: string[], passOutput = true, maxOutputChars = 4000) =>
      request<{ ok: boolean }>(`/tasks/${taskId}/dependencies`, {
        method: "POST",
        body: JSON.stringify({ depends_on: dependsOn, pass_output: passOutput, max_output_chars: maxOutputChars }),
      }),
    upstreamContext: (taskId: string) =>
      request<{ task_id: string; upstream_context: UpstreamContextItem[] }>(`/tasks/${taskId}/upstream-context`),
    xcom: (taskId: string) =>
      request<{ task_id: string; run_id?: string; xcom: Array<{ key: string; value: string }> }>(`/tasks/${taskId}/xcom`),
    removeDependency: (taskId: string, depId: string) =>
      request<{ ok: boolean }>(`/tasks/${taskId}/dependencies/${depId}`, {
        method: "DELETE",
      }),
    quickCreate: (data: {
      title: string;
      prompt: string;
      model?: string;
      work_dir?: string;
      permissions?: Permissions;
      schedule?: string;
      max_retries?: number;
      retry_delay_seconds?: number;
      trigger?: boolean;
    }) => request<Task>("/tasks/quick", { method: "POST", body: JSON.stringify(data) }),
  },
  taskRuns: {
    list: (taskId?: string) =>
      request<TaskRun[]>(`/task-runs${taskId ? `?task_id=${taskId}` : ""}`),
    get: (id: string) => request<TaskRun>(`/task-runs/${id}`),
    output: (id: string) => request<TaskRunOutput[]>(`/task-runs/${id}/output`),
    xcom: (id: string) => request<{ run_id: string; xcom: Array<{ key: string; value: string }> }>(`/task-runs/${id}/xcom`),
  },
  flows: {
    list: () => request<Flow[]>("/flows"),
    get: (id: string) => request<Flow>(`/flows/${id}`),
    create: (data: { name: string; description?: string; schedule?: string }) =>
      request<Flow>("/flows", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    update: (
      id: string,
      data: Partial<{
        name: string;
        description: string;
        schedule: string;
        schedule_enabled: boolean;
      }>
    ) =>
      request<Flow>(`/flows/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/flows/${id}`, { method: "DELETE" }),
    trigger: (id: string) =>
      request<{ triggered: number; runs: Array<{ id: string; task_id: string }> }>(
        `/flows/${id}/trigger`,
        { method: "POST" }
      ),
    retry: (id: string) =>
      request<{ retried: number; runs: Array<{ id: string; task_id: string }> }>(
        `/flows/${id}/retry`,
        { method: "POST" }
      ),
    resume: (id: string) =>
      request<{ retried: number; runs: Array<{ id: string; task_id: string }> }>(
        `/flows/${id}/resume`,
        { method: "POST" }
      ),
  },
  debug: {
    status: () => request<DebugStatus>("/debug/status"),
  },
  models: {
    list: () => request<Model[]>("/models"),
  },
  agents: {
    list: () => request<Agent[]>("/agents"),
    get: (id: string) => request<Agent>(`/agents/${id}`),
    create: (data: {
      name: string;
      description?: string;
      instructions?: string;
      context?: ContextItem[];
      default_model?: string;
      default_permissions?: Permissions;
      default_work_dir?: string;
      default_flow_id?: string;
    }) =>
      request<Agent>("/agents", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    update: (
      id: string,
      data: Partial<{
        name: string;
        description: string;
        instructions: string;
        context: ContextItem[];
        default_model: string;
        default_permissions: Permissions;
        default_work_dir: string;
        default_flow_id: string;
      }>
    ) =>
      request<Agent>(`/agents/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/agents/${id}`, { method: "DELETE" }),
    spawn: (
      id: string,
      data: {
        title: string;
        prompt?: string;
        model?: string;
        priority?: number;
        work_dir?: string;
        flow_id?: string;
        permissions?: Permissions;
        depends_on?: string[];
        trigger?: boolean;
      }
    ) =>
      request<Task>(`/agents/${id}/spawn`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
  },
  settings: {
    get: () => request<Settings>("/settings"),
    update: (data: Partial<Settings>) =>
      request<Settings>("/settings", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
  },
  analytics: {
    summary: (since?: string) =>
      request<AnalyticsSummary>(`/analytics/summary${since ? `?since=${encodeURIComponent(since)}` : ""}`),
    runsByDay: (since?: string) =>
      request<DayBucket[]>(`/analytics/runs_by_day${since ? `?since=${encodeURIComponent(since)}` : ""}`),
    topFailures: (since?: string, limit = 10) => {
      const qs = new URLSearchParams();
      if (since) qs.set("since", since);
      qs.set("limit", String(limit));
      return request<TopFailingTask[]>(`/analytics/top_failures?${qs}`);
    },
    durationHistogram: (since?: string) =>
      request<DurationBucket[]>(`/analytics/duration_histogram${since ? `?since=${encodeURIComponent(since)}` : ""}`),
    recentFailures: (limit = 20) =>
      request<RecentFailure[]>(`/analytics/recent_failures?limit=${limit}`),
  },
  notifications: {
    list: (unreadOnly = false, limit = 50) => {
      const qs = new URLSearchParams();
      if (unreadOnly) qs.set("unread_only", "true");
      qs.set("limit", String(limit));
      return request<AppNotification[]>(`/notifications?${qs}`);
    },
    unreadCount: () => request<{ unread_count: number }>("/notifications/unread_count"),
    markRead: (id: string) =>
      request<{ ok: boolean }>(`/notifications/${id}/read`, { method: "POST" }),
    markAllRead: () =>
      request<{ ok: boolean; marked: number }>("/notifications/read_all", { method: "POST" }),
  },
};
