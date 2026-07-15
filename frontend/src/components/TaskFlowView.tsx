import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeTypes,
} from "@xyflow/react";
import dagre from "dagre";
import "@xyflow/react/dist/style.css";

import { api, DagNode, DagEdge } from "../api";
import { socket } from "../socket";
import TaskNode from "./TaskNode";
import FlowDetailPanel from "./FlowDetailPanel";

const NODE_WIDTH = 260;
const NODE_HEIGHT = 72;

const nodeTypes: NodeTypes = {
  taskNode: TaskNode,
};

function getStatusColor(status: string | null): string {
  switch (status) {
    case "running":
      return "#22c55e";
    case "success":
      return "#22c55e";
    case "failed":
      return "#ef4444";
    case "cancelled":
      return "#71717a";
    case "queued":
      return "#71717a";
    case "awaiting_approval":
      return "#f59e0b";
    default:
      return "#71717a";
  }
}

function layoutGraph(
  dagNodes: DagNode[],
  dagEdges: DagEdge[]
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 60, ranksep: 80, marginx: 40, marginy: 40 });

  dagNodes.forEach((n) => {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  });

  dagEdges.forEach((e) => {
    g.setEdge(e.source, e.target);
  });

  dagre.layout(g);

  const nodes: Node[] = dagNodes.map((n) => {
    const pos = g.node(n.id);
    return {
      id: n.id,
      type: "taskNode",
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: {
        title: n.title,
        status: n.status,
        latestRunStatus: n.latest_run_status,
        model: n.model,
        schedule: n.schedule,
        maxRetries: n.max_retries || 0,
        attemptNumber: n.attempt_number,
        latestRunTrigger: n.latest_run_trigger,
        requiresApproval: n.requires_approval,
      },
    };
  });

  const edges: Edge[] = dagEdges.map((e, i) => {
    const targetNode = dagNodes.find((n) => n.id === e.target);
    const sourceNode = dagNodes.find((n) => n.id === e.source);
    const isRunning = targetNode?.latest_run_status === "running";
    const isFailed = sourceNode?.latest_run_status === "failed";
    const passesData = e.pass_output !== false;

    return {
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      animated: isRunning,
      label: passesData ? "data" : undefined,
      labelStyle: passesData ? { fill: "#14b8a6", fontSize: 10, fontWeight: 500 } : undefined,
      labelBgStyle: passesData ? { fill: "#18181b", fillOpacity: 0.9 } : undefined,
      labelBgPadding: [4, 2] as [number, number],
      style: {
        stroke: isFailed ? "#ef4444" : isRunning ? "#22c55e" : passesData ? "#14b8a6" : "#71717a",
        strokeWidth: passesData ? 2.5 : 1.5,
        strokeDasharray: passesData ? undefined : "5,5",
      },
    };
  });

  return { nodes, edges };
}

interface Props {
  selectedFlow: string | null;
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
  onTrigger: (id: string) => void;
  onRetryTask: (id: string) => void;
  onRetryFlow: (id: string) => void;
  onResumeFlow: (id: string) => void;
  onViewTaskDetail: (id: string) => void;
  onApproveRun: (runId: string) => void;
  onRejectRun: (runId: string) => void;
}

export default function TaskFlowView({
  selectedFlow,
  onCancel,
  onDelete,
  onTrigger,
  onRetryTask,
  onRetryFlow,
  onResumeFlow,
  onViewTaskDetail,
  onApproveRun,
  onRejectRun,
}: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState([] as Node[]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([] as Edge[]);
  const [dagData, setDagData] = useState<{ nodes: DagNode[]; edges: DagEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const loadDag = useCallback(async () => {
    const data = await api.tasks.dag(selectedFlow || undefined);
    setDagData(data);
    const { nodes: layoutNodes, edges: layoutEdges } = layoutGraph(data.nodes, data.edges);
    setNodes(layoutNodes);
    setEdges(layoutEdges);
  }, [selectedFlow, setNodes, setEdges]);

  useEffect(() => {
    loadDag();
  }, [loadDag]);

  useEffect(() => {
    function onTaskUpdated(data: { id: string; latest_run_status: string }) {
      setDagData((prev) => {
        const updated = {
          ...prev,
          nodes: prev.nodes.map((n) =>
            n.id === data.id ? { ...n, latest_run_status: data.latest_run_status } : n
          ),
        };
        const { nodes: ln, edges: le } = layoutGraph(updated.nodes, updated.edges);
        setNodes(ln);
        setEdges(le);
        return updated;
      });
    }

    socket.on("task:updated", onTaskUpdated);
    return () => {
      socket.off("task:updated", onTaskUpdated);
    };
  }, [setNodes, setEdges]);

  useEffect(() => {
    const interval = setInterval(loadDag, 10000);
    return () => clearInterval(interval);
  }, [loadDag]);

  const selectedNode = useMemo(
    () => dagData.nodes.find((n) => n.id === selectedNodeId) || null,
    [dagData.nodes, selectedNodeId]
  );

  const upstreamIds = useMemo(
    () =>
      selectedNodeId
        ? dagData.edges.filter((e) => e.target === selectedNodeId).map((e) => e.source)
        : [],
    [dagData.edges, selectedNodeId]
  );

  const downstreamIds = useMemo(
    () =>
      selectedNodeId
        ? dagData.edges.filter((e) => e.source === selectedNodeId).map((e) => e.target)
        : [],
    [dagData.edges, selectedNodeId]
  );

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const handleCancel = useCallback(
    (id: string) => {
      onCancel(id);
      setTimeout(loadDag, 500);
    },
    [onCancel, loadDag]
  );

  const handleDelete = useCallback(
    (id: string) => {
      setSelectedNodeId(null);
      onDelete(id);
      setTimeout(loadDag, 500);
    },
    [onDelete, loadDag]
  );

  const handleTrigger = useCallback(
    (id: string) => {
      onTrigger(id);
      setTimeout(loadDag, 500);
    },
    [onTrigger, loadDag]
  );

  const handleRetryTask = useCallback(
    (id: string) => {
      onRetryTask(id);
      setTimeout(loadDag, 500);
    },
    [onRetryTask, loadDag]
  );

  const handleApproveRun = useCallback(
    (runId: string) => {
      onApproveRun(runId);
      setTimeout(loadDag, 500);
    },
    [onApproveRun, loadDag]
  );

  const handleRejectRun = useCallback(
    (runId: string) => {
      onRejectRun(runId);
      setTimeout(loadDag, 500);
    },
    [onRejectRun, loadDag]
  );

  const handleRetryFlow = useCallback(() => {
    if (selectedFlow) {
      onRetryFlow(selectedFlow);
      setTimeout(loadDag, 500);
    }
  }, [selectedFlow, onRetryFlow, loadDag]);

  const handleResumeFlow = useCallback(() => {
    if (selectedFlow) {
      onResumeFlow(selectedFlow);
      setTimeout(loadDag, 500);
    }
  }, [selectedFlow, onResumeFlow, loadDag]);

  const hasFailedTasks = dagData.nodes.some(
    (n) => n.latest_run_status === "failed" || n.latest_run_status === "cancelled"
  );

  const hasAnyRuns = dagData.nodes.some((n) => n.latest_run_status != null);

  return (
    <div className="agentflow-container">
      {selectedFlow && hasAnyRuns && (
        <div className="flow-toolbar">
          {hasFailedTasks && (
            <>
              <button
                className="btn btn-sm flow-toolbar-btn flow-toolbar-resume"
                onClick={handleResumeFlow}
                title="Resume from failed tasks — retries the earliest failed tasks and continues the flow"
              >
                &#x25b6; Resume Flow
              </button>
              <button
                className="btn btn-sm flow-toolbar-btn flow-toolbar-retry"
                onClick={handleRetryFlow}
                title="Retry entire flow from scratch — re-triggers all root tasks"
              >
                &#x21bb; Retry Flow
              </button>
            </>
          )}
        </div>
      )}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="rgba(255,255,255,0.06)" />
        <Controls
          className="flow-controls"
          showInteractive={false}
        />
        <MiniMap
          className="flow-minimap"
          nodeColor={(n) => getStatusColor((n.data as { latestRunStatus?: string })?.latestRunStatus || null)}
          maskColor="rgba(9, 9, 11, 0.8)"
        />
      </ReactFlow>

      {dagData.nodes.length === 0 && (
        <div className="flow-empty-overlay">
          <div className="empty-state">
            <h2>No tasks yet</h2>
            <p>Create tasks with dependencies to see the flow graph</p>
          </div>
        </div>
      )}

      {selectedNode && (
        <FlowDetailPanel
          node={selectedNode}
          allNodes={dagData.nodes}
          upstreamIds={upstreamIds}
          downstreamIds={downstreamIds}
          onClose={() => setSelectedNodeId(null)}
          onCancel={handleCancel}
          onDelete={handleDelete}
          onTrigger={handleTrigger}
          onRetryTask={handleRetryTask}
          onApproveRun={handleApproveRun}
          onRejectRun={handleRejectRun}
          onNodeSelect={(id) => setSelectedNodeId(id)}
          onViewDetail={onViewTaskDetail}
        />
      )}
    </div>
  );
}
