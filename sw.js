// StockIQ Service Worker — US Site
const CACHE_NAME = 'stockiq-us-v1';
const SHELL_ASSETS = [
  '/',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];

// Install: cache shell
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(c => c.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch: network-first for data, cache-first for shell
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  
  // Data files: always network-first, cache fallback
  if (url.pathname.startsWith('/data/') || url.pathname.startsWith('/daily/')) {
    e.respondWith(
      fetch(e.request)
        .then(r => {
          const clone = r.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
          return r;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }
  
  // Shell assets: cache-first, network fallback
  e.respondWith(
    caches.match(e.request)
      .then(cached => {
        const fetched = fetch(e.request).then(r => {
          const clone = r.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
          return r;
        });
        return cached || fetched;
      })
  );
});
