import React, { useCallback, useEffect, useState } from "react";
import { api, Secret } from "../api";
import SecretForm from "./SecretForm";

function formatDate(iso: string): string {
  try {
    return new Date(iso + "Z").toLocaleString();
  } catch {
    return iso;
  }
}

export default function SecretsPage() {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Secret | null>(null);

  const load = useCallback(async () => {
    const data = await api.secrets.list();
    setSecrets(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete(secret: Secret) {
    if (!window.confirm(`Delete secret "${secret.key}"? Tasks referencing it will stop receiving it.`)) {
      return;
    }
    await api.secrets.delete(secret.id);
    load();
  }

  if (loading) {
    return (
      <div className="agent-list-page">
        <div className="settings-loading">Loading secrets...</div>
      </div>
    );
  }

  return (
    <div className="agent-list-page">
      <div className="agent-list-header">
        <div>
          <h2 className="agent-list-title">Secrets</h2>
          <p className="agent-list-subtitle">
            {secrets.length} secret{secrets.length !== 1 ? "s" : ""} — encrypted at rest, injected as
            environment variables into tasks that opt in
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => {
            setEditing(null);
            setShowForm(true);
          }}
        >
          + New Secret
        </button>
      </div>

      {secrets.length === 0 ? (
        <div className="empty-state">
          <p>No secrets yet</p>
          <p className="text-muted">
            Store API keys and tokens once, then grant individual tasks or agents access to
            them by name — no more pasting credentials into prompts or work directories.
          </p>
        </div>
      ) : (
        <div className="secrets-table">
          <div className="secrets-table-header">
            <span>Key</span>
            <span>Description</span>
            <span>Updated</span>
            <span />
          </div>
          {secrets.map((s) => (
            <div key={s.id} className="secrets-table-row">
              <span className="secrets-key">{s.key}</span>
              <span className="secrets-description">{s.description || "—"}</span>
              <span className="secrets-updated">{formatDate(s.updated_at)}</span>
              <span className="secrets-actions">
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => {
                    setEditing(s);
                    setShowForm(true);
                  }}
                >
                  Edit
                </button>
                <button
                  className="btn btn-sm btn-danger"
                  onClick={() => handleDelete(s)}
                >
                  Delete
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <SecretForm
          secret={editing}
          onClose={() => {
            setShowForm(false);
            setEditing(null);
          }}
          onSaved={load}
        />
      )}
    </div>
  );
}
