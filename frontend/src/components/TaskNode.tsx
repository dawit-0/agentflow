import React, { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";

export interface TaskNodeData {
  title: string;
  status: string;
  latestRunStatus: string | null;
  model: string;
  schedule: string | null;
  maxRetries: number;
  attemptNumber: number | null;
  latestRunTrigger: string | null;
  requiresApproval: boolean;
  [key: string]: unknown;
}

function TaskNode({ data }: NodeProps) {
  const { title, latestRunStatus, model, schedule, maxRetries, attemptNumber, latestRunTrigger, requiresApproval } =
    data as unknown as TaskNodeData;
  const displayStatus = latestRunStatus || "idle";
  const statusClass = displayStatus === "cancelled" ? "cancelled" : displayStatus;
  const statusLabel = displayStatus === "awaiting_approval" ? "needs approval" : displayStatus;
  const modelShort = ((model as string) || "")
    .replace("claude-", "")
    .replace("-20250514", "")
    .replace("-latest", "");

  const isRetry = latestRunTrigger === "retry";
  const showRetryBadge = isRetry && attemptNumber && attemptNumber > 1;
  const hasAutoRetry = maxRetries > 0;

  return (
    <div className={`flow-node flow-node-${statusClass}`}>
      <Handle type="target" position={Position.Top} className="flow-handle" />
      <div className="flow-node-header">
        <span className="flow-node-title">
          {schedule && (
            <span className="schedule-badge-sm" title={`Schedule: ${schedule}`}>
              &#x23f0;{" "}
            </span>
          )}
          {requiresApproval && (
            <span className="schedule-badge-sm" title="Requires approval before each run">
              &#x1f512;{" "}
            </span>
          )}
          {title as string}
        </span>
        <span className={`flow-node-status ${statusClass}`}>{statusLabel}</span>
      </div>
      <div className="flow-node-meta">
        {modelShort}
        {hasAutoRetry && (
          <span className="flow-node-retry-badge" title={`Auto-retry: up to ${maxRetries}x`}>
            &#x21bb; {maxRetries}x
          </span>
        )}
        {showRetryBadge && (
          <span className="flow-node-attempt-badge" title={`Attempt ${attemptNumber}`}>
            attempt {attemptNumber}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="flow-handle" />
    </div>
  );
}

export default memo(TaskNode);
