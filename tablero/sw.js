/* Día a día — Service Worker
   Estrategia:
   - HTML: red primero (para no servir páginas viejas), caché de respaldo offline.
   - Estáticos (iconos, fuentes): caché primero.
   - API: siempre red (nunca cachear datos).
   - Push: listo para la Fase 2 (avisos por persona). */

const VERSION = 'dd-v3';
const SHELL = [
  '/',
  '/tablero/index.html',
  '/tablero/agenda.html',
  '/tablero/admin.html',
  '/tablero/proyectos.html',
  '/tablero/comidas.html',
  '/tablero/dd.js',
  '/tablero/manifest.webmanifest',
  '/tablero/iconos/icono-192.png',
  '/tablero/iconos/icono-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return; // API: siempre red

  // HTML → red primero, caché de respaldo
  if (e.request.mode === 'navigate' || url.pathname.endsWith('.html')) {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copia = r.clone();
          caches.open(VERSION).then((c) => c.put(e.request, copia));
          return r;
        })
        .catch(() => caches.match(e.request).then((m) => m || caches.match('/')))
    );
    return;
  }

  // Estáticos → caché primero
  e.respondWith(
    caches.match(e.request).then(
      (m) =>
        m ||
        fetch(e.request).then((r) => {
          if (r.ok && url.origin === location.origin) {
            const copia = r.clone();
            caches.open(VERSION).then((c) => c.put(e.request, copia));
          }
          return r;
        })
    )
  );
});

/* ── Push (Fase 2: avisos por persona) ───────────────────── */
self.addEventListener('push', (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (_) {}
  const title = data.title || 'Día a día';
  const opts = {
    body: data.body || '',
    icon: '/tablero/iconos/icono-192.png',
    badge: '/tablero/iconos/icono-192.png',
    data: { url: data.url || '/' },
    tag: data.tag || undefined,
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = e.notification.data?.url || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((lista) => {
      for (const c of lista) {
        if ('focus' in c) { c.navigate(url); return c.focus(); }
      }
      return clients.openWindow(url);
    })
  );
});
