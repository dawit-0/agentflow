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

import { api, DagNode, DagEdge, FlowRun } from "../api";
import { socket } from "../socket";
import TaskNode from "./TaskNode";
import FlowDetailPanel from "./FlowDetailPanel";
import FlowRunHistory from "./FlowRunHistory";

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
    default:
      return "#71717a";
  }
}

/** Latest-attempt status per task within one flow run. Tasks absent from the
 * run map to null so the graph renders them as idle/dimmed. */
function runStatusByTask(run: FlowRun): Map<string, string> {
  const best = new Map<string, { runNumber: number; status: string }>();
  for (const tr of run.task_runs || []) {
    const cur = best.get(tr.task_id);
    if (!cur || tr.run_number > cur.runNumber) {
      best.set(tr.task_id, { runNumber: tr.run_number, status: tr.status });
    }
  }
  return new Map([...best].map(([taskId, v]) => [taskId, v.status]));
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
}: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState([] as Node[]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([] as Edge[]);
  const [dagData, setDagData] = useState<{ nodes: DagNode[]; edges: DagEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [flowRuns, setFlowRuns] = useState<FlowRun[]>([]);
  // null = live view; otherwise the graph shows this historical run's statuses
  const [selectedFlowRunId, setSelectedFlowRunId] = useState<string | null>(null);
  const [selectedFlowRun, setSelectedFlowRun] = useState<FlowRun | null>(null);

  const loadDag = useCallback(async () => {
    const data = await api.tasks.dag(selectedFlow || undefined);
    setDagData(data);
  }, [selectedFlow]);

  const loadFlowRuns = useCallback(async () => {
    if (!selectedFlow) {
      setFlowRuns([]);
      return;
    }
    setFlowRuns(await api.flows.runs(selectedFlow));
  }, [selectedFlow]);

  // Re-render the graph whenever the DAG or the selected historical run changes
  useEffect(() => {
    let nodesToRender = dagData.nodes;
    if (selectedFlowRun) {
      const statusMap = runStatusByTask(selectedFlowRun);
      nodesToRender = dagData.nodes.map((n) => ({
        ...n,
        latest_run_status: statusMap.get(n.id) ?? null,
      }));
    }
    const { nodes: ln, edges: le } = layoutGraph(nodesToRender, dagData.edges);
    setNodes(ln);
    setEdges(le);
  }, [dagData, selectedFlowRun, setNodes, setEdges]);

  useEffect(() => {
    loadDag();
    loadFlowRuns();
    setSelectedFlowRunId(null);
    setSelectedFlowRun(null);
  }, [loadDag, loadFlowRuns]);

  // Fetch the selected run's member task runs for graph coloring
  useEffect(() => {
    if (!selectedFlowRunId) {
      setSelectedFlowRun(null);
      return;
    }
    let stale = false;
    api.flowRuns.get(selectedFlowRunId).then((run) => {
      if (!stale) setSelectedFlowRun(run);
    });
    return () => {
      stale = true;
    };
  }, [selectedFlowRunId]);

  useEffect(() => {
    function onTaskUpdated(data: { id: string; latest_run_status: string }) {
      setDagData((prev) => ({
        ...prev,
        nodes: prev.nodes.map((n) =>
          n.id === data.id ? { ...n, latest_run_status: data.latest_run_status } : n
        ),
      }));
    }

    function onFlowRunChanged() {
      loadFlowRuns();
    }

    socket.on("task:updated", onTaskUpdated);
    socket.on("flow_run:started", onFlowRunChanged);
    socket.on("flow_run:finished", onFlowRunChanged);
    return () => {
      socket.off("task:updated", onTaskUpdated);
      socket.off("flow_run:started", onFlowRunChanged);
      socket.off("flow_run:finished", onFlowRunChanged);
    };
  }, [loadFlowRuns]);

  useEffect(() => {
    const interval = setInterval(() => {
      loadDag();
      loadFlowRuns();
    }, 10000);
    return () => clearInterval(interval);
  }, [loadDag, loadFlowRuns]);

  const handleCancelFlowRun = useCallback(
    async (runId: string) => {
      await api.flowRuns.cancel(runId);
      loadFlowRuns();
      setTimeout(loadDag, 500);
    },
    [loadFlowRuns, loadDag]
  );

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
      {selectedFlow && (
        <FlowRunHistory
          runs={flowRuns}
          selectedRunId={selectedFlowRunId}
          onSelect={setSelectedFlowRunId}
          onCancelRun={handleCancelFlowRun}
        />
      )}

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
          onNodeSelect={(id) => setSelectedNodeId(id)}
          onViewDetail={onViewTaskDetail}
        />
      )}
    </div>
  );
}
