/* Service worker del quiosco (Fase 3, docs/15 «Modo contingencia»): SOLO guarda el «caparazón» para poder recargar la página de registro sin red:
     - las páginas `/kiosk/<id>/registro` y `/kiosk/<id>/rostro` (el HTML del propio quiosco: nombre del operador y datos del evento, sin la lista de personas), y
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
const KIOSK_PAGE = /^\/kiosk\/\d+\/(registro|rostro|areas|inventario)\/?$/;       // el registro y la pantalla de la puerta (autoservicio «Entrar con mi rostro»)

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
    // Un estático guardado con otro `?v=` queda viejo: se borra (así `ignoreSearch` nunca devuelve una versión vieja pudiendo servir la nueva y el caché no crece con cada despliegue).
    const u = new URL(key);
    if (u.search && u.pathname.startsWith('/static/')) for (const old of await cache.keys()) { const o = new URL(old.url); if (o.pathname === u.pathname && o.search !== u.search) await cache.delete(old); }
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

/* Registro de diagnóstico (últimas 150 peticiones que atendió): {path, via, ms}. `via`: red | timeout→copia | error→copia | 5xx→copia | sin copia. La página lo pide con
   postMessage({type:'trace'}) (static/js/boot-trace.js) para ver de dónde sale cada espera al recargar sin red. Solo en memoria del worker; no guarda nada en disco. */
const TRACE = [];
function trace(req, via, since) { TRACE.push({ path: new URL(req.url).pathname, via, ms: Math.round(Date.now() - since) }); if (TRACE.length > 150) TRACE.shift(); }
/* Primera visita: la página ya cargó ANTES de que el worker tomara el control, así que nada pasó por él. La página le manda su propia URL y la de sus archivos estáticos para guardarlos
   ya (solo `/kiosk/<id>/registro` y `/static/*`; cualquier otra cosa se ignora). */
self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'trace' && event.ports && event.ports[0]) { event.ports[0].postMessage({ log: TRACE.slice() }); return; }       // diagnóstico (boot-trace.js)
  if (data.type === 'print-cfg' && data.eventId && data.cfg && typeof data.cfg === 'object') {          // datos del evento para armar la escarapela sin red (qué categorías tienen plantilla, nombres de los opcionales): no son datos personales
    event.waitUntil((async () => {
      const cache = await caches.open(CACHE);
      await cache.put(cfgKey(String(data.eventId).replace(/\D/g, '')), jsonRes(200, data.cfg));
      const eid = String(data.eventId).replace(/\D/g, ''), O = self.location.origin;
      const tpls = [`${O}/api/events/${eid}/badge-template`, ...((Array.isArray(data.cfg.categories) ? data.cfg.categories : []).slice(0, 30).map((c) => `${O}/api/events/${eid}/badge-template?category=${encodeURIComponent(c)}`))];
      for (const t of tpls) { try { const r = await fetch(t, { credentials: 'same-origin', cache: 'no-store' }); if (r.status === 200 && r.type === 'basic' && !r.redirected) { const copy = r.clone(); await keep(cache, tplKey(new URL(t)), r); await keepAssets(copy, cache); } } catch (e) { /* sin red */ } }
      try {                                                                // la ventana de impresión y los archivos que usa (librerías, tipografías)
        const pk = `${O}/kiosk/${eid}/escarapela/imprimir`; const r = await fetch(`${pk}/PRUEBA`, { credentials: 'same-origin' });
        if (r.status === 200 && r.type === 'basic' && !r.redirected) {
          const html = await r.clone().text(); await keep(cache, pk, r);
          const statics = [...new Set((html.match(/(?:src|href)="(\/static\/[^"]+)"/g) || []).map((x) => x.replace(/^(?:src|href)="/, '').replace(/"$/, '').replace(/&amp;/g, '&')))].slice(0, 40);
          for (const st of statics) {
            try {
              const u = new URL(st, O); if (await cache.match(keyOf(u.href, false), { ignoreVary: true })) continue;
              const sr = await fetch(u.href, { credentials: 'same-origin' }); if (!(sr.status === 200 && sr.type === 'basic')) continue;
              const css = /\.css$/.test(u.pathname) ? await sr.clone().text() : ''; await keep(cache, keyOf(u.href, false), sr);
              for (const f of [...new Set((css.match(/url\(([^)]+)\)/g) || []).map((x) => x.slice(4, -1).replace(/['"]/g, '')))].slice(0, 40)) { try { const fu = new URL(f, u.href); if (fu.origin !== O || !fu.pathname.startsWith('/static/') || await cache.match(keyOf(fu.href, false), { ignoreVary: true })) continue; const fr = await fetch(fu.href); if (fr.status === 200) await keep(cache, keyOf(fu.href, false), fr); } catch (e) { /* una tipografía menos */ } }
            } catch (e) { /* sin red */ }
          }
        }
      } catch (e) { /* sin red */ }
    })());
    return;
  }
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

/* ------------------------------------------------------------------ IMPRIMIR SIN RED (25-nov-2026, docs/28_CONTINGENCIA_COMPLETA.md)
   Para que la escarapela salga sin conexión por los caminos de siempre (ventana de impresión y USB), SIN tocar su código ni sus parámetros, el worker atiende SOLO estas lecturas, siempre
   RED PRIMERO y la copia únicamente si la red falla:
     - la plantilla de la escarapela y sus imágenes (no son datos personales): se guarda la última respuesta buena;
     - la página de la ventana de impresión: se guarda una por evento y, sin red, se sirve con la cédula pedida;
     - los datos de la persona para la escarapela: NUNCA se guardan aquí; sin red se arman al momento desde la copia completa CIFRADA del dispositivo (contingency.js › people);
     - el conteo de impresiones: sin red responde «0» (no hay con quién comprobar; cada impresión se anota y se envía al volver la red).
   Todo lo demás de la API sigue sin pasar por el worker. */
const PRINT_PAGE = /^\/kiosk\/(\d+)\/escarapela\/imprimir\/([^/]+)\/?$/;
const TPL_API = /^\/api\/events\/(\d+)\/badge-template$/;
const ASSET_API = /^\/api\/badge-assets\/[^/]+\/[^/]+$/;
const PRINT_DATA_API = /^\/api\/users\/([^/]+)\/badge-print-data$/;
const PRINT_AUX_API = /^\/api\/users\/([^/]+)\/(print-count|print-flow)$/;
const jsonRes = (status, data) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Gw-Offline': '1' } });
const cfgKey = (eventId) => `${self.location.origin}/__gw/print-cfg/${eventId}`;
function tplKey(url) { const q = new URLSearchParams(); ['category', 'kind'].forEach((k) => { if (url.searchParams.get(k)) q.set(k, url.searchParams.get(k)); }); const t = q.toString(); return url.origin + url.pathname + (t ? '?' + t : ''); }

/* Red primero; la copia solo si la red falla (o da 5xx). Guarda la respuesta 200. */
async function netThenCopy(event, req, key, onFresh) {
  const cache = await caches.open(CACHE);
  let res;
  try { res = (await cache.match(key, { ignoreVary: true })) ? await withTimeout(req) : await fetch(req); }
  catch (e) { const hit = await cache.match(key, { ignoreVary: true }); if (hit) return hit; throw e; }
  if (res && res.status === 200 && res.type === 'basic' && !res.redirected) { const copy = res.clone(); event.waitUntil(keep(cache, key, res).then(() => (onFresh ? onFresh(copy, cache) : null)).catch(() => {})); return res; }
  if (res && res.status >= 500) { const hit = await cache.match(key, { ignoreVary: true }); if (hit) return hit; }
  return res;
}
/* Al guardar una plantilla se guardan también sus imágenes (fondo y logos), para que la escarapela salga completa sin red. */
async function keepAssets(res, cache) {
  const tpl = await res.json();
  const paths = new Set();
  if (tpl && tpl.background_type === 'image' && tpl.background_value) paths.add(tpl.background_value);
  ((tpl && tpl.elements) || []).forEach((el) => { if (el && el.storage_path) paths.add(el.storage_path); });
  await Promise.all([...paths].slice(0, 40).map(async (p) => {
    const u = `${self.location.origin}/api/badge-assets/${p}`;
    try { if (await cache.match(u, { ignoreVary: true })) return; const r = await fetch(u, { credentials: 'same-origin' }); if (r.status === 200 && r.type === 'basic' && !r.redirected) await keep(cache, u, r); } catch (e) { /* sin red: en la próxima */ }
  }));
}
/* La página de impresión guardada (una por evento), con la cédula de ESTA petición. */
async function printPage(event, req, url) {
  const m = PRINT_PAGE.exec(url.pathname), key = `${url.origin}/kiosk/${m[1]}/escarapela/imprimir`;
  const cache = await caches.open(CACHE);
  const fromCopy = async () => {
    const hit = await cache.match(key, { ignoreVary: true });
    if (!hit) return new Response('Sin conexión y sin una copia de la ventana de impresión. Abre el registro una vez con conexión.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    const js = (v) => JSON.stringify(v).replace(/</g, '\\u003c');
    const id = decodeURIComponent(m[2]), many = (url.searchParams.get('users') || '').split(',').map((x) => x.trim()).filter(Boolean).slice(0, 50);
    const html = (await hit.text()).replace(/^(\s*)const USER_ID = .*$/m, (_, sp) => `${sp}const USER_ID = ${js(id)};`).replace(/^(\s*)const USER_IDS = .*$/m, (_, sp) => `${sp}const USER_IDS = ${js(many.length > 1 ? many : [id])};`);
    return new Response(html, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Gw-Offline': '1' } });
  };
  let res;
  try { res = (await cache.match(key, { ignoreVary: true })) ? await withTimeout(req) : await fetch(req); } catch (e) { return fromCopy(); }
  if (res && res.status === 200 && res.type === 'basic' && !res.redirected) { event.waitUntil(keep(cache, key, res)); return res; }
  if (res && res.status >= 500) return fromCopy();
  return res;
}
/* Datos de la persona para su escarapela, armados desde la copia completa cifrada (misma forma que GET /api/users/{id}/badge-print-data). Solo a quien está Registrado (o la persona de prueba). */
const idbReq = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error || new Error('idb')); });
async function localPrintData(eventId, userId) {
  const name = `golden-contingency-${eventId}`;
  if (self.indexedDB.databases) { const all = await self.indexedDB.databases(); if (!all.some((d) => d.name === name)) return null; }          // no crear una base vacía
  const db = await idbReq(self.indexedDB.open(name));
  try {
    if (!db.objectStoreNames.contains('people') || !db.objectStoreNames.contains('keys')) return null;
    const tx = db.transaction(['people', 'keys', 'meta'], 'readonly');
    const [blocks, keyRec, roster] = await Promise.all([idbReq(tx.objectStore('people').getAll()), idbReq(tx.objectStore('keys').get('q')), idbReq(tx.objectStore('meta').get('roster'))]);
    if (!keyRec || !keyRec.key || !roster || !roster.expires_at || Date.now() >= roster.expires_at) return null;          // vencida la lista local, la copia ya no vale
    for (const rec of blocks) {
      let rows;
      try { rows = JSON.parse(new TextDecoder().decode(await self.crypto.subtle.decrypt({ name: 'AES-GCM', iv: rec.enc.iv }, keyRec.key, rec.enc.ct))); } catch (e) { continue; }
      const u = rows.find((x) => String(x.id) === String(userId));
      if (u) return u;
    }
    return null;
  } finally { db.close(); }
}
async function printData(req, url) {
  try { return await fetch(req); } catch (netErr) {
    const userId = decodeURIComponent(PRINT_DATA_API.exec(url.pathname)[1]), eventId = url.searchParams.get('event_id');
    let u = null, cfg = {};
    try { u = await localPrintData(eventId, userId); } catch (e) { u = null; }
    if (!u) return jsonRes(503, { detail: 'Sin conexión y sin los datos de esta persona en el dispositivo.' });
    if (u.status === 'No registrado' && String(u.id) !== 'PRUEBA') return jsonRes(403, { detail: 'Esta persona aún no está registrada en el evento: regístrala antes de imprimir su escarapela.' });
    try { const hit = await (await caches.open(CACHE)).match(cfgKey(eventId), { ignoreVary: true }); cfg = hit ? await hit.json() : {}; } catch (e) { cfg = {}; }
    const cats = Array.isArray(u.categories) ? u.categories : [];
    const withTpl = Array.isArray(cfg.categories) ? cfg.categories : [];
    return jsonRes(200, {
      card_url: '', id: u.id, first_name: u.first_name || '', last_name: u.last_name || '', role: u.role || '', entity: u.entity || '', phone: u.phone || '', email: u.email || '',
      opt_1: u.opt_1 || '', extra_fields: u.extra_fields || {}, optional_field_labels: cfg.labels || {}, has_photo: false, categories: cats.join(', '),
      ...(cfg.code ? { code: u.code || '' } : {}), template_category: cfg.per_category ? (cats.find((c) => withTpl.includes(c)) || null) : null,
    });
  }
}
function offlineRoute(event, req, url) {
  const p = url.pathname;
  if (req.mode === 'navigate' && PRINT_PAGE.test(p)) return printPage(event, req, url);
  if (TPL_API.test(p)) return netThenCopy(event, req, tplKey(url), keepAssets);
  if (ASSET_API.test(p)) return netThenCopy(event, req, url.origin + p);
  if (PRINT_DATA_API.test(p)) return printData(req, url);
  if (PRINT_AUX_API.test(p)) return fetch(req).catch(() => jsonRes(200, p.endsWith('print-count') ? { times_printed: 0, offline: true } : { auto_print_skip: false, offline: true }));
  return null;
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const off = offlineRoute(event, req, url);
  if (off) { event.respondWith(off); return; }
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
  // Por texto y sin Vary (no depende de las cabeceras de la petición). Un estático: primero EXACTO (con su ?v=) y, si no está, cualquier versión del mismo archivo.
  const cached = async () => (await cache.match(key, { ignoreVary: true })) || (isPage ? undefined : cache.match(key, { ignoreSearch: true, ignoreVary: true }));
  let res;
  const since = Date.now();
  try {
    // Sin copia guardada no hay a qué recurrir: se espera la red sin tope. Con el tope, un archivo lento (sin copia) se abortaba ("signal is aborted") y la página quedaba en blanco y con errores.
    res = (await cached()) ? await withTimeout(req) : await fetch(req);
  } catch (e) {
    const timedOut = Date.now() - since >= NETWORK_TIMEOUT_MS - 50;
    const hit = await cached();
    trace(req, (timedOut ? 'timeout→' : 'error→') + (hit ? 'copia' : 'sin copia'), since);
    if (hit) return hit;
    if (isPage) return new Response('Sin conexión y sin una copia guardada de esta página. Abre el registro una vez con conexión.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    throw e;
  }
  if (res && res.status === 200 && res.type === 'basic' && !res.redirected) {
    event.waitUntil(keep(cache, key, res));            // guardar no retrasa ni puede romper la respuesta en vivo
    trace(req, 'red', since);
    return res;
  }
  if (res && res.status >= 500) { const hit = await cached(); trace(req, '5xx→' + (hit ? 'copia' : 'sin copia'), since); if (hit) return hit; }        // un 502/503 de la infraestructura al recargar: mejor la última página buena
  return res;
}
