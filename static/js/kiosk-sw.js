/* Service worker del quiosco (Fase 3, docs/15 «Modo contingencia»): SOLO guarda el «caparazón» para poder recargar la página de registro sin red:
     - la página `/kiosk/<id>/registro` (el HTML del propio quiosco: nombre del operador y datos del evento, sin la lista de personas), y
     - los archivos estáticos `/static/*` (JS, CSS, imágenes) que esa página usa.
   NUNCA toca (ni guarda) respuestas de la API (`/api/*`, incluido el roster local), `/health`, `/ready`, el inicio/cierre de sesión, otros orígenes ni peticiones que no sean GET: para
   todo eso el worker no interviene y el navegador va directo a la red.
   Estrategia: RED PRIMERO (4 s de espera máxima) y, si la red falla o no contesta, lo último guardado. Así nadie queda atrapado en una versión vieja: con red siempre se ve lo último del servidor.
   Versión: el servidor sustituye `__BUILD__` (revisión de Cloud Run + huella de este archivo) al servir `/kiosk/sw.js`; cada despliegue cambia el archivo, el navegador instala el
   worker nuevo, éste toma el control de inmediato (`skipWaiting` + `clients.claim`) y borra los cachés de las versiones anteriores. Una redirección (p. ej. a /login por sesión vencida) o
   una respuesta que no sea 200 NO se guarda: no se puede «congelar» una pantalla de error o de inicio de sesión. */
const BUILD = '__BUILD__';
const CACHE_PREFIX = 'golden-kiosk-shell-';
const CACHE = CACHE_PREFIX + BUILD;
const NETWORK_TIMEOUT_MS = 4000;
const KIOSK_PAGE = /^\/kiosk\/\d+\/registro\/?$/;

self.addEventListener('install', () => { self.skipWaiting(); });

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k.startsWith(CACHE_PREFIX) && k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

/* Primera visita: la página ya cargó ANTES de que el worker tomara el control, así que nada pasó por él. La página le manda su propia URL y la de sus archivos estáticos para guardarlos
   ya (solo `/kiosk/<id>/registro` y `/static/*`; cualquier otra cosa se ignora). */
self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type !== 'precache' || !Array.isArray(data.urls)) return;
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(data.urls.slice(0, 200).map(async (u) => {
      try {
        const url = new URL(u, self.location.href);
        if (url.origin !== self.location.origin || !(url.pathname.startsWith('/static/') || KIOSK_PAGE.test(url.pathname))) return;
        const res = await fetch(url.href, { credentials: 'same-origin' });
        if (res.status === 200 && res.type === 'basic' && !res.redirected) await cache.put(url.href, res);
      } catch (e) { /* sin red: se guardará en la próxima visita */ }
    }));
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const isStatic = url.pathname.startsWith('/static/');
  const isPage = req.mode === 'navigate' && KIOSK_PAGE.test(url.pathname);
  if (!isStatic && !isPage) return;                    // API, roster, salud, sesión, otras páginas: nunca por el worker
  event.respondWith(networkFirst(req, isPage));
});

function withTimeout(req) {
  const ctl = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), NETWORK_TIMEOUT_MS) : null;
  return fetch(req, ctl ? { signal: ctl.signal } : undefined).finally(() => { if (timer) clearTimeout(timer); });
}

async function networkFirst(req, isPage) {
  const cache = await caches.open(CACHE);
  const cached = () => cache.match(req, { ignoreSearch: !isPage });          // estáticos: cualquier versión (?v=) sirve sin red; la página: la misma URL
  try {
    const res = await withTimeout(req);
    if (res && res.status === 200 && res.type === 'basic' && !res.redirected) {
      await cache.put(req, res.clone());
      return res;
    }
    if (res && res.status >= 500) { const hit = await cached(); if (hit) return hit; }        // un 502/503 de la infraestructura al recargar: mejor la última página buena
    return res;
  } catch (e) {
    const hit = await cached();
    if (hit) return hit;
    if (isPage) return new Response('Sin conexión y sin una copia guardada de esta página. Abre el registro una vez con conexión.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    throw e;
  }
}
