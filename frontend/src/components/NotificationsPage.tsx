import React, { useCallback, useEffect, useState } from "react";
import { AppNotification, api } from "../api";
import { socket } from "../socket";

interface Props {
  onBack: () => void;
  onSelectTask?: (taskId: string) => void;
}

function timeAgo(iso: string): string {
  const created = new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime();
  const diff = Date.now() - created;
  if (Number.isNaN(diff)) return "";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

type Filter = "all" | "unread" | "read";

export default function NotificationsPage({ onBack, onSelectTask }: Props) {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.notifications.list(false, 200);
      setItems(list);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    function onNew(ev: { notification: AppNotification }) {
      setItems((prev) => [ev.notification, ...prev]);
    }
    socket.on("notification:new", onNew);
    return () => {
      socket.off("notification:new", onNew);
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onBack();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onBack]);

  async function handleMarkRead(id: string) {
    await api.notifications.markRead(id);
    setItems((prev) =>
      prev.map((n) =>
        n.id === id && !n.read_at ? { ...n, read_at: new Date().toISOString() } : n
      )
    );
  }

  async function handleMarkAllRead() {
    await api.notifications.markAllRead();
    const now = new Date().toISOString();
    setItems((prev) => prev.map((n) => (n.read_at ? n : { ...n, read_at: now })));
  }

  const filtered = items.filter((n) => {
    if (filter === "unread") return !n.read_at;
    if (filter === "read") return !!n.read_at;
    return true;
  });

  const unreadCount = items.filter((n) => !n.read_at).length;

  return (
    <div className="notifications-page">
      <div className="notifications-page-header">
        <div className="notifications-page-title">
          <button
            className="btn btn-sm"
            onClick={onBack}
            title="Back (Esc)"
          >
            ← Back
          </button>
          <h2>Notifications</h2>
        </div>
        <div className="notifications-page-controls">
          <div className="notifications-filter">
            <button
              className={`btn btn-sm${filter === "all" ? " btn-icon-active" : ""}`}
              onClick={() => setFilter("all")}
            >
              All ({items.length})
            </button>
            <button
              className={`btn btn-sm${filter === "unread" ? " btn-icon-active" : ""}`}
              onClick={() => setFilter("unread")}
            >
              Unread ({unreadCount})
            </button>
            <button
              className={`btn btn-sm${filter === "read" ? " btn-icon-active" : ""}`}
              onClick={() => setFilter("read")}
            >
              Read ({items.length - unreadCount})
            </button>
          </div>
          {unreadCount > 0 && (
            <button className="btn btn-sm" onClick={handleMarkAllRead}>
              Mark all read
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="notifications-empty">Loading...</div>
      ) : filtered.length === 0 ? (
        <div className="notifications-empty">
          {filter === "unread"
            ? "You're all caught up."
            : filter === "read"
            ? "No read notifications."
            : "No notifications yet."}
        </div>
      ) : (
        <ul className="notifications-page-list">
          {filtered.map((n) => (
            <li
              key={n.id}
              className={`notification-item notification-${n.severity}${
                n.read_at ? "" : " unread"
              }${n.task_id ? " clickable" : ""}`}
              onClick={() => {
                if (!n.read_at) handleMarkRead(n.id);
                if (n.task_id && onSelectTask) onSelectTask(n.task_id);
              }}
            >
              <div className="notification-item-header">
                <span className="notification-item-title">{n.title}</span>
                <span className="notification-item-time">{timeAgo(n.created_at)}</span>
              </div>
              {n.body && <div className="notification-item-body">{n.body}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
