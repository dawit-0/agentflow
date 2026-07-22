import React, { useEffect, useState } from "react";
import { api, TaskRun, TaskRunOutput, DagNode } from "../api";

interface Props {
  node: DagNode;
  allNodes: DagNode[];
  upstreamIds: string[];
  downstreamIds: string[];
  onClose: () => void;
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
  onTrigger: (id: string) => void;
  onRetryTask: (id: string) => void;
  onApprove: (id: string) => void;
  onNodeSelect: (id: string) => void;
  onViewDetail: (id: string) => void;
}

export default function FlowDetailPanel({
  node,
  allNodes,
  upstreamIds,
  downstreamIds,
  onClose,
  onCancel,
  onDelete,
  onTrigger,
  onRetryTask,
  onApprove,
  onNodeSelect,
  onViewDetail,
}: Props) {
  const [latestRun, setLatestRun] = useState<TaskRun | null>(null);
  const [output, setOutput] = useState<TaskRunOutput[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const runs = await api.taskRuns.list(node.id);
      if (cancelled) return;
      if (runs.length > 0) {
        const latest = runs[0];
        setLatestRun(latest);
        const out = await api.taskRuns.output(latest.id);
        if (!cancelled) setOutput(out);
      } else {
        setLatestRun(null);
        setOutput([]);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [node.id, node.latest_run_status]);

  const nodeMap = new Map(allNodes.map((n) => [n.id, n]));
  const displayStatus = node.latest_run_status || "idle";
  const isAwaitingApproval = displayStatus === "awaiting_approval";
  const isRunning = displayStatus === "running" || displayStatus === "queued";
  const isFailed = displayStatus === "failed" || displayStatus === "cancelled";

  return (
    <div className="flow-detail-panel">
      <div className="flow-detail-header">
        <h3>{node.title}</h3>
        <button className="btn-icon" onClick={onClose}>x</button>
      </div>

      <div className="flow-detail-status-row">
        <span className={`status-pill ${displayStatus}`}>
          {isAwaitingApproval ? "needs approval" : displayStatus}
        </span>
        {node.task_type === "approval" ? (
          <span className="flow-detail-model">approval gate</span>
        ) : (
          <span className="flow-detail-model">{node.model}</span>
        )}
        {node.schedule && <span className="flow-detail-schedule">{node.schedule}</span>}
      </div>

      {isAwaitingApproval && (
        <div className="flow-detail-approval-banner">
          This flow is paused here until you approve or reject this step.
        </div>
      )}

      {latestRun && (
        <div className="flow-detail-timing">
          {latestRun.run_number > 0 && (
            <span>Run #{latestRun.run_number}</span>
          )}
          {latestRun.duration_ms > 0 && (
            <span>{(latestRun.duration_ms / 1000).toFixed(1)}s</span>
          )}
          {latestRun.cost_usd > 0 && (
            <span>${latestRun.cost_usd.toFixed(4)}</span>
          )}
          {latestRun.num_turns > 0 && (
            <span>{latestRun.num_turns} turns</span>
          )}
        </div>
      )}

      {/* Retry info */}
      {(node.max_retries > 0 || (latestRun && latestRun.attempt_number > 1)) && (
        <div className="flow-detail-retry-info">
          {node.max_retries > 0 && (
            <span className="retry-config-badge" title="Auto-retry configured">
              &#x21bb; Auto-retry: up to {node.max_retries}x (delay: {node.retry_delay_seconds}s)
            </span>
          )}
          {latestRun && latestRun.attempt_number > 1 && (
            <span className="retry-attempt-badge">
              Attempt {latestRun.attempt_number}
              {latestRun.trigger === "retry" && " (retry)"}
            </span>
          )}
        </div>
      )}

      {/* Error message for failed runs */}
      {isFailed && latestRun?.error_message && (
        <div className="flow-detail-error">
          <div className="flow-detail-dep-label">Error</div>
          <pre className="flow-detail-error-pre">{latestRun.error_message}</pre>
        </div>
      )}

      {(upstreamIds.length > 0 || downstreamIds.length > 0) && (
        <div className="flow-detail-deps">
          {upstreamIds.length > 0 && (
            <div className="flow-detail-dep-section">
              <span className="flow-detail-dep-label">Depends on</span>
              {upstreamIds.map((id) => {
                const n = nodeMap.get(id);
                return (
                  <button
                    key={id}
                    className="flow-detail-dep-link"
                    onClick={() => onNodeSelect(id)}
                  >
                    {n ? n.title : id.slice(0, 8)}
                  </button>
                );
              })}
            </div>
          )}
          {downstreamIds.length > 0 && (
            <div className="flow-detail-dep-section">
              <span className="flow-detail-dep-label">Downstream</span>
              {downstreamIds.map((id) => {
                const n = nodeMap.get(id);
                return (
                  <button
                    key={id}
                    className="flow-detail-dep-link"
                    onClick={() => onNodeSelect(id)}
                  >
                    {n ? n.title : id.slice(0, 8)}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {output.length > 0 && (
        <div className="flow-detail-output">
          <div className="flow-detail-dep-label">Output</div>
          <pre className="flow-detail-output-pre">
            {output
              .filter((o) => o.type === "assistant" || o.type === "text" || o.type === "result")
              .map((o) => o.content)
              .join("\n")}
          </pre>
        </div>
      )}

      <div className="flow-detail-actions">
        {isAwaitingApproval && (
          <>
            <button className="btn btn-sm btn-approve" onClick={() => onApprove(node.id)}>
              &#x2713; Approve
            </button>
            <button className="btn btn-sm btn-danger" onClick={() => onCancel(node.id)}>
              &#x2715; Reject
            </button>
          </>
        )}
        {!isAwaitingApproval && isRunning && (
          <button className="btn btn-sm btn-danger" onClick={() => onCancel(node.id)}>
            Cancel
          </button>
        )}
        {isFailed && (
          <button
            className="btn btn-sm btn-retry"
            onClick={() => onRetryTask(node.id)}
            title="Retry this task and continue the flow from here"
          >
            &#x21bb; Retry
          </button>
        )}
        {!isRunning && !isAwaitingApproval && (
          <button className="btn btn-sm btn-primary" onClick={() => onTrigger(node.id)}>
            Trigger
          </button>
        )}
        <button className="btn btn-sm btn-secondary" onClick={() => onDelete(node.id)}>
          Delete
        </button>
        <button className="btn btn-sm btn-secondary" onClick={() => onViewDetail(node.id)}>
          More Info &rarr;
        </button>
      </div>
    </div>
  );
}
