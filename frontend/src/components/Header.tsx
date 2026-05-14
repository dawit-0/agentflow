import React, { useEffect, useState } from "react";
import { api, DebugStatus, Task } from "../api";

interface Props {
  tasks: Task[];
  view: "flows" | "agents" | "settings";
  onViewChange: (view: "flows" | "agents" | "settings") => void;
  onNewAgent: () => void;
}

export default function Header({ tasks, view, onViewChange, onNewAgent }: Props) {
  const [debugStatus, setDebugStatus] = useState<DebugStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const s = await api.debug.status();
        if (!cancelled) setDebugStatus(s);
      } catch {
        if (!cancelled) setDebugStatus(null);
      }
    }
    poll();
    const interval = setInterval(poll, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  return (
    <header className="header">
      <div className="header-left">
        <div className="header-logo">
          AgentFlow
        </div>
        <div className="header-tabs">
          <button
            className={`header-tab${view === "flows" ? " active" : ""}`}
            onClick={() => onViewChange("flows")}
          >
            Flows
          </button>
          <button
            className={`header-tab${view === "agents" ? " active" : ""}`}
            onClick={() => onViewChange("agents")}
          >
            Agent Registry
          </button>
        </div>
      </div>
      <div className="header-stats">
        <span className="stat-badge">
          {tasks.length} task{tasks.length !== 1 ? "s" : ""}
        </span>
        {tasks.filter((t) => t.schedule).length > 0 && (
          <span className="stat-badge">
            <span className="dot scheduled" /> {tasks.filter((t) => t.schedule).length} scheduled
          </span>
        )}
      </div>
      <div className="header-system-status">
        {debugStatus ? (
          <>
            <span className={`system-status-dot ${debugStatus.orchestrator.running ? "ok" : "down"}`} />
            <span className="system-status-text">
              {debugStatus.orchestrator.active_runs} active &middot; {debugStatus.queued_runs} queued
            </span>
            {debugStatus.recent_failures.length > 0 && (
              <span className="system-status-warn">
                {debugStatus.recent_failures.length} recent failure{debugStatus.recent_failures.length !== 1 ? "s" : ""}
              </span>
            )}
          </>
        ) : (
          <>
            <span className="system-status-dot down" />
            <span className="system-status-text">Status unavailable</span>
          </>
        )}
      </div>
      <div className="header-actions">
        {view === "agents" && (
          <button className="btn btn-primary" onClick={onNewAgent}>
            + New Agent
          </button>
        )}
        <button
          className={`btn btn-icon${view === "settings" ? " btn-icon-active" : ""}`}
          onClick={() => onViewChange("settings")}
          title="Settings"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
