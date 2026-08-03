/* Meal Planner — service worker.
   Strategy: NETWORK-FIRST for the page and the weekly data, so an update is
   always shown when online (this app changes every Wednesday). The cache is
   only a fallback so it still opens offline. Bump CACHE to force a refresh. */
const CACHE = 'mealplanner-v4';
const SHELL = [
  'index.html',
  'manifest.json',
  'icon-192.png',
  'icon-512.png',
  'apple-touch-icon.png',
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  // Network-first: try the network, cache the fresh copy, fall back to cache
  // when offline. Applies to everything (HTML shell + thisweek.json + icons).
  e.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      })
      .catch(() =>
        caches.match(req).then((hit) => hit || caches.match('index.html'))
      )
  );
});
