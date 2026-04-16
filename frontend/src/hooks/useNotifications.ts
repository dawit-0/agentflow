import { useCallback, useEffect, useState } from "react";
import { AppNotification, Settings, api } from "../api";
import { socket } from "../socket";
import { fireDesktopNotification } from "../lib/desktopNotifications";

interface NewNotificationEvent {
  notification: AppNotification;
  unread_count: number;
}

export function useNotifications(settings: Settings | null) {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const load = useCallback(async () => {
    try {
      const [list, count] = await Promise.all([
        api.notifications.list(false, 20),
        api.notifications.unreadCount(),
      ]);
      setItems(list);
      setUnreadCount(count.unread_count);
    } catch {
      // Non-fatal: leave previous state in place.
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    function onNew(ev: NewNotificationEvent) {
      setItems((prev) => [ev.notification, ...prev].slice(0, 50));
      setUnreadCount(ev.unread_count);

      if (settings?.notify_desktop_enabled) {
        fireDesktopNotification(ev.notification.title, ev.notification.body);
      }
    }

    socket.on("notification:new", onNew);
    return () => {
      socket.off("notification:new", onNew);
    };
  }, [settings?.notify_desktop_enabled]);

  const markRead = useCallback(async (id: string) => {
    await api.notifications.markRead(id);
    setItems((prev) =>
      prev.map((n) => (n.id === id && !n.read_at ? { ...n, read_at: new Date().toISOString() } : n))
    );
    setUnreadCount((c) => Math.max(0, c - 1));
  }, []);

  const markAllRead = useCallback(async () => {
    await api.notifications.markAllRead();
    const now = new Date().toISOString();
    setItems((prev) => prev.map((n) => (n.read_at ? n : { ...n, read_at: now })));
    setUnreadCount(0);
  }, []);

  return { items, unreadCount, markRead, markAllRead, reload: load };
}
