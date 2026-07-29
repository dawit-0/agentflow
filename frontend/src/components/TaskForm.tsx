import React, { useState, useEffect } from "react";
import { api, Task, Flow, Model, Permissions, PERMISSION_PRESETS } from "../api";
import { TaskPrefill } from "../App";

interface Props {
  flows: Flow[];
  tasks: Task[];
  selectedFlow: string | null;
  onClose: () => void;
  onCreated: () => void;
  prefill?: Partial<TaskPrefill> | null;
}

const FALLBACK_MODELS: Model[] = [
  { value: "claude-sonnet-4-20250514", label: "Claude Sonnet", provider: "claude" },
  { value: "claude-opus-4-20250514", label: "Claude Opus", provider: "claude" },
  { value: "claude-haiku-3-5-20241022", label: "Claude Haiku", provider: "claude" },
];

const CRON_PRESETS = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Daily at 9am", value: "0 9 * * *" },
  { label: "Weekdays at 9am", value: "0 9 * * 1-5" },
  { label: "Weekly (Mon)", value: "0 9 * * 1" },
  { label: "Monthly (1st)", value: "0 9 1 * *" },
];

function describeCron(expr: string): string {
  const match = CRON_PRESETS.find((p) => p.value === expr);
  if (match) return match.label;
  return expr;
}

export default function TaskForm({ flows, tasks, selectedFlow, onClose, onCreated, prefill }: Props) {
  const [models, setModels] = useState<Model[]>(FALLBACK_MODELS);
  const [title, setTitle] = useState(prefill?.title || "");
  const [prompt, setPrompt] = useState(prefill?.prompt || "");
  const [model, setModel] = useState(prefill?.model || FALLBACK_MODELS[0].value);

  useEffect(() => {
    api.models.list().then(setModels).catch(() => {});
  }, []);
  const [workDir, setWorkDir] = useState(prefill?.workDir || "");
  const [permissions, setPermissions] = useState<Permissions>(
    prefill?.permissions?.preset ? prefill.permissions : PERMISSION_PRESETS["standard"]
  );
  const [showPermDetails, setShowPermDetails] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Dependency state (multi-select)
  const [dependsOn, setDependsOn] = useState<string[]>([]);
  const [passOutput, setPassOutput] = useState(true);
  const [maxOutputChars, setMaxOutputChars] = useState(4000);

  // Schedule state
  const [hasSchedule, setHasSchedule] = useState(false);
  const [cronExpression, setCronExpression] = useState(CRON_PRESETS[1].value);

  // Retry config
  const [maxRetries, setMaxRetries] = useState(0);
  const [retryDelay, setRetryDelay] = useState(10);

  // Sandbox: "inherit" (use settings default), "" (force host), or "docker"
  const [sandbox, setSandbox] = useState<"inherit" | "" | "docker">("inherit");

  // Require a human to approve each run before it executes
  const [requiresApproval, setRequiresApproval] = useState(false);

  // Whether to trigger immediately
  const [triggerNow, setTriggerNow] = useState(true);

  const isSpawn = !!prefill?.agentId;
  const isQuickTask = prefill?.flowId === "__new__";

  // Determine the flow: either from selectedFlow (adding task to flow) or auto-create for quick task
  const resolvedFlowId = selectedFlow || prefill?.flowId || "";
  const isNewFlow = resolvedFlowId === "__new__" || !resolvedFlowId;

  // Show the flow name for context
  const flowData = flows.find((f) => f.id === resolvedFlowId);

  // Filter tasks to only show those in the selected flow (for dependencies)
  const flowTasks = isNewFlow ? [] : tasks.filter((t) => t.flow_id === resolvedFlowId);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim() || !title.trim()) return;
    setSubmitting(true);
    try {
      let finalFlowId = resolvedFlowId;

      // Auto-create flow for quick tasks
      if (isNewFlow) {
        const flowName = title.trim();
        const newFlow = await api.flows.create({ name: flowName });
        finalFlowId = newFlow.id;
      }

      const sandboxValue = sandbox === "inherit" ? undefined : sandbox;

      if (isSpawn && prefill?.agentId) {
        await api.agents.spawn(prefill.agentId, {
          title: title.trim(),
          prompt: prompt.trim(),
          model,
          work_dir: workDir.trim(),
          flow_id: finalFlowId,
          permissions,
          depends_on: dependsOn.length > 0 ? dependsOn : undefined,
          trigger: triggerNow,
          sandbox: sandboxValue,
        });
      } else {
        const task = await api.tasks.create({
          title: title.trim(),
          prompt: prompt.trim(),
          model,
          work_dir: workDir.trim(),
          flow_id: finalFlowId,
          permissions,
          schedule: hasSchedule ? cronExpression : undefined,
          depends_on: dependsOn.length > 0 ? dependsOn : undefined,
          pass_output: dependsOn.length > 0 ? passOutput : undefined,
          max_output_chars: dependsOn.length > 0 && passOutput ? maxOutputChars : undefined,
          max_retries: maxRetries > 0 ? maxRetries : undefined,
          retry_delay_seconds: maxRetries > 0 ? retryDelay : undefined,
          sandbox: sandboxValue,
          requires_approval: requiresApproval,
        } as Parameters<typeof api.tasks.create>[0]);

        // Trigger immediately if requested and no schedule
        if (triggerNow && !hasSchedule) {
          await api.tasks.trigger(task.id);
        }
      }
      onCreated();
      onClose();
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  }

  function getSubmitLabel() {
    if (submitting) return "Creating...";
    if (isSpawn) return triggerNow ? "Spawn & Run" : "Spawn Task";
    if (hasSchedule) return "Create Scheduled Task";
    return triggerNow ? "Create & Run" : "Create Task";
  }

  const isValid = prompt.trim() && title.trim();

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{isSpawn ? "Spawn Task from Agent" : isQuickTask ? "Quick Task" : "New Task"}</h2>

        {/* Show flow context */}
        {flowData && (
          <div className="task-form-flow-badge">
            Flow: <strong>{flowData.name}</strong>
          </div>
        )}
        {isQuickTask && (
          <div className="task-form-flow-badge">
            A new flow will be created automatically for this task.
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Title</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Brief description of the task"
              autoFocus
            />
          </div>

          <div className="form-group">
            <label>Prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={isSpawn ? "Describe the specific task..." : "Detailed instructions for the agent..."}
            />
          </div>

          <div className="form-group">
            <label>Schedule (optional)</label>
            <div className="schedule-toggle">
              <label className="permission-toggle">
                <input
                  type="checkbox"
                  checked={hasSchedule}
                  onChange={(e) => setHasSchedule(e.target.checked)}
                />
                <span>Run on a recurring schedule</span>
              </label>
            </div>

            {hasSchedule && (
              <div className="schedule-config">
                <div className="cron-presets">
                  {CRON_PRESETS.map((p) => (
                    <button
                      key={p.value}
                      type="button"
                      className={`btn btn-sm${cronExpression === p.value ? " active" : ""}`}
                      onClick={() => setCronExpression(p.value)}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
                <input
                  value={cronExpression}
                  onChange={(e) => setCronExpression(e.target.value)}
                  placeholder="* * * * * (min hour dom mon dow)"
                  className="cron-input"
                />
                <p className="field-hint">Schedule: {describeCron(cronExpression)}</p>
              </div>
            )}
          </div>

          <div className="form-group">
            <label>Auto-Retry on Failure (optional)</label>
            <div className="retry-config">
              <div className="retry-config-row">
                <label className="retry-config-label">Max retries</label>
                <select
                  value={maxRetries}
                  onChange={(e) => setMaxRetries(Number(e.target.value))}
                  className="retry-select"
                >
                  <option value={0}>None</option>
                  <option value={1}>1</option>
                  <option value={2}>2</option>
                  <option value={3}>3</option>
                  <option value={5}>5</option>
                </select>
              </div>
              {maxRetries > 0 && (
                <div className="retry-config-row">
                  <label className="retry-config-label">Delay between retries</label>
                  <select
                    value={retryDelay}
                    onChange={(e) => setRetryDelay(Number(e.target.value))}
                    className="retry-select"
                  >
                    <option value={5}>5 seconds</option>
                    <option value={10}>10 seconds</option>
                    <option value={30}>30 seconds</option>
                    <option value={60}>1 minute</option>
                    <option value={300}>5 minutes</option>
                  </select>
                </div>
              )}
            </div>
            {maxRetries > 0 && (
              <p className="field-hint">
                If this task fails, it will automatically retry up to {maxRetries} time{maxRetries > 1 ? "s" : ""} with a {retryDelay}s delay.
              </p>
            )}
          </div>

          {!hasSchedule && (
            <div className="form-group">
              <label className="permission-toggle">
                <input
                  type="checkbox"
                  checked={triggerNow}
                  onChange={(e) => setTriggerNow(e.target.checked)}
                />
                <span>Trigger immediately after creation</span>
              </label>
            </div>
          )}

          <div className="form-group">
            <label>Model</label>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {Object.entries(
                models.reduce<Record<string, Model[]>>((groups, m) => {
                  (groups[m.provider] ??= []).push(m);
                  return groups;
                }, {})
              ).map(([provider, group]) => (
                <optgroup key={provider} label={provider === "claude" ? "Anthropic" : "OpenAI"}>
                  {group.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>Working Directory (optional)</label>
            <input
              value={workDir}
              onChange={(e) => setWorkDir(e.target.value)}
              placeholder="/path/to/project"
            />
          </div>

          {flowTasks.length > 0 && (
            <div className="form-group">
              <label>Depends On (optional)</label>
              <div className="depends-on-list">
                {flowTasks.map((t) => (
                  <label key={t.id} className="permission-toggle">
                    <input
                      type="checkbox"
                      checked={dependsOn.includes(t.id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setDependsOn([...dependsOn, t.id]);
                        } else {
                          setDependsOn(dependsOn.filter((id) => id !== t.id));
                        }
                      }}
                    />
                    <span>{t.title}</span>
                  </label>
                ))}
              </div>
              {dependsOn.length > 0 && (
                <>
                  <p className="field-hint">This task will wait for all selected tasks to succeed before running.</p>
                  <div className="data-passing-config">
                    <label className="permission-toggle">
                      <input
                        type="checkbox"
                        checked={passOutput}
                        onChange={(e) => setPassOutput(e.target.checked)}
                      />
                      <span>Pass upstream output as context</span>
                    </label>
                    {passOutput && (
                      <div className="retry-config-row" style={{ marginTop: 6 }}>
                        <label className="retry-config-label">Max context chars per task</label>
                        <select
                          value={maxOutputChars}
                          onChange={(e) => setMaxOutputChars(Number(e.target.value))}
                          className="retry-select"
                        >
                          <option value={1000}>1,000</option>
                          <option value={2000}>2,000</option>
                          <option value={4000}>4,000</option>
                          <option value={8000}>8,000</option>
                          <option value={16000}>16,000</option>
                        </select>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          <div className="form-group">
            <label>Permissions</label>
            <div className="permission-presets">
              {Object.entries(PERMISSION_PRESETS).map(([key, preset]) => (
                <button
                  key={key}
                  type="button"
                  className={`btn btn-sm permission-preset-btn${
                    permissions.preset === key ? " active" : ""
                  }`}
                  onClick={() => setPermissions(preset)}
                >
                  {key === "read-only" ? "Read Only" : key === "standard" ? "Standard" : "Full Access"}
                </button>
              ))}
            </div>
            <p className="permission-description">
              {permissions.preset === "read-only" &&
                "Agent can only read files. No writes, no shell commands."}
              {permissions.preset === "standard" &&
                "Agent can read/write files and run shell commands."}
              {permissions.preset === "full" &&
                "Agent has full access including web search and MCP tools."}
            </p>
            <button
              type="button"
              className="btn-link"
              onClick={() => setShowPermDetails(!showPermDetails)}
            >
              {showPermDetails ? "Hide details" : "Show details"}
            </button>
            {showPermDetails && (
              <div className="permission-details">
                {(
                  [
                    ["file_read", "File Read"],
                    ["file_write", "File Write"],
                    ["bash", "Shell Commands"],
                    ["web_search", "Web Search"],
                    ["mcp", "MCP Tools"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="permission-toggle">
                    <input
                      type="checkbox"
                      checked={permissions[key]}
                      onChange={(e) =>
                        setPermissions({
                          ...permissions,
                          preset: "custom",
                          [key]: e.target.checked,
                        })
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="form-group">
            <label className="permission-toggle">
              <input
                type="checkbox"
                checked={requiresApproval}
                onChange={(e) => setRequiresApproval(e.target.checked)}
              />
              <span>Require approval before each run</span>
            </label>
            <p className="field-hint">
              Every run of this task pauses until someone approves or rejects it from the Approvals page — useful for tasks with elevated permissions.
            </p>
          </div>

          <div className="form-group">
            <label>Sandbox</label>
            <select
              value={sandbox}
              onChange={(e) => setSandbox(e.target.value as "inherit" | "" | "docker")}
            >
              <option value="inherit">Use default (from Settings)</option>
              <option value="">None — run on host</option>
              <option value="docker">Docker — disposable container</option>
            </select>
            <p className="field-hint">
              {sandbox === "docker"
                ? "This run will execute inside a Docker container with the work directory bind-mounted."
                : sandbox === ""
                ? "This run will execute as a host subprocess."
                : "Inherits the global Sandbox setting."}
            </p>
          </div>

          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || !isValid}
            >
              {getSubmitLabel()}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
