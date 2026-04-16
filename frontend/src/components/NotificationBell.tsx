import React, { useEffect, useRef, useState } from "react";
import { AppNotification } from "../api";
import NotificationDropdown from "./NotificationDropdown";

interface Props {
  items: AppNotification[];
  unreadCount: number;
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  onSelectTask?: (taskId: string) => void;
}

export default function NotificationBell({
  items,
  unreadCount,
  onMarkRead,
  onMarkAllRead,
  onSelectTask,
}: Props) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const label = unreadCount > 9 ? "9+" : String(unreadCount);

  return (
    <div className="notification-bell-wrapper" ref={wrapperRef}>
      <button
        className={`btn btn-icon${open ? " btn-icon-active" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title={`${unreadCount} unread notification${unreadCount === 1 ? "" : "s"}`}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 01-3.46 0" />
        </svg>
        {unreadCount > 0 && <span className="notification-badge">{label}</span>}
      </button>
      {open && (
        <NotificationDropdown
          items={items}
          unreadCount={unreadCount}
          onMarkRead={onMarkRead}
          onMarkAllRead={onMarkAllRead}
          onSelectTask={onSelectTask}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
