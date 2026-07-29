import React, { useCallback, useEffect, useState } from "react";
import { PendingApproval, Permissions, api } from "../api";
import { socket } from "../socket";

interface Props {
  onBack: () => void;
  onSelectTask?: (taskId: string) => void;
}

function timeAgo(iso: string): string {
  const created = new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime();
  const diff = Date.now() - created;
  if (Number.isNaN(diff)) return "";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function permissionSummary(raw: string): string {
  try {
    const perms = JSON.parse(raw) as Permissions;
    const on: string[] = [];
    if (perms.file_write) on.push("write");
    if (perms.bash) on.push("bash");
    if (perms.web_search) on.push("web");
    if (perms.mcp) on.push("mcp");
    if (on.length === 0) return "read-only";
    return on.join(", ");
  } catch {
    return "unknown";
  }
}

export default function ApprovalsPage({ onBack, onSelectTask }: Props) {
  const [items, setItems] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [comments, setComments] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.approvals.listPending();
      setItems(list);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    function onChange() {
      load();
    }
    socket.on("approval:requested", onChange);
    socket.on("approval:decided", onChange);
    return () => {
      socket.off("approval:requested", onChange);
      socket.off("approval:decided", onChange);
    };
  }, [load]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onBack();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onBack]);

  async function decide(runId: string, decision: "approve" | "reject") {
    setBusy((b) => ({ ...b, [runId]: true }));
    try {
      const comment = comments[runId]?.trim() || undefined;
      if (decision === "approve") {
        await api.approvals.approve(runId, comment);
      } else {
        await api.approvals.reject(runId, comment);
      }
      setItems((prev) => prev.filter((i) => i.task_run_id !== runId));
    } finally {
      setBusy((b) => ({ ...b, [runId]: false }));
    }
  }

  return (
    <div className="notifications-page approvals-page">
      <div className="notifications-page-header">
        <div className="notifications-page-title">
          <button className="btn btn-sm" onClick={onBack} title="Back (Esc)">
            ← Back
          </button>
          <h2>Approvals</h2>
        </div>
        <div className="notifications-page-controls">
          <span className="field-hint">{items.length} pending</span>
        </div>
      </div>

      {loading ? (
        <div className="notifications-empty">Loading...</div>
      ) : items.length === 0 ? (
        <div className="notifications-empty">Nothing waiting on a decision.</div>
      ) : (
        <ul className="approvals-list">
          {items.map((item) => (
            <li key={item.id} className="approval-card">
              <div className="approval-card-header">
                <button
                  className="btn-link approval-card-title"
                  onClick={() => onSelectTask?.(item.task_id)}
                >
                  {item.task_title}
                </button>
                <span className="notification-item-time">{timeAgo(item.created_at)}</span>
              </div>
              <div className="approval-card-meta">
                {item.flow_name && <span>Flow: {item.flow_name}</span>}
                <span>Model: {item.model}</span>
                <span>Permissions: {permissionSummary(item.permissions)}</span>
                <span>Trigger: {item.run_trigger} (run #{item.run_number})</span>
              </div>
              <p className="approval-card-question">{item.question}</p>
              <div className="approval-card-actions">
                <input
                  className="approval-comment-input"
                  placeholder="Optional comment..."
                  value={comments[item.task_run_id] || ""}
                  onChange={(e) =>
                    setComments((c) => ({ ...c, [item.task_run_id]: e.target.value }))
                  }
                />
                <button
                  className="btn btn-sm btn-danger"
                  disabled={busy[item.task_run_id]}
                  onClick={() => decide(item.task_run_id, "reject")}
                >
                  Reject
                </button>
                <button
                  className="btn btn-sm btn-success"
                  disabled={busy[item.task_run_id]}
                  onClick={() => decide(item.task_run_id, "approve")}
                >
                  Approve
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
