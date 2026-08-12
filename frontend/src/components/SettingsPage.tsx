import React, { useEffect, useState } from "react";
import { api, Settings } from "../api";
import {
  desktopPermission,
  requestDesktopPermission,
} from "../lib/desktopNotifications";
import SecretsPanel from "./SecretsPanel";

interface Props {
  onSettingsChanged?: (settings: Settings) => void;
}

export default function SettingsPage({ onSettingsChanged }: Props = {}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [workDirDraft, setWorkDirDraft] = useState("");
  const [imageDraft, setImageDraft] = useState("");
  const [permission, setPermission] = useState<string>(desktopPermission());

  useEffect(() => {
    api.settings.get().then((s) => {
      setSettings(s);
      setWorkDirDraft(s.default_work_dir);
      setImageDraft(s.sandbox_image);
    });
  }, []);

  async function updateSetting(patch: Partial<Settings>) {
    const key = Object.keys(patch)[0];
    setSaving(key);
    try {
      const updated = await api.settings.update(patch);
      setSettings(updated);
      onSettingsChanged?.(updated);

      // Apply theme immediately
      if (patch.theme) {
        document.documentElement.setAttribute("data-theme", patch.theme);
      }
    } finally {
      setSaving(null);
    }
  }

  async function handleEnableDesktop() {
    const result = await requestDesktopPermission();
    setPermission(result);
    if (result === "granted") {
      await updateSetting({ notify_desktop_enabled: true });
    }
  }

  if (!settings) {
    return (
      <div className="settings-page">
        <div className="settings-loading">Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="settings-page">
      <div className="settings-container">
        <div className="settings-header">
          <h2>Settings</h2>
          <p className="settings-subtitle">Configure your local AgentFlow instance</p>
        </div>

        <div className="settings-sections">
          {/* Theme */}
          <div className="settings-section">
            <div className="settings-section-header">
              <h3>Appearance</h3>
            </div>
            <div className="settings-field">
              <label className="settings-label">Theme</label>
              <p className="settings-description">Choose between dark and light mode</p>
              <div className="settings-toggle-group">
                <button
                  className={`settings-toggle-btn ${settings.theme === "dark" ? "active" : ""}`}
                  onClick={() => updateSetting({ theme: "dark" })}
                  disabled={saving === "theme"}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                  </svg>
                  Dark
                </button>
                <button
                  className={`settings-toggle-btn ${settings.theme === "light" ? "active" : ""}`}
                  onClick={() => updateSetting({ theme: "light" })}
                  disabled={saving === "theme"}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="5" />
                    <line x1="12" y1="1" x2="12" y2="3" />
                    <line x1="12" y1="21" x2="12" y2="23" />
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                    <line x1="1" y1="12" x2="3" y2="12" />
                    <line x1="21" y1="12" x2="23" y2="12" />
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                  </svg>
                  Light
                </button>
              </div>
            </div>
          </div>

          {/* Default Working Directory */}
          <div className="settings-section">
            <div className="settings-section-header">
              <h3>Defaults</h3>
            </div>
            <div className="settings-field">
              <label className="settings-label">Default Working Directory</label>
              <p className="settings-description">
                Base directory for task execution. Used when a task doesn't specify its own.
              </p>
              <div className="settings-input-row">
                <input
                  type="text"
                  className="settings-input"
                  value={workDirDraft}
                  onChange={(e) => setWorkDirDraft(e.target.value)}
                  placeholder="/home/user/projects"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      updateSetting({ default_work_dir: workDirDraft });
                    }
                  }}
                />
                <button
                  className="settings-save-btn"
                  onClick={() => updateSetting({ default_work_dir: workDirDraft })}
                  disabled={saving === "default_work_dir" || workDirDraft === settings.default_work_dir}
                >
                  {saving === "default_work_dir" ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>

          {/* Max Concurrent Runs */}
          <div className="settings-section">
            <div className="settings-section-header">
              <h3>Performance</h3>
            </div>
            <div className="settings-field">
              <label className="settings-label">Max Concurrent Runs</label>
              <p className="settings-description">
                Maximum number of tasks that can run simultaneously. Lower this if your machine is resource-constrained.
              </p>
              <div className="settings-slider-row">
                <input
                  type="range"
                  min="1"
                  max="20"
                  value={settings.max_concurrent_runs}
                  onChange={(e) => {
                    const val = parseInt(e.target.value);
                    setSettings({ ...settings, max_concurrent_runs: val });
                  }}
                  onMouseUp={(e) => {
                    updateSetting({ max_concurrent_runs: settings.max_concurrent_runs });
                  }}
                  onTouchEnd={() => {
                    updateSetting({ max_concurrent_runs: settings.max_concurrent_runs });
                  }}
                  className="settings-slider"
                />
                <span className="settings-slider-value">{settings.max_concurrent_runs}</span>
              </div>
            </div>
          </div>

          {/* Sandbox */}
          <div className="settings-section">
            <div className="settings-section-header">
              <h3>Sandbox</h3>
            </div>
            <div className="settings-field">
              <label className="settings-label">Default sandbox mode</label>
              <p className="settings-description">
                Run agents inside a Docker container by default. Each run gets its own
                disposable container with the work directory bind-mounted. Tasks can
                override this. Requires Docker on the host and a built sandbox image
                (see <code>docker/</code>).
              </p>
              <div className="settings-toggle-group">
                <button
                  className={`settings-toggle-btn ${settings.default_sandbox === "" ? "active" : ""}`}
                  onClick={() => updateSetting({ default_sandbox: "" })}
                  disabled={saving === "default_sandbox"}
                >
                  None (host)
                </button>
                <button
                  className={`settings-toggle-btn ${settings.default_sandbox === "docker" ? "active" : ""}`}
                  onClick={() => updateSetting({ default_sandbox: "docker" })}
                  disabled={saving === "default_sandbox"}
                >
                  Docker
                </button>
              </div>
            </div>
            <div className="settings-field">
              <label className="settings-label">Sandbox image</label>
              <p className="settings-description">
                Docker image used when sandbox mode is "docker". Build the default with
                <code> bash docker/build.sh</code>.
              </p>
              <div className="settings-input-row">
                <input
                  type="text"
                  className="settings-input"
                  value={imageDraft}
                  onChange={(e) => setImageDraft(e.target.value)}
                  placeholder="agentflow/claude-sandbox:latest"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      updateSetting({ sandbox_image: imageDraft });
                    }
                  }}
                />
                <button
                  className="settings-save-btn"
                  onClick={() => updateSetting({ sandbox_image: imageDraft })}
                  disabled={saving === "sandbox_image" || imageDraft === settings.sandbox_image}
                >
                  {saving === "sandbox_image" ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>

          {/* Secrets */}
          <SecretsPanel />

          {/* Notifications */}
          <div className="settings-section">
            <div className="settings-section-header">
              <h3>Notifications</h3>
            </div>
            <div className="settings-field">
              <p className="settings-description">
                Choose which events create an in-app notification. Desktop alerts also
                require browser permission.
              </p>
              <label className="settings-checkbox">
                <input
                  type="checkbox"
                  checked={settings.notify_on_task_failure}
                  onChange={(e) =>
                    updateSetting({ notify_on_task_failure: e.target.checked })
                  }
                  disabled={saving === "notify_on_task_failure"}
                />
                <span>Notify when a task fails</span>
              </label>
              <label className="settings-checkbox">
                <input
                  type="checkbox"
                  checked={settings.notify_on_task_success}
                  onChange={(e) =>
                    updateSetting({ notify_on_task_success: e.target.checked })
                  }
                  disabled={saving === "notify_on_task_success"}
                />
                <span>Notify when a task succeeds</span>
              </label>
              <label className="settings-checkbox">
                <input
                  type="checkbox"
                  checked={settings.notify_on_flow_completion}
                  onChange={(e) =>
                    updateSetting({ notify_on_flow_completion: e.target.checked })
                  }
                  disabled={saving === "notify_on_flow_completion"}
                />
                <span>Notify when a flow completes</span>
              </label>
            </div>
            <div className="settings-field">
              <label className="settings-label">Desktop notifications</label>
              <p className="settings-description">
                Show OS-level popups when events fire. Requires browser permission.
              </p>
              <label className="settings-checkbox">
                <input
                  type="checkbox"
                  checked={settings.notify_desktop_enabled}
                  onChange={(e) =>
                    updateSetting({ notify_desktop_enabled: e.target.checked })
                  }
                  disabled={saving === "notify_desktop_enabled"}
                />
                <span>Enable desktop notifications</span>
              </label>
              {permission !== "granted" && permission !== "unsupported" && (
                <button
                  className="btn btn-sm"
                  onClick={handleEnableDesktop}
                  style={{ marginTop: 8 }}
                >
                  {permission === "denied"
                    ? "Permission denied — enable in browser settings"
                    : "Request browser permission"}
                </button>
              )}
              {permission === "unsupported" && (
                <p className="settings-description">
                  This browser does not support desktop notifications.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
