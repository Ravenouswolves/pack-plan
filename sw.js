/* Conservative offline shell. Network-first for HTML. Never intercepts cross-origin requests (Google Fonts stay uncached). */
const CACHE = 'pack-plan-shell-v2';
const SHELL = [
  './',
  './index.html',
  './404.html',
  './manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(SHELL.map(async url => {
      try { await cache.add(url); } catch (e) { /* missing file is fine */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

function isHTMLRequest(request, url) {
  if (request.mode === 'navigate') return true;
  const path = url.pathname;
  if (path.endsWith('.html') || path.endsWith('/')) return true;
  const accept = request.headers.get('accept') || '';
  return accept.includes('text/html');
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  // Never intercept third-party calls (Google Fonts, etc.).
  if (url.origin !== self.location.origin) return;
  // Let the browser handle service-worker updates itself.
  if (url.pathname.endsWith('/sw.js')) return;

  if (isHTMLRequest(request, url)) {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(request);
        const cache = await caches.open(CACHE);
        cache.put(request, fresh.clone());
        return fresh;
      } catch (e) {
        const cached = await caches.match(request);
        return cached || caches.match('./index.html') || caches.match('./404.html');
      }
    })());
    return;
  }

  event.respondWith((async () => {
    const cached = await caches.match(request);
    const network = fetch(request).then(resp => {
      if (resp && resp.ok) {
        caches.open(CACHE).then(cache => cache.put(request, resp.clone()));
      }
      return resp;
    }).catch(() => null);
    return cached || network || Promise.reject(new Error('offline'));
  })());
});
