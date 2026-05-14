import React from "react";
import { Agent } from "../api";
import AgentCard from "./AgentCard";

interface Props {
  agents: Agent[];
  onSpawn: (agent: Agent) => void;
  onEdit: (agent: Agent) => void;
  onDelete: (id: string) => void;
  onNewAgent: () => void;
}

export default function AgentList({ agents, onSpawn, onEdit, onDelete, onNewAgent }: Props) {
  if (!agents.length) {
    return (
      <div className="agent-list-page">
        <div className="agent-list-header">
          <div>
            <h2 className="agent-list-title">Agents</h2>
            <p className="agent-list-subtitle">0 agents</p>
          </div>
          <button className="btn btn-primary" onClick={onNewAgent}>
            + New Agent
          </button>
        </div>
        <div className="empty-state">
          <p>No agents yet</p>
          <p className="text-muted">
            Create pre-configured agents with instructions and context to quickly spawn tasks.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="agent-list-page">
      <div className="agent-list-header">
        <div>
          <h2 className="agent-list-title">Agents</h2>
          <p className="agent-list-subtitle">
            {agents.length} agent{agents.length !== 1 ? "s" : ""}
          </p>
        </div>
        <button className="btn btn-primary" onClick={onNewAgent}>
          + New Agent
        </button>
      </div>
      <div className="agent-grid">
        {agents.map((a) => (
          <AgentCard
            key={a.id}
            agent={a}
            onSpawn={onSpawn}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  );
}
