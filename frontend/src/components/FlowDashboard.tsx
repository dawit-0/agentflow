import React from "react";
import { Flow, Task, api } from "../api";

interface Props {
  flows: Flow[];
  tasks: Task[];
  onSelectFlow: (id: string) => void;
  onNewFlow: () => void;
  onFlowsChange: () => void;
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "Never";
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);
  if (diffSec < 60) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

export default function FlowDashboard({ flows, tasks, onSelectFlow, onNewFlow, onFlowsChange }: Props) {
  async function toggleScheduleEnabled(e: React.MouseEvent, flow: Flow) {
    e.stopPropagation();
    await api.flows.update(flow.id, { schedule_enabled: !flow.schedule_enabled });
    onFlowsChange();
  }

  function getFlowStats(flowId: string) {
    const flowTasks = tasks.filter((t) => t.flow_id === flowId);
    const running = flowTasks.filter((t) => t.latest_run?.status === "running").length;
    const failed = flowTasks.filter((t) => t.latest_run?.status === "failed").length;
    const success = flowTasks.filter((t) => t.latest_run?.status === "success").length;
    return { total: flowTasks.length, running, failed, success };
  }

  function getFlowStatus(flowId: string): "running" | "failed" | "success" | "idle" {
    const stats = getFlowStats(flowId);
    if (stats.running > 0) return "running";
    if (stats.failed > 0) return "failed";
    if (stats.success > 0 && stats.success === stats.total) return "success";
    return "idle";
  }

  if (flows.length === 0) {
    return (
      <div className="flow-dashboard-empty">
        <div className="flow-dashboard-empty-content">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
            <rect x="4" y="8" width="40" height="32" rx="4" stroke="var(--text-muted)" strokeWidth="2" />
            <path d="M24 18v12M18 24h12" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <h3>No flows yet</h3>
          <p>Create a flow to organize and run your tasks.</p>
          <button className="btn btn-primary" onClick={onNewFlow}>
            + New Flow
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flow-dashboard">
      <div className="flow-dashboard-header">
        <div>
          <h2 className="flow-dashboard-title">Flows</h2>
          <p className="flow-dashboard-subtitle">
            {flows.length} flow{flows.length !== 1 ? "s" : ""}
          </p>
        </div>
        <button className="btn btn-primary" onClick={onNewFlow}>
          + New Flow
        </button>
      </div>
      <div className="flow-table-wrapper">
        <table className="flow-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Tasks</th>
              <th>Running</th>
              <th>Failed</th>
              <th>Schedule</th>
              <th>Last Run</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {flows.map((flow) => {
              const stats = getFlowStats(flow.id);
              const status = getFlowStatus(flow.id);
              return (
                <tr
                  key={flow.id}
                  className="flow-table-row"
                  onClick={() => onSelectFlow(flow.id)}
                >
                  <td className="flow-table-name-cell">
                    <span className={`flow-card-dot flow-card-dot-${status}`} />
                    <div className="flow-table-name-text">
                      <div className="flow-table-name">{flow.name}</div>
                      {flow.description && (
                        <div className="flow-table-desc">{flow.description}</div>
                      )}
                    </div>
                  </td>
                  <td>
                    <span className={`flow-status-pill flow-status-${status}`}>
                      {status}
                    </span>
                  </td>
                  <td className="flow-table-num">{stats.total}</td>
                  <td className="flow-table-num">
                    {stats.running > 0 ? (
                      <span className="flow-card-stat-running">{stats.running}</span>
                    ) : (
                      <span className="text-muted">0</span>
                    )}
                  </td>
                  <td className="flow-table-num">
                    {stats.failed > 0 ? (
                      <span className="flow-card-stat-failed">{stats.failed}</span>
                    ) : (
                      <span className="text-muted">0</span>
                    )}
                  </td>
                  <td>
                    {flow.schedule ? (
                      <div className="flow-schedule-cell">
                        <button
                          type="button"
                          className={`flow-toggle${flow.schedule_enabled ? " on" : ""}`}
                          onClick={(e) => toggleScheduleEnabled(e, flow)}
                          title={flow.schedule_enabled ? "Disable scheduled runs" : "Enable scheduled runs"}
                          aria-label={flow.schedule_enabled ? "Disable scheduled runs" : "Enable scheduled runs"}
                          aria-pressed={flow.schedule_enabled}
                        >
                          <span className="flow-toggle-thumb" />
                        </button>
                        <span
                          className={`flow-card-schedule${flow.schedule_enabled ? "" : " flow-card-schedule-off"}`}
                        >
                          &#x23f0; {flow.schedule}
                        </span>
                      </div>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="flow-table-time">{formatRelativeTime(flow.last_run_at)}</td>
                  <td className="flow-table-time">{formatRelativeTime(flow.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
