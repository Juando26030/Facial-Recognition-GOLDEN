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
  const caches = {
    open: async (name) => {
      if (!store.has(name)) store.set(name, new Map());
      const m = store.get(name);
      return {
        match: async (req, opts = {}) => { const k = opts.ignoreSearch ? [...m.keys()].find((u) => u.split('?')[0] === req.url.split('?')[0]) : req.url; return k && m.get(k) ? m.get(k).clone() : undefined; },
        put: async (req, res) => { m.set(typeof req === 'string' ? req : req.url, res); },
      };
    },
    keys: async () => [...store.keys()],
    delete: async (n) => store.delete(n),
  };
  const state = { skipWaiting: 0, claimed: 0 };
  const scope = { location: { origin: 'https://app.test' }, addEventListener: (k, f) => { listeners[k] = f; }, skipWaiting: () => { state.skipWaiting++; }, clients: { claim: async () => { state.claimed++; } } };
  const src = fs.readFileSync('static/js/kiosk-sw.js', 'utf8').split('__BUILD__').join(build);       // igual que el servidor (reemplaza todas las apariciones)
  let net = async () => R('red');
  const fetchFake = (req, init) => net(req, init);
  new Function('self', 'caches', 'fetch', 'Response', 'URL', 'AbortController', 'setTimeout', 'clearTimeout', src)(scope, caches, fetchFake, Response, URL, AbortController, setTimeout, clearTimeout);
  const dispatch = async (url, { method = 'GET', mode = 'cors' } = {}) => {
    let handled = null;
    listeners.fetch({ request: { url, method, mode }, respondWith: (p) => { handled = p; } });
    return handled ? { handled: true, res: await handled } : { handled: false };
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

  // versión nueva: otro BUILD = otro caché; al activarse borra el anterior
  const w2 = makeWorker('rev2-bbb'); w2.store.set('golden-kiosk-shell-rev1-aaa', new Map());
  await new Promise((resolve) => w2.listeners.activate({ waitUntil: (p) => p.then(resolve) }));
  assert.deepStrictEqual([...w2.store.keys()], []); await w2.dispatch(`${O}/static/js/a.js`); assert.deepStrictEqual([...w2.store.keys()], ['golden-kiosk-shell-rev2-bbb']);
  console.log('kiosk-sw.js: solo caparazón, red primero, versionado y sin API OK');
})().catch((e) => { console.error(e); process.exit(1); });
