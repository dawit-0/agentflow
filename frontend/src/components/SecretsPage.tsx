import React, { useEffect, useState } from "react";
import { api, Secret } from "../api";

const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

export default function SecretsPage() {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [rotatingId, setRotatingId] = useState<string | null>(null);
  const [rotateValue, setRotateValue] = useState("");
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setSecrets(await api.secrets.list());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function resetForm() {
    setName("");
    setValue("");
    setDescription("");
    setError(null);
    setShowForm(false);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !value) return;
    if (!NAME_RE.test(name.trim())) {
      setError("Name must look like an env var: letters, digits, underscores, not starting with a digit.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.secrets.create({
        name: name.trim(),
        value,
        description: description.trim(),
      });
      if ((result as any)?.error) {
        setError((result as any).error);
        return;
      }
      resetForm();
      load();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRotate(id: string) {
    if (!rotateValue) return;
    await api.secrets.update(id, { value: rotateValue });
    setRotatingId(null);
    setRotateValue("");
    load();
  }

  async function handleDelete(id: string) {
    await api.secrets.delete(id);
    setConfirmingDeleteId(null);
    load();
  }

  return (
    <div className="settings-page">
      <div className="settings-container">
        <div className="settings-header">
          <h2>Secrets</h2>
          <p className="settings-subtitle">
            Store API keys, tokens, and credentials once, then inject them as environment
            variables into specific tasks and agents — never paste them into a prompt.
          </p>
        </div>

        <div className="settings-sections">
          <div className="settings-section">
            <div
              className="settings-section-header"
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
            >
              <h3 style={{ marginBottom: 0 }}>Vault</h3>
              {!showForm && (
                <button className="btn btn-sm btn-primary" onClick={() => setShowForm(true)}>
                  + New Secret
                </button>
              )}
            </div>

            {showForm && (
              <form className="secrets-form" onSubmit={handleCreate}>
                <div className="form-group">
                  <label>Name</label>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value.toUpperCase())}
                    placeholder="GITHUB_TOKEN"
                    autoFocus
                  />
                  <p className="field-hint">
                    This becomes the environment variable name inside the run.
                  </p>
                </div>
                <div className="form-group">
                  <label>Value</label>
                  <input
                    type="password"
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    placeholder="Paste the secret value"
                    autoComplete="off"
                  />
                </div>
                <div className="form-group">
                  <label>Description (optional)</label>
                  <input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What this key is for"
                  />
                </div>
                {error && <p className="secrets-error">{error}</p>}
                <div className="form-actions">
                  <button type="button" className="btn btn-secondary" onClick={resetForm}>
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={submitting || !name.trim() || !value}
                  >
                    {submitting ? "Saving..." : "Save Secret"}
                  </button>
                </div>
              </form>
            )}

            {loading ? (
              <div className="settings-loading">Loading secrets...</div>
            ) : secrets.length === 0 ? (
              <div className="sidebar-empty-hint">
                No secrets yet. Add one to make it available for tasks and agents to use.
              </div>
            ) : (
              <div className="secrets-list">
                {secrets.map((s) => (
                  <div key={s.id} className="secrets-item">
                    <div className="secrets-item-main">
                      <span className="secrets-item-name">{s.name}</span>
                      {s.description && (
                        <span className="secrets-item-desc">{s.description}</span>
                      )}
                      <span className="secrets-item-meta">
                        {s.last_used_at ? `Last used ${new Date(s.last_used_at).toLocaleString()}` : "Never used"}
                        {" · "}Updated {new Date(s.updated_at).toLocaleDateString()}
                      </span>
                    </div>
                    <div className="secrets-item-actions">
                      {rotatingId === s.id ? (
                        <>
                          <input
                            type="password"
                            className="settings-input"
                            value={rotateValue}
                            onChange={(e) => setRotateValue(e.target.value)}
                            placeholder="New value"
                            autoFocus
                          />
                          <button
                            className="btn btn-sm btn-primary"
                            onClick={() => handleRotate(s.id)}
                            disabled={!rotateValue}
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
                        </>
                      ) : confirmingDeleteId === s.id ? (
                        <>
                          <span className="sidebar-delete-confirm-text">Delete?</span>
                          <button
                            className="btn btn-sm btn-danger"
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
                        </>
                      ) : (
                        <>
                          <button
                            className="btn btn-sm btn-secondary"
                            onClick={() => setRotatingId(s.id)}
                          >
                            Rotate
                          </button>
                          <button
                            className="btn btn-sm btn-danger"
                            onClick={() => setConfirmingDeleteId(s.id)}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </div>
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
