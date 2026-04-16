import React from "react";
import { AppNotification } from "../api";

interface Props {
  items: AppNotification[];
  unreadCount: number;
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  onSelectTask?: (taskId: string) => void;
  onClose: () => void;
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

export default function NotificationDropdown({
  items,
  unreadCount,
  onMarkRead,
  onMarkAllRead,
  onSelectTask,
  onClose,
}: Props) {
  return (
    <div className="notification-dropdown">
      <div className="notification-dropdown-header">
        <span>Notifications</span>
        {unreadCount > 0 && (
          <button className="btn-link" onClick={onMarkAllRead}>
            Mark all read
          </button>
        )}
      </div>
      {items.length === 0 ? (
        <div className="notification-empty">You're all caught up.</div>
      ) : (
        <ul className="notification-list">
          {items.map((n) => (
            <li
              key={n.id}
              className={`notification-item notification-${n.severity}${
                n.read_at ? "" : " unread"
              }`}
              onClick={() => {
                if (!n.read_at) onMarkRead(n.id);
                if (n.task_id && onSelectTask) {
                  onSelectTask(n.task_id);
                  onClose();
                }
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
