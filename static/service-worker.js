const CACHE_NAME = 'schools-shell-20261121-referrals-v1';
const SHELL = ['/', '/css/site.css', '/js/app.js', '/manifest.webmanifest', '/images/schools-mark.svg', '/images/kenya-schools-profile.jpg', '/images/kenya-flag.svg', '/offline.html'];
self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/admin') || url.pathname.startsWith('/uploads') || url.pathname.startsWith('/school/')) return;
  if (url.pathname.startsWith('/schools') || url.pathname.startsWith('/directory') || url.pathname.startsWith('/api')) return;
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok && (url.pathname === '/' || url.pathname.startsWith('/css/') || url.pathname.startsWith('/js/') || url.pathname === '/manifest.webmanifest')) {
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
    }
    return response;
  }).catch(async () => (await caches.match(event.request)) || (await caches.match('/offline.html'))));
});
