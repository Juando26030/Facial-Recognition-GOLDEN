// Prueba del reintento automático de la estación de cédula (static/js/directory.js::postWithRetry) con un DOM, un reloj y un servidor falsos. Correr: node tests/js/directory_checkin_retry_check.js
// Comprueba: tiempo de espera de 10 s por intento (aborta y reintenta), hasta 2 reintentos ante 502/503/504 o error de red, SIEMPRE con el mismo client_id (el servidor no duplica),
// aviso discreto mientras reintenta (y se quita al terminar) y que tras el último intento se muestra el error en vez de quedarse esperando.
const fs = require('fs');
const assert = require('assert');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this._html = ''; this.offsetParent = {}; this.value = ''; this.attrs = {}; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c) { c.parentNode = this; this.children.unshift(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this); }
  addEventListener(k, f) { this.listeners[k] = f; }
  set innerHTML(v) { this._html = v; this.children = []; }
  get innerHTML() { return this._html; }
  closest() { return table; }
  setAttribute(k, v) { this.attrs[k] = v; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  replaceChildren(...c) { c.forEach(x => { x.parentNode = this; }); this.children = c; this._html = ''; }
}
const container = new El('div');
const table = container.appendChild(new El('table'));
const els = { tbody: new El('tbody'), cedula: new El('input') };
const body = new El('body');
global.window = { EVENT_ID: 7, STAFF_ROLE: 'coordinador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [] };
global.document = { getElementById: id => els[id] || null, createElement: t => new El(t), visibilityState: 'visible', body, addEventListener() {} };
global.setInterval = () => 1;
let now = 0, timers = [];
global.setTimeout = (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; };
global.clearTimeout = t => { timers = timers.filter(x => x !== t); };
const flush = () => new Promise(r => setImmediate(r));
const advance = async ms => { now += ms; const due = timers.filter(t => t.at <= now); timers = timers.filter(t => t.at > now); due.forEach(t => t.f()); await flush(); };
const toasts = [];
global.showToast = (m, t) => toasts.push([m, t]);

let script = [];            // por intento: 'hang' | 'net' | número de estado
let posts = [];             // client_id de cada POST
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, json: async () => data });
global.fetch = (url, init = {}) => {
  const u = new URL(url, 'http://x');
  if (u.pathname === '/api/users/changes') return Promise.resolve(json(200, { cursor: '1:1', total: 0, users: [] }));
  if (u.pathname === '/api/users') return Promise.resolve(json(200, []));
  assert.strictEqual(u.pathname, '/api/checkin-cedula');
  posts.push(init.body.get('client_id'));
  const step = script.shift();
  if (step === 'hang') return new Promise((_, rej) => init.signal.addEventListener('abort', () => rej(new Error('AbortError'))));
  if (step === 'net') return Promise.reject(new TypeError('Failed to fetch'));
  if (step === 200) return Promise.resolve(json(200, { result: 'SÍ', data: { id: '1001', first_name: 'Ana', last_name: 'Pérez' } }));
  return Promise.resolve(json(step, {}));
};
// AbortController mínimo (Node trae el real, pero este usa el reloj falso igual: solo hace falta `abort` y `signal`).
eval(fs.readFileSync('static/js/directory.js', 'utf8'));

(async () => {
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula' }, fastCheckin: true });
  const run = async (steps, advances) => {
    script = steps.slice(); posts = []; toasts.length = 0;
    const p = d.submitScannedCedula('1001');
    await flush();
    for (const ms of advances) { await advance(ms); }
    await p;
  };

  // 1) 502, 503 y por fin 200: tres POST con el MISMO client_id, aviso mientras reintenta y NINGÚN error al operador.
  const p1 = (async () => { script = [502, 503, 200]; posts = []; toasts.length = 0; const p = d.submitScannedCedula('1001'); await flush(); return p; })();
  await flush();
  assert.strictEqual(body.children.length, 1, 'debe haber un aviso mientras reintenta');
  assert.strictEqual(body.children[0].attrs['aria-live'], 'polite');
  await advance(400); assert.strictEqual(body.children.length, 1);
  await advance(800);
  await p1;
  assert.strictEqual(posts.length, 3); assert.strictEqual(new Set(posts).size, 1, 'el reintento debe reusar el client_id');
  assert.strictEqual(body.children.length, 0, 'el aviso se quita al terminar');
  assert.ok(toasts.some(([m, t]) => /Acreditado: Ana/.test(m) && t === 'success') && !toasts.some(([, t]) => t === 'error'));

  // 2) Un intento que no responde se aborta a los 10 s y se reintenta solo (con el mismo client_id).
  script = ['hang', 200]; posts = []; toasts.length = 0;
  const p2 = d.submitScannedCedula('1001'); await flush();
  await advance(9999); assert.strictEqual(posts.length, 1, 'antes de 10 s no se rinde');
  await advance(1); await advance(400);
  await p2;
  assert.strictEqual(posts.length, 2); assert.strictEqual(new Set(posts).size, 1);
  assert.ok(toasts.some(([m]) => /Acreditado: Ana/.test(m)));

  // 3) Error de red, luego 504, luego 200: se recupera con 2 reintentos.
  script = ['net', 504, 200]; posts = []; toasts.length = 0;
  const p3 = d.submitScannedCedula('1001'); await flush(); await advance(400); await advance(800); await p3;
  assert.strictEqual(posts.length, 3); assert.ok(toasts.some(([m]) => /Acreditado: Ana/.test(m)));

  // 4) Tres fallos seguidos: no reintenta sin fin (3 intentos), avisa del error y quita el aviso.
  script = [502, 502, 502]; posts = []; toasts.length = 0;
  const p4 = d.submitScannedCedula('1001'); await flush(); await advance(400); await advance(800); await p4;
  assert.strictEqual(posts.length, 3); assert.ok(toasts.some(([, t]) => t === 'error')); assert.strictEqual(body.children.length, 0);

  // 5) Un 500 NO se reintenta (es de la app), y dos escaneos distintos usan client_id distintos.
  script = [500]; posts = []; toasts.length = 0;
  await d.submitScannedCedula('1001'); const first = posts[0];
  assert.strictEqual(posts.length, 1);
  script = [200]; posts = []; await d.submitScannedCedula('1001');
  assert.notStrictEqual(posts[0], first);
  console.log('directory.js: reintento automático de la estación OK (10 s, 2 reintentos, mismo client_id, aviso discreto)');
})().catch(e => { console.error(e); process.exit(1); });
