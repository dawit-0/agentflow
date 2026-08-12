import React, { useEffect, useState } from "react";
import { api, Secret } from "../api";

function isError(result: Secret | { detail: string }): result is { detail: string } {
  return (result as { detail?: string }).detail !== undefined;
}

function placeholder(name: string): string {
  return `{{secret.${name}}}`;
}

function formatRelative(iso: string | null): string {
  if (!iso) return "Never used";
  const date = new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "Used just now";
  if (mins < 60) return `Used ${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `Used ${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `Used ${days}d ago`;
}

export default function SecretsPanel() {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  function load() {
    api.secrets.list().then((s) => {
      setSecrets(s);
      setLoading(false);
    });
  }

  useEffect(load, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !value.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const result = await api.secrets.create({
        name: name.trim(),
        description: description.trim(),
        value,
      });
      if (isError(result)) {
        setError(result.detail);
        return;
      }
      setName("");
      setDescription("");
      setValue("");
      setShowAdd(false);
      load();
    } finally {
      setSaving(false);
    }
  }

  async function handleRotate(id: string) {
    if (!editValue.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const result = await api.secrets.update(id, { value: editValue });
      if (isError(result)) {
        setError(result.detail);
        return;
      }
      setEditingId(null);
      setEditValue("");
      load();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete secret "${name}"? Any task prompt still referencing {{secret.${name}}} will fail.`)) {
      return;
    }
    await api.secrets.delete(id);
    load();
  }

  function handleCopy(id: string, name: string) {
    navigator.clipboard?.writeText(placeholder(name));
    setCopiedId(id);
    setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1500);
  }

  return (
    <div className="settings-section">
      <div className="settings-section-header">
        <h3>Secrets</h3>
      </div>
      <p className="settings-description">
        Store API keys and tokens once, encrypted at rest, and reference them from any task
        prompt with <code>{"{{secret.NAME}}"}</code>. The placeholder is expanded right before
        the run starts and is never saved back to the prompt — if the agent's output echoes the
        value, it's masked before it's logged.
      </p>

      {error && <div className="secrets-error">{error}</div>}

      {loading ? (
        <p className="settings-description">Loading...</p>
      ) : (
        <div className="secret-list">
          {secrets.length === 0 && !showAdd && (
            <p className="settings-description">No secrets yet.</p>
          )}
          {secrets.map((s) => (
            <div key={s.id} className="secret-row">
              <div className="secret-row-main">
                <button
                  type="button"
                  className="secret-name-badge"
                  onClick={() => handleCopy(s.id, s.name)}
                  title="Click to copy the {{secret.NAME}} reference"
                >
                  {copiedId === s.id ? "Copied!" : placeholder(s.name)}
                </button>
                {s.description && <span className="secret-description">{s.description}</span>}
              </div>
              <div className="secret-row-meta">
                <span>{formatRelative(s.last_used_at)}</span>
                <button
                  type="button"
                  className="btn-link"
                  onClick={() => {
                    setEditingId(editingId === s.id ? null : s.id);
                    setEditValue("");
                    setError(null);
                  }}
                >
                  Rotate
                </button>
                <button
                  type="button"
                  className="btn-link secret-delete-link"
                  onClick={() => handleDelete(s.id, s.name)}
                >
                  Delete
                </button>
              </div>
              {editingId === s.id && (
                <div className="secret-rotate-row">
                  <input
                    type="password"
                    className="settings-input"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    placeholder="New value"
                    autoFocus
                  />
                  <button
                    type="button"
                    className="settings-save-btn"
                    disabled={saving || !editValue.trim()}
                    onClick={() => handleRotate(s.id)}
                  >
                    Save
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {showAdd ? (
        <form className="secret-add-form" onSubmit={handleAdd}>
          <div className="settings-input-row">
            <input
              className="settings-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="NAME (e.g. GITHUB_TOKEN)"
              autoFocus
            />
          </div>
          <div className="settings-input-row">
            <input
              className="settings-input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Description (optional)"
            />
          </div>
          <div className="settings-input-row">
            <input
              type="password"
              className="settings-input"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Value"
            />
          </div>
          <div className="secret-add-actions">
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => {
                setShowAdd(false);
                setError(null);
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="settings-save-btn"
              disabled={saving || !name.trim() || !value.trim()}
            >
              {saving ? "Saving..." : "Add secret"}
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="btn btn-sm" onClick={() => setShowAdd(true)}>
          + Add secret
        </button>
      )}
    </div>
  );
}
