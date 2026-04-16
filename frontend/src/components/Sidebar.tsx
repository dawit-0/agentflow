import React, { useState } from "react";
import { Flow, Task, Agent, api } from "../api";

interface Props {
  flows: Flow[];
  selectedFlow: string | null;
  onSelectFlow: (id: string | null) => void;
  onFlowsChange: () => void;
  tasks: Task[];
  view: "flows" | "agents" | "settings" | "dashboard";
  agents: Agent[];
  onNewTask: () => void;
  onNewAgent: () => void;
  onSpawnAgent: (agent: Agent) => void;
  onEditAgent: (agent: Agent) => void;
  onTriggerFlow: (id: string) => void;
  onRetryFlow: (id: string) => void;
  onResumeFlow: (id: string) => void;
  onNewFlow: () => void;
  onQuickTask: () => void;
}

export default function Sidebar({
  flows,
  selectedFlow,
  onSelectFlow,
  onFlowsChange,
  tasks,
  view,
  agents,
  onNewTask,
  onNewAgent,
  onSpawnAgent,
  onEditAgent,
  onTriggerFlow,
  onRetryFlow,
  onResumeFlow,
  onNewFlow,
  onQuickTask,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  async function handleDeleteFlow() {
    if (!selectedFlow) return;
    await api.flows.delete(selectedFlow);
    setConfirmingDelete(false);
    onSelectFlow(null);
    onFlowsChange();
  }

  const runningTasks = tasks.filter(
    (t) => t.latest_run?.status === "running"
  );
  const failedTasks = tasks.filter(
    (t) => t.latest_run?.status === "failed"
  );
  const scheduledTasks = tasks.filter((t) => t.schedule);

  const selectedFlowData = flows.find((f) => f.id === selectedFlow);

  // Tasks for the selected flow
  const flowTasks = selectedFlow
    ? tasks.filter((t) => t.flow_id === selectedFlow)
    : [];
  const flowRunning = flowTasks.filter((t) => t.latest_run?.status === "running");
  const flowFailed = flowTasks.filter((t) => t.latest_run?.status === "failed");

  // Filter flows by search
  const filteredFlows = searchQuery
    ? flows.filter((f) => f.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : flows;

  function getTaskStatusColor(task: Task): string {
    const status = task.latest_run?.status;
    if (status === "running") return "var(--success)";
    if (status === "failed") return "var(--danger)";
    if (status === "queued") return "var(--queued)";
    if (status === "success") return "var(--success)";
    return "var(--text-muted)";
  }

  return (
    <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`}>
      <button
        className="sidebar-toggle"
        onClick={() => setCollapsed(!collapsed)}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          className={`sidebar-toggle-icon ${collapsed ? "rotated" : ""}`}
        >
          <path
            d="M10 12L6 8L10 4"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {!collapsed && (
        <div className="sidebar-inner">
          {/* ── Flows Tab ── */}
          {view === "flows" && !selectedFlow && (
            <>
              {/* Actions */}
              <div className="sidebar-section">
                <h3>Actions</h3>
                <button className="sidebar-action-btn" onClick={onNewFlow}>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  New Flow
                </button>
                <button className="sidebar-action-btn" onClick={onQuickTask}>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M13 2L3 14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    <path d="M3 2l4 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  Quick Task
                </button>
              </div>

              {/* Search */}
              <div className="sidebar-section" style={{ borderBottom: "none", paddingBottom: 0 }}>
                <div className="sidebar-search">
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="sidebar-search-icon">
                    <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="2" />
                    <path d="M11 11l3 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search flows..."
                    className="sidebar-search-input"
                    onKeyDown={(e) => {
                      if (e.key === "Escape") setSearchQuery("");
                    }}
                  />
                </div>
              </div>

              {/* Flow List */}
              <div className="sidebar-section">
                <h3>Flows</h3>
                {filteredFlows.map((f) => {
                  const count = tasks.filter((t) => t.flow_id === f.id).length;
                  const hasRunning = tasks.some((t) => t.flow_id === f.id && t.latest_run?.status === "running");
                  const hasFailed = tasks.some((t) => t.flow_id === f.id && t.latest_run?.status === "failed");
                  return (
                    <div
                      key={f.id}
                      className="project-item"
                      onClick={() => onSelectFlow(f.id)}
                    >
                      <span className="sidebar-flow-name">
                        <span
                          className="sidebar-flow-dot"
                          style={{
                            background: hasRunning ? "var(--success)" : hasFailed ? "var(--danger)" : "var(--text-muted)",
                          }}
                        />
                        {f.name}
                      </span>
                      <span className="sidebar-item-right">
                        {f.schedule && (
                          <span className="flow-schedule-badge" title={f.schedule}>
                            &#x23f0;
                          </span>
                        )}
                        <span className="sidebar-count">{count}</span>
                      </span>
                    </div>
                  );
                })}
                {filteredFlows.length === 0 && searchQuery && (
                  <div className="sidebar-empty-hint">No flows match "{searchQuery}"</div>
                )}
              </div>

              {/* Overview Stats */}
              <div className="sidebar-section">
                <h3>Overview</h3>
                <div className="sidebar-stats">
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value">{flows.length}</span>
                    <span className="sidebar-stat-label">Flows</span>
                  </div>
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value sidebar-stat-running">
                      {runningTasks.length}
                    </span>
                    <span className="sidebar-stat-label">Running</span>
                  </div>
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value sidebar-stat-failed">
                      {failedTasks.length}
                    </span>
                    <span className="sidebar-stat-label">Failed</span>
                  </div>
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value sidebar-stat-scheduled">
                      {scheduledTasks.length}
                    </span>
                    <span className="sidebar-stat-label">Scheduled</span>
                  </div>
                </div>
              </div>

              {/* Running Now */}
              {runningTasks.length > 0 && (
                <div className="sidebar-section">
                  <h3>Running Now</h3>
                  {runningTasks.slice(0, 5).map((t) => (
                    <div key={t.id} className="sidebar-activity-item">
                      <span className="sidebar-activity-dot running" />
                      <span className="sidebar-activity-text">{t.title}</span>
                    </div>
                  ))}
                  {runningTasks.length > 5 && (
                    <span className="sidebar-more-text">
                      +{runningTasks.length - 5} more
                    </span>
                  )}
                </div>
              )}
            </>
          )}

          {/* ── Flow Detail (State B) ── */}
          {view === "flows" && selectedFlow && selectedFlowData && (
            <>
              {/* Back Button */}
              <div className="sidebar-section" style={{ borderBottom: "none", paddingBottom: 0 }}>
                <button
                  className="sidebar-back-btn"
                  onClick={() => onSelectFlow(null)}
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Flows
                </button>
              </div>

              {/* Flow Info */}
              <div className="sidebar-section">
                <div className="sidebar-flow-header">
                  <h2 className="sidebar-flow-title">{selectedFlowData.name}</h2>
                  {selectedFlowData.description && (
                    <p className="sidebar-flow-desc">{selectedFlowData.description}</p>
                  )}
                  {selectedFlowData.schedule && (
                    <span className="sidebar-flow-schedule">
                      &#x23f0; {selectedFlowData.schedule}
                    </span>
                  )}
                </div>
              </div>

              {/* Flow Actions */}
              <div className="sidebar-section">
                <h3>Actions</h3>
                <button
                  className="sidebar-action-btn"
                  onClick={() => onTriggerFlow(selectedFlow)}
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M4 2l10 6-10 6V2z" fill="currentColor" />
                  </svg>
                  Trigger Flow
                </button>
                {flowFailed.length > 0 && (
                  <button
                    className="sidebar-action-btn sidebar-action-warning"
                    onClick={() => onRetryFlow(selectedFlow)}
                  >
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                      <path
                        d="M2 8a6 6 0 0111.5-2.5M14 8a6 6 0 01-11.5 2.5"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                      />
                      <path d="M14 2v4h-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M2 14v-4h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Retry Failed
                  </button>
                )}
                {flowFailed.length > 0 && (
                  <button
                    className="sidebar-action-btn sidebar-action-accent"
                    onClick={() => onResumeFlow(selectedFlow)}
                  >
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                      <path d="M3 2l5 6-5 6V2z" fill="currentColor" />
                      <path d="M9 2l5 6-5 6V2z" fill="currentColor" />
                    </svg>
                    Resume Flow
                  </button>
                )}
                <button className="sidebar-action-btn" onClick={onNewTask}>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  Add Task to Flow
                </button>
                {!confirmingDelete ? (
                  <button
                    className="sidebar-action-btn sidebar-action-danger"
                    onClick={() => setConfirmingDelete(true)}
                  >
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                      <path d="M3 4h10M6 4V3a1 1 0 011-1h2a1 1 0 011 1v1M5 4v9a1 1 0 001 1h4a1 1 0 001-1V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Delete Flow
                  </button>
                ) : (
                  <div className="sidebar-delete-confirm">
                    <span className="sidebar-delete-confirm-text">Delete this flow?</span>
                    <div className="sidebar-delete-confirm-actions">
                      <button
                        className="sidebar-action-btn sidebar-action-danger"
                        onClick={handleDeleteFlow}
                      >
                        Confirm
                      </button>
                      <button
                        className="sidebar-action-btn"
                        onClick={() => setConfirmingDelete(false)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Task List */}
              {flowTasks.length > 0 && (
                <div className="sidebar-section">
                  <h3>Tasks ({flowTasks.length})</h3>
                  {flowTasks.map((t) => (
                    <div key={t.id} className="sidebar-task-item">
                      <span
                        className="sidebar-task-dot"
                        style={{ background: getTaskStatusColor(t) }}
                      />
                      <span className="sidebar-task-name">{t.title}</span>
                      <span className="sidebar-task-status">
                        {t.latest_run?.status || "idle"}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Flow Stats */}
              <div className="sidebar-section">
                <h3>Stats</h3>
                <div className="sidebar-stats">
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value">{flowTasks.length}</span>
                    <span className="sidebar-stat-label">Tasks</span>
                  </div>
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value sidebar-stat-running">
                      {flowRunning.length}
                    </span>
                    <span className="sidebar-stat-label">Running</span>
                  </div>
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value sidebar-stat-failed">
                      {flowFailed.length}
                    </span>
                    <span className="sidebar-stat-label">Failed</span>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* ── Agents Tab ── */}
          {view === "agents" && (
            <>
              <div className="sidebar-section">
                <h3>Quick Actions</h3>
                <button className="sidebar-action-btn" onClick={onNewAgent}>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  New Agent
                </button>
              </div>

              <div className="sidebar-section">
                <h3>Agents ({agents.length})</h3>
                {agents.length === 0 ? (
                  <div className="sidebar-empty-hint">
                    No agents yet. Create one to get started.
                  </div>
                ) : (
                  agents.map((a) => (
                    <div key={a.id} className="sidebar-agent-item">
                      <div className="sidebar-agent-name">{a.name}</div>
                      {a.description && (
                        <div className="sidebar-agent-desc">
                          {a.description}
                        </div>
                      )}
                      <div className="sidebar-agent-actions">
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => onSpawnAgent(a)}
                        >
                          Spawn
                        </button>
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => onEditAgent(a)}
                        >
                          Edit
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>

              <div className="sidebar-section">
                <h3>Overview</h3>
                <div className="sidebar-stats">
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value">{agents.length}</span>
                    <span className="sidebar-stat-label">Agents</span>
                  </div>
                  <div className="sidebar-stat">
                    <span className="sidebar-stat-value">{tasks.length}</span>
                    <span className="sidebar-stat-label">Tasks</span>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </aside>
  );
}
