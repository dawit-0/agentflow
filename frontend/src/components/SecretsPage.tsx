import React, { useEffect, useState } from "react";
import { api, Secret } from "../api";

export default function SecretsPage() {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [rotatingId, setRotatingId] = useState<string | null>(null);
  const [rotateValue, setRotateValue] = useState("");
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const data = await api.secrets.list();
      setSecrets(data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !value.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const result: any = await api.secrets.create({
        name: name.trim(),
        value: value.trim(),
        description: description.trim(),
      });
      if (result?.error) {
        setError(result.error);
        return;
      }
      setName("");
      setValue("");
      setDescription("");
      await load();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRotate(id: string) {
    if (!rotateValue.trim()) return;
    await api.secrets.update(id, { value: rotateValue.trim() });
    setRotatingId(null);
    setRotateValue("");
    await load();
  }

  async function handleDelete(id: string) {
    await api.secrets.delete(id);
    setConfirmingDeleteId(null);
    await load();
  }

  return (
    <div className="settings-page">
      <div className="settings-container">
        <div className="settings-header">
          <h2>Secrets</h2>
          <p className="settings-subtitle">
            Store credentials once, then reference them by name from a task or agent.
            Values are encrypted at rest and injected as environment variables into
            the run only — they are never shown again, logged, or included in a
            prompt.
          </p>
        </div>

        <div className="settings-sections">
          <div className="settings-section">
            <div className="settings-section-header">
              <h3>New Secret</h3>
            </div>
            <form onSubmit={handleCreate} className="settings-field">
              <label className="settings-label">Name</label>
              <p className="settings-description">
                Used as the environment variable name, e.g. <code>GITHUB_TOKEN</code>.
              </p>
              <input
                className="settings-input"
                value={name}
                onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"))}
                placeholder="GITHUB_TOKEN"
                autoComplete="off"
              />

              <label className="settings-label" style={{ marginTop: 14 }}>Value</label>
              <p className="settings-description">Write-only — you won't be able to view it again.</p>
              <input
                className="settings-input"
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="secret value"
                autoComplete="new-password"
              />

              <label className="settings-label" style={{ marginTop: 14 }}>Description (optional)</label>
              <input
                className="settings-input"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this credential is for"
              />

              {error && (
                <p className="field-hint" style={{ color: "var(--danger)" }}>{error}</p>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                style={{ marginTop: 14 }}
                disabled={submitting || !name.trim() || !value.trim()}
              >
                {submitting ? "Adding..." : "Add Secret"}
              </button>
            </form>
          </div>

          <div className="settings-section">
            <div className="settings-section-header">
              <h3>Stored Secrets ({secrets.length})</h3>
            </div>
            {loading ? (
              <div className="settings-loading">Loading...</div>
            ) : secrets.length === 0 ? (
              <div className="sidebar-empty-hint">
                No secrets yet. Add one above, then attach it to a task or agent from
                the "Secrets" section of its form.
              </div>
            ) : (
              <div className="secrets-list">
                {secrets.map((s) => (
                  <div key={s.id} className="secrets-list-item">
                    <div className="secrets-list-main">
                      <code className="secrets-list-name">{s.name}</code>
                      {s.description && (
                        <span className="secrets-list-desc">{s.description}</span>
                      )}
                    </div>
                    {rotatingId === s.id ? (
                      <div className="secrets-list-rotate">
                        <input
                          className="settings-input"
                          type="password"
                          value={rotateValue}
                          onChange={(e) => setRotateValue(e.target.value)}
                          placeholder="new value"
                          autoFocus
                        />
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => handleRotate(s.id)}
                          disabled={!rotateValue.trim()}
                        >
                          Save
                        </button>
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => {
                            setRotatingId(null);
                            setRotateValue("");
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : confirmingDeleteId === s.id ? (
                      <div className="secrets-list-rotate">
                        <span className="field-hint">Delete this secret?</span>
                        <button
                          className="btn btn-sm sidebar-action-danger"
                          onClick={() => handleDelete(s.id)}
                        >
                          Confirm
                        </button>
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => setConfirmingDeleteId(null)}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="secrets-list-actions">
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => {
                            setRotatingId(s.id);
                            setRotateValue("");
                          }}
                        >
                          Rotate
                        </button>
                        <button
                          className="btn btn-sm btn-danger-icon"
                          onClick={() => setConfirmingDeleteId(s.id)}
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
