// Prueba del service worker del quiosco (static/js/kiosk-sw.js) en un entorno falso de worker. Correr: node tests/js/kiosk_sw_check.js
// Comprueba: solo maneja la página /kiosk/<id>/registro y /static/*; NUNCA la API (roster incluido), /health, sesión, otros orígenes ni POST; red primero con respaldo en el caché;
// no guarda redirecciones ni errores; versionado (activate borra los cachés viejos, skipWaiting y claim); sin copia guardada, una respuesta clara en vez de un error de red.
const fs = require('fs');
const assert = require('assert');

// Las Response construidas a mano tienen type «default»; las de una petición del mismo origen son «basic»
const R = (text, status = 200, extra = {}) => { const r = new Response(text, { status }); Object.defineProperty(r, 'type', { value: 'basic' }); Object.entries(extra).forEach(([k, v]) => Object.defineProperty(r, k, { value: v })); return r; };

function makeWorker(build) {
  const listeners = {};
  const store = new Map();                                  // nombre de caché -> Map(url -> Response)
  // Cache API falsa CON la semántica de Vary de la especificación: una respuesta guardada con `Vary: X` solo coincide si la petición nueva lleva el mismo valor de X que la guardada. Una clave
  // de texto se comporta como en WebKit/Chrome reales de forma conservadora: la petición guardada no tenía cabeceras y la nueva (navegación) lleva Accept y Accept-Encoding.
  const NAV_HEADERS = { accept: 'text/html', 'accept-encoding': 'gzip' };
  const headersOf = (req) => (typeof req === 'string' ? NAV_HEADERS : Object.fromEntries(Object.entries(req.headers || NAV_HEADERS)));
  const caches = {
    open: async (name) => {
      if (!store.has(name)) store.set(name, new Map());
      const m = store.get(name);
      const urlOf = (req) => (typeof req === 'string' ? req : req.url);
      return {
        match: async (req, opts = {}) => {
          const k = opts.ignoreSearch ? [...m.keys()].find((u) => u.split('?')[0] === urlOf(req).split('?')[0]) : urlOf(req);
          const hit = k && m.get(k);
          if (!hit) return undefined;
          if (!opts.ignoreVary) {
            const vary = hit.res.headers.get('vary');
            if (vary === '*') return undefined;
            for (const name of (vary || '').split(',').map((x) => x.trim().toLowerCase()).filter(Boolean)) if ((hit.reqHeaders[name] || null) !== (headersOf(req)[name] || null)) return undefined;
          }
          return hit.res.clone();
        },
        put: async (req, res) => {
          if (res.headers.get && res.headers.get('vary') === '*') throw new TypeError('Cache.put() no admite Vary: *');
          m.set(urlOf(req), { res, reqHeaders: typeof req === 'string' ? {} : headersOf(req) });
        },
        keysList: () => [...m.keys()],
      };
    },
    keys: async () => [...store.keys()],
    delete: async (n) => store.delete(n),
  };
  const state = { skipWaiting: 0, claimed: 0 };
  const scope = { location: { origin: 'https://app.test' }, addEventListener: (k, f) => { listeners[k] = f; }, skipWaiting: () => { state.skipWaiting++; }, clients: { claim: async () => { state.claimed++; } } };
  const src = fs.readFileSync(process.env.KIOSK_SW_FILE || 'static/js/kiosk-sw.js', 'utf8').split('__BUILD__').join(build);       // igual que el servidor (reemplaza todas las apariciones)
  let net = async () => R('red');
  const fetchFake = (req, init) => net(req, init);
  new Function('self', 'caches', 'fetch', 'Response', 'URL', 'AbortController', 'setTimeout', 'clearTimeout', src)(scope, caches, fetchFake, Response, URL, AbortController, setTimeout, clearTimeout);
  const dispatch = async (url, { method = 'GET', mode = 'cors', headers } = {}) => {
    let handled = null; const waits = [];
    listeners.fetch({ request: { url, method, mode, headers: headers || (mode === 'navigate' ? NAV_HEADERS : {}) }, respondWith: (p) => { handled = p; }, waitUntil: (p) => waits.push(p) });
    const out = handled ? { handled: true, res: await handled } : { handled: false };
    await Promise.all(waits);
    return out;
  };
  return { listeners, store, state, dispatch, setNet: (f) => { net = f; } };
}
const O = 'https://app.test';

(async () => {
  const w = makeWorker('rev1-aaa');
  // install / activate
  w.listeners.install(); assert.strictEqual(w.state.skipWaiting, 1, 'toma el control sin esperar a que se cierren las pestañas');
  w.store.set('golden-kiosk-shell-rev0-zzz', new Map([['x', new Response('viejo')]])); w.store.set('otro-cache-ajeno', new Map());
  await new Promise((resolve) => w.listeners.activate({ waitUntil: (p) => p.then(resolve) }));
  assert.ok(!w.store.has('golden-kiosk-shell-rev0-zzz'), 'borra los cachés de versiones anteriores'); assert.ok(w.store.has('otro-cache-ajeno'), 'no toca cachés ajenos'); assert.strictEqual(w.state.claimed, 1);

  // lo que NO maneja: la API (roster incluido), salud, sesión, POST, otros orígenes, otras páginas
  for (const [u, o] of [[`${O}/api/events/7/local-roster`, {}], [`${O}/api/ping-auth`, {}], [`${O}/api/events/7/access-logs/sync`, { method: 'POST' }], [`${O}/health`, {}], [`${O}/ready`, {}], [`${O}/login`, { mode: 'navigate' }],
    [`${O}/logout`, { method: 'POST' }], [`${O}/f/7/feria`, { mode: 'navigate' }], [`${O}/kiosk/7`, { mode: 'navigate' }], [`${O}/kiosk/7/roster`, { mode: 'navigate' }], ['https://cdn.otro/static/x.js', {}], [`${O}/kiosk/7/registro`, { method: 'POST', mode: 'navigate' }],
    [`${O}/kiosk/7/registro`, { mode: 'cors' }]]) {
    assert.strictEqual((await w.dispatch(u, o)).handled, false, `no debe manejar ${o.method || 'GET'} ${u}`);
  }

  // lo que SÍ maneja: la página del registro (navegación) y /static/*; red primero y lo guarda
  let r = await w.dispatch(`${O}/kiosk/7/registro`, { mode: 'navigate' });
  assert.ok(r.handled); assert.strictEqual(await r.res.text(), 'red');
  w.setNet(async () => R('js')); r = await w.dispatch(`${O}/static/js/contingency.js?v=111`); assert.ok(r.handled);
  const cache = w.store.get('golden-kiosk-shell-rev1-aaa'); assert.deepStrictEqual([...cache.keys()].sort(), [`${O}/kiosk/7/registro`, `${O}/static/js/contingency.js?v=111`]);
  assert.ok(![...cache.keys()].some((k) => k.includes('/api/')), 'nunca guarda la API');

  // primera visita: la página manda su URL y la de sus estáticos; solo se guardan la página del registro y /static/* (nada de la API ni de otros orígenes)
  w.setNet(async () => R('precargado'));
  await new Promise((resolve) => w.listeners.message({ data: { type: 'precache', urls: [`${O}/kiosk/5/registro`, `${O}/static/css/style.css?v=1`, `${O}/api/events/5/local-roster`, `${O}/health`, 'https://otro.test/static/x.js', `${O}/kiosk/5`] }, waitUntil: (p) => p.then(resolve) }));
  assert.deepStrictEqual([...w.store.get('golden-kiosk-shell-rev1-aaa').keys()].filter((k) => /\/5\/|style\.css|local-roster|health|otro|\/kiosk\/5$/.test(k)).sort(), [`${O}/kiosk/5/registro`, `${O}/static/css/style.css?v=1`]);
  w.listeners.message({ data: { type: 'otra-cosa' }, waitUntil: () => { throw new Error('no debe hacer nada'); } });

  // sin red: la página y los estáticos salen del caché (estáticos con cualquier ?v=)
  w.setNet(async () => { throw new TypeError('Failed to fetch'); });
  r = await w.dispatch(`${O}/kiosk/7/registro`, { mode: 'navigate' }); assert.strictEqual(await r.res.text(), 'red', 'recarga sin red: la última página guardada');
  r = await w.dispatch(`${O}/static/js/contingency.js?v=222`); assert.strictEqual(await r.res.text(), 'js', 'estático de otra versión (?v=) como respaldo');
  r = await w.dispatch(`${O}/kiosk/8/registro`, { mode: 'navigate' }); assert.strictEqual(r.res.status, 503, 'sin copia guardada: respuesta clara'); assert.ok(/Sin conexión/.test(await r.res.text()));
  await assert.rejects(w.dispatch(`${O}/static/js/otro.js`), /Failed to fetch/);

  // con red el servidor manda: lo nuevo reemplaza lo guardado; un 502 de la infraestructura sirve la última página buena
  w.setNet(async () => R('pagina nueva')); r = await w.dispatch(`${O}/kiosk/7/registro`, { mode: 'navigate' }); assert.strictEqual(await r.res.text(), 'pagina nueva');
  w.setNet(async () => R('Bad Gateway', 502)); r = await w.dispatch(`${O}/kiosk/7/registro`, { mode: 'navigate' }); assert.strictEqual(await r.res.text(), 'pagina nueva');
  r = await w.dispatch(`${O}/kiosk/8/registro`, { mode: 'navigate' }); assert.strictEqual(r.res.status, 502, 'sin copia, el 502 se muestra tal cual');

  // NO se guardan redirecciones (sesión vencida → /login) ni errores: no se «congela» una pantalla de login o de error
  w.setNet(async () => R('login', 200, { redirected: true })); await w.dispatch(`${O}/kiosk/9/registro`, { mode: 'navigate' });
  w.setNet(async () => R('no', 403)); await w.dispatch(`${O}/kiosk/10/registro`, { mode: 'navigate' });
  w.setNet(async () => R('x', 404)); await w.dispatch(`${O}/static/js/no-existe.js`);
  assert.ok(![...cache.keys()].some((k) => /\/9\/|\/10\/|no-existe/.test(k)), 'no guarda redirecciones ni errores');

  // espera máxima de 4 s con la red colgada: usa lo guardado
  w.setNet((req, init) => new Promise((_, rej) => { init.signal.addEventListener('abort', () => rej(new Error('abortado'))); }));
  const t0 = Date.now(); r = await w.dispatch(`${O}/kiosk/7/registro`, { mode: 'navigate' }); const waited = Date.now() - t0;
  assert.strictEqual(await r.res.text(), 'pagina nueva'); assert.ok(waited >= 3900 && waited < 4600, `esperó ${waited} ms (deben ser ~4 s)`);

  // DETRÁS DE FIREBASE HOSTING: las respuestas llevan Vary: Accept-Encoding, cookie, need-authorization, x-fh-requested-host (y la app, Cookie/Accept-Encoding). Con la Cache API real
  // (semántica de Vary), guardar la respuesta tal cual y buscarla con la petición de navegación NO coincide; el worker guarda una copia sin Vary y busca por texto con ignoreVary.
  const FH = { 'Vary': 'Cookie, Accept-Encoding, cookie, need-authorization, x-fh-requested-host', 'Content-Encoding': 'gzip', 'Content-Length': '999', 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'private' };
  const fhPage = (txt, status = 200) => R2(txt, status, FH);
  function R2(text, status, headers) { const r = new Response(text, { status, headers }); Object.defineProperty(r, 'type', { value: 'basic' }); return r; }
  const wf = makeWorker('rev9-fh');
  wf.setNet(async () => fhPage('pagina de firebase'));
  let rf = await wf.dispatch(`${O}/kiosk/3/registro`, { mode: 'navigate' }); assert.strictEqual(await rf.res.text(), 'pagina de firebase');
  const fhCache = await (async () => { const m = wf.store.get('golden-kiosk-shell-rev9-fh'); return m; })();
  const saved = [...fhCache.values()][0].res; assert.strictEqual(saved.headers.get('vary'), null, 'la copia guardada no lleva Vary'); assert.strictEqual(saved.headers.get('content-encoding'), null, 'ni Content-Encoding (el cuerpo ya viene descomprimido)'); assert.strictEqual(saved.headers.get('content-length'), null);
  assert.strictEqual(saved.headers.get('content-type'), 'text/html; charset=utf-8');
  // la prueba de que el problema existía: la respuesta CON Vary guardada tal cual no coincide con la navegación (lo que hacía el worker anterior)
  wf.setNet(async () => { throw new TypeError('Failed to fetch'); });
  for (const nav of [`${O}/kiosk/3/registro`, `${O}/kiosk/3/registro?tab=2&x=1`, `${O}/kiosk/3/registro/`]) {
    rf = await wf.dispatch(nav, { mode: 'navigate' }); assert.strictEqual(rf.res.status, 200, `sin red debe servir ${nav}`); assert.strictEqual(await rf.res.text(), 'pagina de firebase');
  }
  // la petición de navegación lleva cabeceras que la guardada no tenía (Accept, Accept-Encoding, Cookie…): da igual
  rf = await wf.dispatch(`${O}/kiosk/3/registro`, { mode: 'navigate', headers: { accept: 'text/html,application/xhtml+xml', 'accept-encoding': 'br', cookie: '__session=abc', 'x-fh-requested-host': 'staging.web.app' } }); assert.strictEqual(await rf.res.text(), 'pagina de firebase');
  // «Vary: *» (no se puede guardar con cache.put): en línea la página sale igual y sin red también (copia sin Vary)
  wf.setNet(async () => R2('vary comodin', 200, { Vary: '*' })); rf = await wf.dispatch(`${O}/kiosk/4/registro`, { mode: 'navigate' }); assert.strictEqual(await rf.res.text(), 'vary comodin', 'un fallo al guardar no rompe la respuesta en vivo');
  wf.setNet(async () => { throw new TypeError('x'); }); rf = await wf.dispatch(`${O}/kiosk/4/registro`, { mode: 'navigate' }); assert.strictEqual(await rf.res.text(), 'vary comodin');
  // estáticos de Firebase (Cache-Control público, Vary): sin red, con otro ?v=
  wf.setNet(async () => R2('css', 200, { Vary: 'Accept-Encoding, cookie', 'Cache-Control': 'public, max-age=3600', 'Content-Type': 'text/css' })); await wf.dispatch(`${O}/static/css/style.css?v=1790000000`);
  wf.setNet(async () => { throw new TypeError('x'); }); rf = await wf.dispatch(`${O}/static/css/style.css?v=1790000999`); assert.strictEqual(await rf.res.text(), 'css');
  // la sesión es por cookie y la página ya redirigió a /login (sesión vencida): NO se guarda ni se sirve en lugar de la buena
  wf.setNet(async () => R2('login', 200, { ...FH })); const redirected = R2('login', 200, FH); Object.defineProperty(redirected, 'redirected', { value: true });
  wf.setNet(async () => redirected); await wf.dispatch(`${O}/kiosk/3/registro`, { mode: 'navigate' });
  wf.setNet(async () => { throw new TypeError('x'); }); rf = await wf.dispatch(`${O}/kiosk/3/registro`, { mode: 'navigate' }); assert.strictEqual(await rf.res.text(), 'pagina de firebase', 'la redirección a /login no pisa la página guardada');

  // versión nueva: otro BUILD = otro caché; al activarse borra el anterior
  const w2 = makeWorker('rev2-bbb'); w2.store.set('golden-kiosk-shell-rev1-aaa', new Map());
  await new Promise((resolve) => w2.listeners.activate({ waitUntil: (p) => p.then(resolve) }));
  assert.deepStrictEqual([...w2.store.keys()], []); await w2.dispatch(`${O}/static/js/a.js`); assert.deepStrictEqual([...w2.store.keys()], ['golden-kiosk-shell-rev2-bbb']);
  console.log('kiosk-sw.js: solo caparazón, red primero, versionado y sin API OK');
})().catch((e) => { console.error(e); process.exit(1); });
