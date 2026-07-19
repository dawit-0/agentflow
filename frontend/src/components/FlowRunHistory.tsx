import React from "react";
import type { FlowRun } from "../api";

function statusDotClass(status: FlowRun["status"]): string {
  switch (status) {
    case "running":
      return "run-dot-running";
    case "success":
      return "run-dot-success";
    case "failed":
      return "run-dot-failed";
    case "cancelled":
      return "run-dot-cancelled";
    default:
      return "run-dot-queued";
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface Props {
  runs: FlowRun[];
  selectedRunId: string | null; // null = live view (latest state per task)
  onSelect: (runId: string | null) => void;
  onCancelRun: (runId: string) => void;
}

export default function FlowRunHistory({ runs, selectedRunId, onSelect, onCancelRun }: Props) {
  if (runs.length === 0) return null;

  return (
    <div className="flow-run-history">
      <div className="flow-run-history-header">
        <span>Runs</span>
        {selectedRunId && (
          <button className="flow-run-history-live" onClick={() => onSelect(null)}>
            back to live
          </button>
        )}
      </div>
      <div className="flow-run-history-list">
        {runs.map((run) => {
          const active = run.status === "queued" || run.status === "running";
          const counts =
            run.total_tasks != null
              ? `${run.succeeded_tasks ?? 0}/${run.total_tasks} ok` +
                ((run.failed_tasks ?? 0) > 0 ? `, ${run.failed_tasks} failed` : "")
              : "";
          return (
            <div
              key={run.id}
              className={`flow-run-item ${selectedRunId === run.id ? "selected" : ""}`}
              onClick={() => onSelect(run.id)}
              title={`${run.trigger}${run.partial ? " (partial)" : ""} — ${counts}`}
            >
              <span className={`run-dot ${statusDotClass(run.status)}`} />
              <span className="flow-run-item-number">#{run.run_number}</span>
              <span className="flow-run-item-time">{formatTime(run.started_at || run.created_at)}</span>
              {run.partial ? <span className="flow-run-item-partial">partial</span> : null}
              {run.total_cost_usd > 0 && (
                <span className="flow-run-item-cost">${run.total_cost_usd.toFixed(2)}</span>
              )}
              {active && (
                <button
                  className="flow-run-item-cancel"
                  title="Cancel this run"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCancelRun(run.id);
                  }}
                >
                  &#x2715;
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
