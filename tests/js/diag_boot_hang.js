// DIAGNÓSTICO (no es una prueba de CI: no termina en _check.js). Reproduce con tiempo virtual la recarga con la red COLGADA (wifi sin internet) y muestra CUÁNDO aparece la tabla.
// Correr: node tests/js/diag_boot_hang.js   (HANG_MS=30000 por defecto: lo que tarda el navegador en rendirse con una petición colgada)
const fs = require('fs');
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this._html = ''; this.offsetParent = {}; this.value = ''; this.attrs = {}; this.innerText = ''; this.className = ''; this.placeholder = ''; this.disabled = false; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) { c.parentNode = this; const i = ref ? this.children.indexOf(ref) : -1; if (i >= 0) this.children.splice(i, 0, c); else if (ref === null) this.children.push(c); else this.children.unshift(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
  addEventListener(k, f) { this.listeners[k] = f; }
  set innerHTML(v) { this._html = v; this.children = []; }
  get innerHTML() { return this._html; }
  closest() { return table; }
  setAttribute(k, v) { this.attrs[k] = v; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  replaceChildren(...c) { c.forEach((x) => { x.parentNode = this; }); this.children = c; this._html = ''; }
}
const container = new El('div');
const table = container.appendChild(new El('table'));
const els = { tbody: new El('tbody'), cedula: new El('input'), nombre: new El('input'), entidad: new El('input') };
els.entidad.placeholder = 'Entidad';
global.window = { EVENT_ID: 1, STAFF_ROLE: 'digitador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [] };
global.document = { getElementById: (id) => els[id] || null, createElement: (t) => new El(t), visibilityState: 'visible', head: new El('head'), body: new El('body'), addEventListener() {} };
global.setInterval = () => 1;
const T0 = 7_000_000; let now = T0, timers = [];
global.setTimeout = (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; };
global.clearTimeout = (t) => { timers = timers.filter((x) => x !== t); };
const flush = () => new Promise((r) => setImmediate(r));
const advance = async (ms) => { now += ms; const due = timers.filter((t) => t.at <= now); timers = timers.filter((t) => t.at > now); due.forEach((t) => t.f()); for (let i = 0; i < 15; i++) await flush(); };
global.showToast = () => {};
global.CSS = { escape: (x) => x };

const hex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
const SALT = 'd'.repeat(32);
const fp = async (c) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${c}`))).slice(0, 16);
const json = (status, data, headers = {}) => ({ ok: status >= 200 && status < 300, status, headers: { get: (k) => headers[k] ?? null }, json: async () => data });
let netDown = false, healthOk = true, usersCalls = 0, ROSTER = [];
const SERVER = [{ id: '1001', first_name: 'Ana', last_name: 'Pérez', entity: 'ACME', status: 'No registrado' }];
// «Sin red» de wifi-conectado-sin-internet (lie-fi): las peticiones NO fallan al instante, se quedan colgadas hasta que alguien las aborta o el navegador se rinde (HANG_MS).
const HANG_MS = Number(process.env.HANG_MS || 30000);
const hang = (signal) => new Promise((_, rej) => {
  const fail = () => rej(Object.assign(new Error('x'), { name: signal && signal.aborted ? 'AbortError' : 'TypeError' }));
  timers.push({ f: fail, at: now + HANG_MS });
  if (signal) signal.addEventListener('abort', fail);
});
global.fetch = async (url, init = {}) => {
  if (netDown) return hang(init.signal);
  const u = new URL(url, 'http://x');
  if (u.pathname === '/health') { if (!healthOk) throw new TypeError('x'); return json(200, {}); }
  if (u.pathname === '/api/ping-auth') return json(200, {});
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 1, status: 'en_proceso', auto_register: true }, salt: SALT, count: ROSTER.length, people: ROSTER });
  if (u.pathname === '/api/users/changes') { usersCalls++; return json(200, { cursor: '1:1', total: SERVER.length, users: [] }); }
  if (u.pathname === '/api/users') { usersCalls++; return json(200, SERVER, { 'X-Total-Count': '1' }); }
  if (u.pathname.endsWith('/access-logs/sync')) return json(200, { results: [] });
  throw new Error('ruta inesperada ' + u.pathname);
};
eval(fs.readFileSync('static/js/directory.js', 'utf8'));
const rows = () => els.tbody.children;

const log = (msg) => console.log(String(Math.round((now - T0) / 100) / 10).padStart(5) + ' s  ' + msg);
const shown = () => (els.tbody._html.includes('Cargando') ? 'Cargando base de datos…' : (els.tbody.children.length ? 'filas: ' + els.tbody.children.length : '(vacía)'));
window.GoldenTrace = { mark: (n, x) => log('[trace] ' + n + (x ? ' ' + JSON.stringify(x) : '')) };

(async () => {
  ROSTER = [{ h: await fp('1001'), n: 'Ana Pérez', c: ['VIP'], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'Registrado' }];
  const GC = C.create({ idb: fakeIndexedDB(), fetch: (u, i) => global.fetch(u, i), now: () => now, document: global.document, subtle: crypto.subtle, eventId: 1, uuid: () => 'u', setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });
  await GC.start(); await flush(); await flush();                                 // con red: baja la copia local
  window.GoldenContingency = { instance: GC };
  log('copia local lista; ahora la red queda COLGADA (lie-fi, HANG_MS=' + HANG_MS + ')');
  netDown = true;
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
  await advance(10);
  log('tabla: ' + shown());
  // el chequeo de salud corre cada 5 s (HEALTH_MS) con tope de 3 s (HEALTH_TIMEOUT_MS); 2 fallos seguidos = contingencia
  for (const at of [5000, 10000]) {
    await advance(at - (now - T0));
    const p = GC.checkHealth(); await advance(3000); await p;
    log('estado de contingencia: ' + GC.state() + ' · tabla: ' + shown());
  }
  for (const s of [20000, 30000, 30100, 40000]) { await advance(s - (now - T0)); log('tabla: ' + shown()); }
  log('(' + (shown().startsWith('filas') ? 'la lista local apareció' : 'sigue sin lista') + ')');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
