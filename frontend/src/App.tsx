import React, { useEffect, useState, useCallback } from "react";
import { api, Task, Flow, Agent, Permissions, Settings } from "./api";
import { socket } from "./socket";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import TaskForm from "./components/TaskForm";
import AgentList from "./components/AgentList";
import AgentForm from "./components/AgentForm";
import TaskFlowView from "./components/TaskFlowView";
import FlowDashboard from "./components/FlowDashboard";
import TaskDetailPage from "./components/TaskDetailPage";
import NewFlowModal from "./components/NewFlowModal";
import SettingsPage from "./components/SettingsPage";
import DashboardPage from "./components/DashboardPage";
import NotificationsPage from "./components/NotificationsPage";
import { useNotifications } from "./hooks/useNotifications";

export interface TaskPrefill {
  title: string;
  prompt: string;
  model: string;
  workDir: string;
  flowId: string;
  permissions: Permissions;
  agentId: string;
}

export default function App() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [flows, setFlows] = useState<Flow[]>([]);
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null);
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [view, setView] = useState<"flows" | "agents" | "settings" | "dashboard" | "notifications">("dashboard");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [showAgentForm, setShowAgentForm] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [taskPrefill, setTaskPrefill] = useState<Partial<TaskPrefill> | null>(null);
  const [showNewFlowModal, setShowNewFlowModal] = useState(false);
  const [selectedTaskDetail, setSelectedTaskDetail] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    const data = await api.tasks.list(selectedFlow || undefined);
    setTasks(data);
  }, [selectedFlow]);

  const loadFlows = useCallback(async () => {
    const data = await api.flows.list();
    setFlows(data);
  }, []);

  const loadAgents = useCallback(async () => {
    const data = await api.agents.list();
    setAgents(data);
  }, []);

  useEffect(() => {
    loadTasks();
    loadFlows();
    loadAgents();
  }, [loadTasks, loadFlows, loadAgents]);

  // Load settings (theme + notification prefs) on startup
  useEffect(() => {
    api.settings.get().then((s) => {
      setSettings(s);
      document.documentElement.setAttribute("data-theme", s.theme || "dark");
    }).catch(() => {});
  }, []);

  const notifications = useNotifications(settings);

  // Real-time updates
  useEffect(() => {
    function onTaskUpdated(data: { id: string; latest_run_status: string }) {
      loadTasks();
    }

    socket.on("task:updated", onTaskUpdated);
    return () => {
      socket.off("task:updated", onTaskUpdated);
    };
  }, [loadTasks]);

  // Poll every 5s for fresh data
  useEffect(() => {
    const interval = setInterval(loadTasks, 5000);
    return () => clearInterval(interval);
  }, [loadTasks]);

  async function handleCancel(id: string) {
    await api.tasks.cancel(id);
    loadTasks();
  }

  async function handleDelete(id: string) {
    await api.tasks.delete(id);
    loadTasks();
  }

  async function handleTrigger(id: string) {
    await api.tasks.trigger(id);
    loadTasks();
  }

  async function handleRetryTask(id: string) {
    await api.tasks.retry(id);
    loadTasks();
  }

  async function handleRetryFlow(id: string) {
    await api.flows.retry(id);
    loadTasks();
  }

  async function handleResumeFlow(id: string) {
    await api.flows.resume(id);
    loadTasks();
  }

  function handleSpawnFromAgent(agent: Agent) {
    setTaskPrefill({
      title: "",
      prompt: "",
      model: agent.default_model,
      workDir: agent.default_work_dir,
      flowId: agent.default_flow_id || "__new__",
      permissions: agent.default_permissions,
      agentId: agent.id,
    });
    setShowTaskForm(true);
    setView("flows");
  }

  function handleEditAgent(agent: Agent) {
    setEditingAgent(agent);
    setShowAgentForm(true);
  }

  async function handleDeleteAgent(id: string) {
    await api.agents.delete(id);
    loadAgents();
  }

  function handleQuickTask() {
    setTaskPrefill({
      flowId: "__new__",
    });
    setShowTaskForm(true);
  }

  return (
    <div className="app">
      <Header
        view={view}
        onViewChange={(v) => {
          setView(v);
          if (v === "flows") setSelectedFlow(null);
        }}
        notifications={notifications.items}
        unreadCount={notifications.unreadCount}
        onMarkNotificationRead={notifications.markRead}
        onMarkAllNotificationsRead={notifications.markAllRead}
        onSelectTaskFromNotification={(taskId) => {
          setSelectedTaskDetail(taskId);
          setView("flows");
        }}
        onViewAllNotifications={() => setView("notifications")}
      />
      <div className="main-layout">
        {view === "flows" && selectedFlow && !selectedTaskDetail && (
          <Sidebar
            flows={flows}
            selectedFlow={selectedFlow}
            onSelectFlow={setSelectedFlow}
            onFlowsChange={loadFlows}
            tasks={tasks}
            view={view}
            agents={agents}
            onNewTask={() => {
              setTaskPrefill(null);
              setShowTaskForm(true);
            }}
            onNewAgent={() => {
              setEditingAgent(null);
              setShowAgentForm(true);
            }}
            onSpawnAgent={handleSpawnFromAgent}
            onEditAgent={handleEditAgent}
            onTriggerFlow={async (id) => {
              await api.flows.trigger(id);
              loadTasks();
            }}
            onRetryFlow={handleRetryFlow}
            onResumeFlow={handleResumeFlow}
            onNewFlow={() => setShowNewFlowModal(true)}
            onQuickTask={handleQuickTask}
          />
        )}
        <main className="content">
          {selectedTaskDetail ? (
            <TaskDetailPage
              taskId={selectedTaskDetail}
              onBack={() => setSelectedTaskDetail(null)}
              onCancel={handleCancel}
              onDelete={handleDelete}
              onTrigger={handleTrigger}
              onRetryTask={handleRetryTask}
            />
          ) : view === "settings" ? (
            <SettingsPage onSettingsChanged={setSettings} />
          ) : view === "dashboard" ? (
            <DashboardPage onSelectTask={setSelectedTaskDetail} />
          ) : view === "notifications" ? (
            <NotificationsPage
              onBack={() => setView("dashboard")}
              onSelectTask={(taskId) => {
                setSelectedTaskDetail(taskId);
                setView("flows");
              }}
            />
          ) : view === "agents" ? (
            <AgentList
              agents={agents}
              onSpawn={handleSpawnFromAgent}
              onEdit={handleEditAgent}
              onDelete={handleDeleteAgent}
              onNewAgent={() => {
                setEditingAgent(null);
                setShowAgentForm(true);
              }}
            />
          ) : selectedFlow ? (
            <TaskFlowView
              selectedFlow={selectedFlow}
              onCancel={handleCancel}
              onDelete={handleDelete}
              onTrigger={handleTrigger}
              onRetryTask={handleRetryTask}
              onRetryFlow={handleRetryFlow}
              onResumeFlow={handleResumeFlow}
              onViewTaskDetail={setSelectedTaskDetail}
            />
          ) : (
            <FlowDashboard
              flows={flows}
              tasks={tasks}
              onSelectFlow={setSelectedFlow}
              onNewFlow={() => setShowNewFlowModal(true)}
              onFlowsChange={loadFlows}
            />
          )}
        </main>
      </div>
      {showTaskForm && (
        <TaskForm
          flows={flows}
          tasks={tasks}
          selectedFlow={selectedFlow}
          onClose={() => {
            setShowTaskForm(false);
            setTaskPrefill(null);
          }}
          onCreated={() => {
            loadTasks();
            loadFlows();
          }}
          prefill={taskPrefill}
        />
      )}
      {showNewFlowModal && (
        <NewFlowModal
          onClose={() => setShowNewFlowModal(false)}
          onCreated={(flowId) => {
            loadFlows();
            setSelectedFlow(flowId);
          }}
        />
      )}
      {showAgentForm && (
        <AgentForm
          flows={flows}
          agent={editingAgent}
          onClose={() => {
            setShowAgentForm(false);
            setEditingAgent(null);
          }}
          onSaved={loadAgents}
        />
      )}
    </div>
  );
}
