import React from "react";
import { AppNotification } from "../api";
import NotificationBell from "./NotificationBell";

export type HeaderView = "flows" | "agents" | "settings" | "dashboard" | "notifications" | "secrets";

interface Props {
  view: HeaderView;
  onViewChange: (view: HeaderView) => void;
  notifications: AppNotification[];
  unreadCount: number;
  onMarkNotificationRead: (id: string) => void;
  onMarkAllNotificationsRead: () => void;
  onSelectTaskFromNotification?: (taskId: string) => void;
  onViewAllNotifications: () => void;
}

export default function Header({
  view,
  onViewChange,
  notifications,
  unreadCount,
  onMarkNotificationRead,
  onMarkAllNotificationsRead,
  onSelectTaskFromNotification,
  onViewAllNotifications,
}: Props) {
  return (
    <header className="header">
      <div className="header-left">
        <div className="header-logo">
          <svg
            className="header-logo-mark"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M3 7 Q 8 3, 12 7 T 21 7" opacity="0.5" />
            <path d="M3 12 Q 8 8, 12 12 T 21 12" />
            <path d="M3 17 Q 8 13, 12 17 T 21 17" opacity="0.7" />
          </svg>
          AgentFlow
        </div>
        <div className="header-tabs">
          <button
            className={`header-tab${view === "dashboard" ? " active" : ""}`}
            onClick={() => onViewChange("dashboard")}
          >
            Dashboard
          </button>
          <button
            className={`header-tab${view === "flows" ? " active" : ""}`}
            onClick={() => onViewChange("flows")}
          >
            Flows
          </button>
          <button
            className={`header-tab${view === "agents" ? " active" : ""}`}
            onClick={() => onViewChange("agents")}
          >
            Agent Registry
          </button>
        </div>
      </div>
      <div className="header-actions">
        <NotificationBell
          items={notifications}
          unreadCount={unreadCount}
          onMarkRead={onMarkNotificationRead}
          onMarkAllRead={onMarkAllNotificationsRead}
          onSelectTask={onSelectTaskFromNotification}
          onViewAll={onViewAllNotifications}
        />
        <button
          className={`btn btn-icon${view === "secrets" ? " btn-icon-active" : ""}`}
          onClick={() => onViewChange("secrets")}
          title="Secrets"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </button>
        <button
          className={`btn btn-icon${view === "settings" ? " btn-icon-active" : ""}`}
          onClick={() => onViewChange("settings")}
          title="Settings"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
