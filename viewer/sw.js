// Service worker for the Malico 3D landslide viewer.
//
// Strategy:
//   - Precache the small shell (HTML, JS, CSS, libs, icons, manifest).
//   - For everything else under the viewer scope, use a cache-first
//     fallback so the large terrain textures and GeoJSON load instantly
//     on repeat visits and remain available offline once fetched.
//
// Bump CACHE_VERSION whenever any precached file changes so old caches
// are evicted on the next visit.

const CACHE_VERSION = 'malico-3d-v1';
const PRECACHE = [
  './',
  './index.html',
  './style.css?v=12',
  './main.js?v=10',
  './manifest.webmanifest',
  './lib/three.module.js',
  './lib/OrbitControls.js',
  './lib/leaflet.js',
  './lib/leaflet.css',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) =>
      // Use addAll with individual catches so one missing asset doesn't
      // abort the whole install (e.g. during local dev iteration).
      Promise.all(
        PRECACHE.map((url) =>
          cache.add(url).catch((err) => {
            console.warn('[sw] precache miss:', url, err);
          })
        )
      )
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Never cache OSM tiles or other cross-origin live data; just let them
  // hit the network and fail gracefully if offline.
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req)
        .then((resp) => {
          // Only cache successful, basic (same-origin) responses.
          if (!resp || resp.status !== 200 || resp.type !== 'basic') {
            return resp;
          }
          const copy = resp.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(req, copy));
          return resp;
        })
        .catch(() => cached);
    })
  );
});
