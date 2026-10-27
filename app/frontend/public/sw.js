// Only push events are handled. Patient information is never cached offline.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data?.json() || {};
  } catch {
    /* Generic private reminder. */
  }
  event.waitUntil(
    self.registration.showNotification("Clinical Compass", {
      body: "У вас есть напоминание. Откройте приложение.",
      icon: "/icon.svg",
      badge: "/icon.svg",
      data: { url: "/" },
      tag: data.tag || "reminder",
    }),
  );
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windows) => {
        if (windows.length) return windows[0].focus();
        return clients.openWindow("/");
      }),
  );
});
