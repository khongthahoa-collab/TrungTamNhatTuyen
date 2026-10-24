// Keep authenticated pages uncached; handle Web Push for student and teacher PWAs.
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let notification = {};
  try {
    notification = event.data ? event.data.json() : {};
  } catch (error) {
    notification = { body: event.data ? event.data.text() : '' };
  }

  const title = notification.title || 'Trung tâm Nhật Tuyền';
  const options = {
    body: notification.body || 'Bạn có thông báo mới.',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/favicon-32.png',
    tag: notification.tag || 'nhat-tuyen-notification',
    data: { url: notification.url || '/student/exams' },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = new URL(
    event.notification.data?.url || '/student/exams',
    self.location.origin,
  ).href;

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const existingClient = clients.find((client) => client.url === targetUrl);
      if (existingClient) return existingClient.focus();
      return self.clients.openWindow(targetUrl);
    }),
  );
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
