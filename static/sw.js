// Minimal service worker: exists so Chrome/Android treats the site as an
// installable PWA. Intentionally does NOT cache pages/API responses —
// this app is session/auth-heavy, and caching HTML risks serving stale
// or wrong-user content across roles (admin/teacher/parent).
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
