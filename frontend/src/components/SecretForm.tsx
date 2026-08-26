import React, { useState } from "react";
import { api, Secret } from "../api";

interface Props {
  secret: Secret | null;
  onClose: () => void;
  onSaved: () => void;
}

export default function SecretForm({ secret, onClose, onSaved }: Props) {
  const [key, setKey] = useState(secret?.key || "");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState(secret?.description || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEdit = !!secret;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!key.trim() || (!isEdit && !value.trim())) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = isEdit
        ? await api.secrets.update(secret!.id, {
            ...(value.trim() ? { value: value.trim() } : {}),
            description: description.trim(),
          })
        : await api.secrets.create({
            key: key.trim(),
            value: value.trim(),
            description: description.trim(),
          });

      if (result && typeof result === "object" && "error" in result) {
        setError((result as unknown as { error: string }).error);
        return;
      }
      onSaved();
      onClose();
    } catch (err) {
      console.error(err);
      setError("Something went wrong — see console for details.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{isEdit ? "Edit Secret" : "New Secret"}</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Key</label>
            <input
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="e.g. GITHUB_TOKEN"
              disabled={isEdit}
              autoFocus={!isEdit}
              style={{ fontFamily: "var(--font-mono, monospace)" }}
            />
            <p className="field-hint">
              This is the environment variable name the agent sees. Uppercase letters,
              digits, and underscores only. Can't be changed after creation.
            </p>
          </div>

          <div className="form-group">
            <label>Value {isEdit && "(leave blank to keep the current value)"}</label>
            <input
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={isEdit ? "•••••••••••••" : "Paste the secret value"}
              autoFocus={isEdit}
              autoComplete="new-password"
            />
            <p className="field-hint">
              Stored encrypted. Never shown again after saving — you'll need the original
              value to rotate it later.
            </p>
          </div>

          <div className="form-group">
            <label>Description (optional)</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this secret is for"
            />
          </div>

          {error && <p className="form-error">{error}</p>}

          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || !key.trim() || (!isEdit && !value.trim())}
            >
              {submitting ? "Saving..." : isEdit ? "Save Changes" : "Create Secret"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
