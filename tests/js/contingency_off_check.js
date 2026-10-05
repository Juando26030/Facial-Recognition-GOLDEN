// Prueba del modo contingencia APAGADO (static/js/contingency-off.js y static/js/kiosk-sw-off.js) con entornos falsos. Correr: node tests/js/contingency_off_check.js
// Comprueba: desregistra el service worker del quiosco (y solo ese), borra los cachés `golden-kiosk-shell-*` (y solo esos), vacía roster y meta de cada `golden-contingency-*`
// SIN tocar la cola de ingresos sin sincronizar, no define GoldenContingency, y el worker «apagado» se desregistra y borra sus cachés al activarse.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const tick = () => new Promise((r) => setImmediate(r));

(async () => {
  // ---- página
  const unregistered = [], deleted = [], cleared = [], closed = [];
  const reg = (scope) => ({ scope, unregister: () => unregistered.push(scope) });
  const dbOf = (name, stores) => ({ objectStoreNames: { contains: (s) => stores.includes(s) }, close: () => closed.push(name),
    transaction: (names) => { const t = {}; t.objectStore = (s) => ({ clear: () => cleared.push(`${name}:${s}`) }); setImmediate(() => t.oncomplete && t.oncomplete()); return t; } });
  const win = {
    navigator: { serviceWorker: { getRegistrations: async () => [reg('https://x.test/kiosk/'), reg('https://x.test/otro/')] } },
    caches: { keys: async () => ['golden-kiosk-shell-abc', 'otra-cosa'], delete: async (k) => { deleted.push(k); } },
    indexedDB: {
      databases: async () => [{ name: 'golden-contingency-7' }, { name: 'ajena' }],
      open: (name) => { const r = {}; setImmediate(() => { r.result = dbOf(name, ['roster', 'meta', 'queue', 'review']); r.onsuccess(); }); return r; },
    },
  };
  win.window = win; win.URL = URL;
  vm.runInNewContext(fs.readFileSync('static/js/contingency-off.js', 'utf8'), win);
  await tick(); await tick(); await tick();
  assert.deepStrictEqual(unregistered, ['https://x.test/kiosk/'], 'solo desregistra el worker del quiosco');
  assert.deepStrictEqual(deleted, ['golden-kiosk-shell-abc'], 'solo borra los cachés del caparazón');
  assert.deepStrictEqual(cleared.sort(), ['golden-contingency-7:meta', 'golden-contingency-7:roster'], 'vacía roster y meta, NUNCA la cola ni la revisión');
  assert.deepStrictEqual(closed, ['golden-contingency-7']);
  assert.strictEqual(win.GoldenContingency, undefined, 'no define GoldenContingency');

  // ---- sin APIs (Safari viejo, navegación privada): no lanza
  vm.runInNewContext(fs.readFileSync('static/js/contingency-off.js', 'utf8'), { navigator: {}, window: {} });

  // ---- worker apagado
  const ls = {}, wdeleted = []; let unreg = 0, skipped = 0;
  const sw = { addEventListener: (n, f) => { ls[n] = f; }, skipWaiting: () => { skipped++; }, registration: { unregister: async () => { unreg++; } },
    caches: { keys: async () => ['golden-kiosk-shell-v1', 'otra'], delete: async (k) => { wdeleted.push(k); } } };
  sw.self = sw;
  vm.runInNewContext(fs.readFileSync('static/js/kiosk-sw-off.js', 'utf8'), { ...sw, caches: sw.caches });
  ls.install(); assert.strictEqual(skipped, 1);
  let pending; ls.activate({ waitUntil: (p) => { pending = p; } }); await pending;
  assert.deepStrictEqual(wdeleted, ['golden-kiosk-shell-v1']); assert.strictEqual(unreg, 1);
  assert.strictEqual(ls.fetch, undefined, 'no intercepta peticiones');
  console.log('contingency-off: limpia worker, cachés y roster sin tocar la cola OK');
})().catch((e) => { console.error(e); process.exit(1); });
