/* Service worker del quiosco (Fase 3, docs/15 «Modo contingencia»): SOLO guarda el «caparazón» para poder recargar la página de registro sin red:
     - la página `/kiosk/<id>/registro` (el HTML del propio quiosco: nombre del operador y datos del evento, sin la lista de personas), y
     - los archivos estáticos `/static/*` (JS, CSS, imágenes) que esa página usa.
   NUNCA toca (ni guarda) respuestas de la API (`/api/*`, incluido el roster local), `/health`, `/ready`, el inicio/cierre de sesión, otros orígenes ni peticiones que no sean GET: para
   todo eso el worker no interviene y el navegador va directo a la red.
   Estrategia: RED PRIMERO (4 s de espera máxima) y, si la red falla o no contesta, lo último guardado. Así nadie queda atrapado en una versión vieja: con red siempre se ve lo último del servidor.
   Versión: el servidor sustituye `__BUILD__` (revisión de Cloud Run + huella de este archivo) al servir `/kiosk/sw.js`; cada despliegue cambia el archivo, el navegador instala el
   worker nuevo, éste toma el control de inmediato (`skipWaiting` + `clients.claim`) y borra los cachés de las versiones anteriores. Una redirección (p. ej. a /login por sesión vencida) o
   una respuesta que no sea 200 NO se guarda: no se puede «congelar» una pantalla de error o de inicio de sesión.
   Detrás de Firebase Hosting las respuestas llevan `Vary: Accept-Encoding, cookie, need-authorization, x-fh-requested-host`. La Cache API compara esas cabeceras de la petición guardada con
   las de la nueva (y Safari/Chrome no las ven igual en una navegación), así que `caches.match` podía fallar y la página no salía sin red. Por eso: (1) lo que se guarda es una COPIA sin
   `Vary` (ni `Content-Encoding`/`Content-Length`/`Set-Cookie`), (2) todo se busca por URL (texto) con `ignoreVary`, y (3) la página se guarda y se busca sin la parte `?…` de la URL. La
   sesión por cookie no interviene: el HTML guardado no contiene la lista de personas y, sin red, la página usa la copia local del roster (static/js/contingency.js). */
const BUILD = '__BUILD__';
const CACHE_PREFIX = 'golden-kiosk-shell-';
const CACHE = CACHE_PREFIX + BUILD;
const NETWORK_TIMEOUT_MS = 4000;
const KIOSK_PAGE = /^\/kiosk\/\d+\/registro\/?$/;

/* Clave de caché: la página sin `?…` y sin «/» final; los estáticos con su `?v=` (y, sin red, cualquier versión sirve). */
function keyOf(rawUrl, isPage) {
  const u = new URL(rawUrl, self.location.href);
  return isPage ? u.origin + u.pathname.replace(/\/$/, '') : u.origin + u.pathname + u.search;
}
function isOurPage(url) { return url.origin === self.location.origin && KIOSK_PAGE.test(url.pathname); }

/* Copia guardable de una respuesta: sin `Vary` (si no, `match` depende de cabeceras de la petición que cambian según el navegador/CDN, y `Vary: *` ni siquiera se puede guardar) y sin las
   cabeceras de codificación (el cuerpo ya viene descomprimido) ni cookies. */
async function keep(cache, key, res) {
  try {
    const body = await res.clone().arrayBuffer();
    const headers = new Headers(res.headers);
    ['vary', 'content-encoding', 'content-length', 'set-cookie', 'transfer-encoding'].forEach((n) => headers.delete(n));
    await cache.put(key, new Response(body, { status: res.status, statusText: res.statusText, headers }));
  } catch (e) { /* no se pudo guardar: no afecta a la respuesta en vivo */ }
}

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
        const page = isOurPage(url);
        if (url.origin !== self.location.origin || !(url.pathname.startsWith('/static/') || page)) return;
        const res = await fetch(url.href, { credentials: 'same-origin' });
        if (res.status === 200 && res.type === 'basic' && !res.redirected) await keep(cache, keyOf(url.href, page), res);
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
  event.respondWith(networkFirst(event, req, isPage));
});

function withTimeout(req) {
  const ctl = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), NETWORK_TIMEOUT_MS) : null;
  return fetch(req, ctl ? { signal: ctl.signal } : undefined).finally(() => { if (timer) clearTimeout(timer); });
}

async function networkFirst(event, req, isPage) {
  const cache = await caches.open(CACHE);
  const key = keyOf(req.url, isPage);
  const cached = () => cache.match(key, { ignoreSearch: !isPage, ignoreVary: true });        // por texto y sin Vary: no depende de las cabeceras de la petición
  let res;
  try {
    res = await withTimeout(req);
  } catch (e) {
    const hit = await cached();
    if (hit) return hit;
    if (isPage) return new Response('Sin conexión y sin una copia guardada de esta página. Abre el registro una vez con conexión.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    throw e;
  }
  if (res && res.status === 200 && res.type === 'basic' && !res.redirected) {
    event.waitUntil(keep(cache, key, res));            // guardar no retrasa ni puede romper la respuesta en vivo
    return res;
  }
  if (res && res.status >= 500) { const hit = await cached(); if (hit) return hit; }        // un 502/503 de la infraestructura al recargar: mejor la última página buena
  return res;
}
