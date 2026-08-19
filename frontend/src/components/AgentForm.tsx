import React, { useState, useEffect } from "react";
import { api, Flow, Agent, Model, ContextItem, Permissions, PERMISSION_PRESETS, Secret } from "../api";

interface Props {
  flows: Flow[];
  agent: Agent | null;
  onClose: () => void;
  onSaved: () => void;
}

const FALLBACK_MODELS: Model[] = [
  { value: "claude-sonnet-4-20250514", label: "Claude Sonnet", provider: "claude" },
  { value: "claude-opus-4-20250514", label: "Claude Opus", provider: "claude" },
  { value: "claude-haiku-3-5-20241022", label: "Claude Haiku", provider: "claude" },
];

export default function AgentForm({ flows, agent, onClose, onSaved }: Props) {
  const [models, setModels] = useState<Model[]>(FALLBACK_MODELS);
  const [name, setName] = useState(agent?.name || "");
  const [description, setDescription] = useState(agent?.description || "");
  const [instructions, setInstructions] = useState(agent?.instructions || "");
  const [context, setContext] = useState<ContextItem[]>(agent?.context || []);
  const [defaultModel, setDefaultModel] = useState(agent?.default_model || FALLBACK_MODELS[0].value);

  useEffect(() => {
    api.models.list().then(setModels).catch(() => {});
  }, []);
  const [permissions, setPermissions] = useState<Permissions>(
    agent?.default_permissions?.preset
      ? agent.default_permissions
      : PERMISSION_PRESETS["standard"]
  );
  const [showPermDetails, setShowPermDetails] = useState(false);
  const [defaultWorkDir, setDefaultWorkDir] = useState(agent?.default_work_dir || "");
  const [defaultFlowId, setDefaultFlowId] = useState(agent?.default_flow_id || "");
  const [defaultSandbox, setDefaultSandbox] = useState<"" | "docker">(
    (agent?.default_sandbox as "" | "docker") || ""
  );
  const [secrets, setSecrets] = useState<Secret[]>([]);
  useEffect(() => {
    api.secrets.list().then(setSecrets).catch(() => {});
  }, []);
  const [defaultSecretNames, setDefaultSecretNames] = useState<string[]>(
    agent?.default_secret_names || []
  );
  const [submitting, setSubmitting] = useState(false);

  function addContextItem(type: "file" | "url" | "text") {
    const item: ContextItem = { type };
    if (type === "file") item.path = "";
    else if (type === "url") item.url = "";
    else item.content = "";
    setContext([...context, item]);
  }

  function updateContextItem(index: number, update: Partial<ContextItem>) {
    setContext(context.map((item, i) => (i === index ? { ...item, ...update } : item)));
  }

  function removeContextItem(index: number) {
    setContext(context.filter((_, i) => i !== index));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      const data = {
        name: name.trim(),
        description: description.trim(),
        instructions: instructions.trim(),
        context,
        default_model: defaultModel,
        default_permissions: permissions,
        default_work_dir: defaultWorkDir.trim(),
        default_flow_id: defaultFlowId || undefined,
        default_sandbox: defaultSandbox,
        default_secret_names: defaultSecretNames,
      };
      if (agent) {
        await api.agents.update(agent.id, data);
      } else {
        await api.agents.create(data);
      }
      onSaved();
      onClose();
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>{agent ? "Edit Agent" : "New Agent"}</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Code Reviewer, API Docs Writer"
              autoFocus
            />
          </div>

          <div className="form-group">
            <label>Description</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of what this agent does"
            />
          </div>

          <div className="form-group">
            <label>Instructions</label>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Persona and instructions for the agent..."
              className="textarea-tall"
            />
          </div>

          <div className="form-group">
            <label>Context</label>
            <div className="context-list">
              {context.map((item, i) => (
                <div key={i} className="context-item">
                  <span className="context-type-badge">{item.type}</span>
                  {item.type === "file" && (
                    <input
                      value={item.path || ""}
                      onChange={(e) => updateContextItem(i, { path: e.target.value })}
                      placeholder="/path/to/document.md"
                    />
                  )}
                  {item.type === "url" && (
                    <input
                      value={item.url || ""}
                      onChange={(e) => updateContextItem(i, { url: e.target.value })}
                      placeholder="https://docs.example.com/api"
                    />
                  )}
                  {item.type === "text" && (
                    <textarea
                      value={item.content || ""}
                      onChange={(e) => updateContextItem(i, { content: e.target.value })}
                      placeholder="Reference text or notes..."
                      className="textarea-short"
                    />
                  )}
                  <button
                    type="button"
                    className="btn-icon btn-danger-icon"
                    onClick={() => removeContextItem(i)}
                    title="Remove"
                  >
                    x
                  </button>
                </div>
              ))}
            </div>
            <div className="context-add-buttons">
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => addContextItem("file")}>
                + File
              </button>
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => addContextItem("url")}>
                + URL
              </button>
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => addContextItem("text")}>
                + Text
              </button>
            </div>
          </div>

          <div className="form-group">
            <label>Default Model</label>
            <select value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)}>
              {Object.entries(
                models.reduce<Record<string, Model[]>>((groups, m) => {
                  (groups[m.provider] ??= []).push(m);
                  return groups;
                }, {})
              ).map(([provider, group]) => (
                <optgroup key={provider} label={provider === "claude" ? "Anthropic" : "OpenAI"}>
                  {group.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>Default Working Directory (optional)</label>
            <input
              value={defaultWorkDir}
              onChange={(e) => setDefaultWorkDir(e.target.value)}
              placeholder="/path/to/project"
            />
          </div>

          <div className="form-group">
            <label>Default Flow (optional)</label>
            <select value={defaultFlowId} onChange={(e) => setDefaultFlowId(e.target.value)}>
              <option value="">None</option>
              {flows.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>Default Sandbox</label>
            <select
              value={defaultSandbox}
              onChange={(e) => setDefaultSandbox(e.target.value as "" | "docker")}
            >
              <option value="">Inherit global setting</option>
              <option value="docker">Docker — disposable container</option>
            </select>
          </div>

          <div className="form-group">
            <label>Default Permissions</label>
            <div className="permission-presets">
              {Object.entries(PERMISSION_PRESETS).map(([key, preset]) => (
                <button
                  key={key}
                  type="button"
                  className={`btn btn-sm permission-preset-btn${
                    permissions.preset === key ? " active" : ""
                  }`}
                  onClick={() => setPermissions(preset)}
                >
                  {key === "read-only" ? "Read Only" : key === "standard" ? "Standard" : "Full Access"}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="btn-link"
              onClick={() => setShowPermDetails(!showPermDetails)}
            >
              {showPermDetails ? "Hide details" : "Show details"}
            </button>
            {showPermDetails && (
              <div className="permission-details">
                {(
                  [
                    ["file_read", "File Read"],
                    ["file_write", "File Write"],
                    ["bash", "Shell Commands"],
                    ["web_search", "Web Search"],
                    ["mcp", "MCP Tools"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="permission-toggle">
                    <input
                      type="checkbox"
                      checked={permissions[key]}
                      onChange={(e) =>
                        setPermissions({
                          ...permissions,
                          preset: "custom",
                          [key]: e.target.checked,
                        })
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
            )}
          </div>

          {secrets.length > 0 && (
            <div className="form-group">
              <label>Default Secrets (optional)</label>
              <div className="depends-on-list">
                {secrets.map((s) => (
                  <label key={s.id} className="permission-toggle">
                    <input
                      type="checkbox"
                      checked={defaultSecretNames.includes(s.name)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setDefaultSecretNames([...defaultSecretNames, s.name]);
                        } else {
                          setDefaultSecretNames(defaultSecretNames.filter((n) => n !== s.name));
                        }
                      }}
                    />
                    <span>{s.name}</span>
                  </label>
                ))}
              </div>
              <p className="field-hint">
                Tasks spawned from this agent get these secrets as environment variables by default.
              </p>
            </div>
          )}

          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || !name.trim()}
            >
              {submitting ? "Saving..." : agent ? "Save Changes" : "Create Agent"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
