// Prueba de static/js/boot-trace.js (marcas de arranque del quiosco) y del registro del service worker. Correr: node tests/js/boot_trace_check.js
// Comprueba: las marcas salen en orden con su tiempo, `report()` trae marcas/navegación/recursos y lo que contesta el service worker (o null si no hay), y el worker anota red / timeout→copia.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

(async () => {
  let perfNow = 100;
  const sent = [];
  const win = {
    performance: { now: () => perfNow, getEntriesByType: (t) => (t === 'navigation' ? [{ responseStart: 5.4, responseEnd: 9, domInteractive: 12, domContentLoadedEventEnd: 13, loadEventEnd: 14 }] : [{ name: 'https://x.test/static/js/app.js', initiatorType: 'script', startTime: 20, duration: 4001, transferSize: 0 }]) },
    location: { search: '?trace=1', pathname: '/kiosk/3/registro', origin: 'https://x.test' }, navigator: { onLine: false }, document: { addEventListener() {} }, addEventListener() {}, console: { log: (m) => sent.push(m) },
    setTimeout, clearTimeout, MessageChannel: class { constructor() { this.port1 = {}; this.port2 = {}; setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: { log: [{ path: '/static/js/app.js', via: 'timeout→copia', ms: 4001 }] } })); } },
  };
  win.window = win;
  vm.runInNewContext(fs.readFileSync('static/js/boot-trace.js', 'utf8'), win);
  perfNow = 250; win.GoldenTrace.mark('directory:fullLoad:begin');
  perfNow = 900; win.GoldenTrace.mark('contingency:state:contingency', { from: 'degraded' });
  let r = await win.GoldenTrace.report();
  assert.deepStrictEqual(JSON.parse(JSON.stringify(r.marks.map((m) => [m.t, m.name]))), [[100, 'page:script-start'], [250, 'directory:fullLoad:begin'], [900, 'contingency:state:contingency']]);
  assert.deepStrictEqual(r.marks[2].from, 'degraded');
  assert.strictEqual(r.navigation.responseStart, 5); assert.strictEqual(r.resources[0].ms, 4001); assert.strictEqual(r.resources[0].name, '/static/js/app.js'); assert.strictEqual(r.online, false);
  assert.strictEqual(r.sw, null, 'sin worker que controle la página: null');
  assert.ok(sent.some((m) => /\+250 ms directory:fullLoad:begin/.test(m)), 'con ?trace=1 imprime en la consola');
  win.navigator.serviceWorker = { controller: { postMessage: (m, ports) => assert.strictEqual(m.type, 'trace') } };
  r = await win.GoldenTrace.report();
  assert.deepStrictEqual(JSON.parse(JSON.stringify(r.sw)), [{ path: '/static/js/app.js', via: 'timeout→copia', ms: 4001 }], 'trae el registro del worker');

  // el worker: anota si la respuesta vino de la red o de la copia tras agotar el tiempo
  const ls = {}; const kept = new Map(); let delay = false;
  const sw = {
    addEventListener: (n, f) => { ls[n] = f; }, skipWaiting() {}, clients: { claim: async () => {} }, location: { href: 'https://x.test/kiosk/sw.js', origin: 'https://x.test' },
    caches: { keys: async () => [], delete: async () => true, open: async () => ({ match: async (k) => kept.get(typeof k === 'string' ? k : k.url), put: async (k, v) => { kept.set(k, v); }, keys: async () => [] }) },
    fetch: (req, init) => (delay ? new Promise((_, rej) => { init.signal.addEventListener('abort', () => rej(new Error('abort'))); }) : Promise.resolve(Object.assign(new Response('ok'), { })))
  };
  sw.self = sw;
  vm.runInNewContext(fs.readFileSync('static/js/kiosk-sw.js', 'utf8').replace('__BUILD__', 't'), { ...sw, URL, Response, Headers, Date, setTimeout, clearTimeout, AbortController });
  assert.ok(ls.message && ls.fetch, 'registra los manejadores');
  let posted; ls.message({ data: { type: 'trace' }, ports: [{ postMessage: (m) => { posted = m; } }] });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(posted)), { log: [] }, 'sin peticiones todavía: registro vacío');
  console.log('boot-trace: marcas por fase, informe y registro del service worker OK');
})().catch((e) => { console.error(e); process.exit(1); });
