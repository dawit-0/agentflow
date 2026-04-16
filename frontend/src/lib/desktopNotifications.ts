/** Browser desktop notification helpers. */

export function desktopNotificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function desktopPermission(): NotificationPermission | "unsupported" {
  if (!desktopNotificationsSupported()) return "unsupported";
  return Notification.permission;
}

export async function requestDesktopPermission(): Promise<NotificationPermission | "unsupported"> {
  if (!desktopNotificationsSupported()) return "unsupported";
  if (Notification.permission === "granted" || Notification.permission === "denied") {
    return Notification.permission;
  }
  return await Notification.requestPermission();
}

export function fireDesktopNotification(title: string, body?: string | null): void {
  if (!desktopNotificationsSupported()) return;
  if (Notification.permission !== "granted") return;
  try {
    new Notification(title, {
      body: body ?? undefined,
      silent: false,
      tag: `agentflow-${Date.now()}`,
    });
  } catch {
    // Some browsers restrict Notification in non-secure contexts — fail silently.
  }
}
