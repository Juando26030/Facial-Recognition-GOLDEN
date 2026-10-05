// Prueba de la RECARGA sin red / con red muerta (LOCAL-FIRST, docs/15 D2.5h) con tiempo virtual, DOM, IndexedDB y red falsos. Correr: node tests/js/offline_reload_check.js
// Criterio: recarga con red muerta («lie-fi») => lista local en ≤ 3 s y franja de contingencia en ≤ 5 s del primer fallo; recargar en contingencia entra directo sin pedir nada; red lenta => lista local y reintento.
// (Chrome Offline real, modo avión real, iPad Safari como PWA: pruebas en dispositivos, ver docs/runbook_evento.md.)
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
// «Red muerta» (lie-fi: wifi conectado, sin internet): las peticiones NO fallan, se quedan colgadas hasta que alguien las aborta o el navegador se rinde (HANG_MS = 30 s).
const HANG_MS = 30000; let slowChanges = 0; const netCalls = [];
const wait = (ms, signal, failWith) => new Promise((res, rej) => {
  const fail = () => rej(Object.assign(new Error('x'), { name: signal && signal.aborted ? 'AbortError' : 'TypeError' }));
  timers.push({ f: () => (failWith ? fail() : res()), at: now + ms });
  if (signal) signal.addEventListener('abort', fail);
});
global.fetch = async (url, init = {}) => {
  const p0 = new URL(url, 'http://x').pathname; netCalls.push(p0);
  if (netDown) return wait(HANG_MS, init.signal, true);
  if (slowChanges && p0 === '/api/users/changes') await wait(slowChanges, init.signal, false);
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
const rows = () => els.tbody.children.filter((tr) => !/directory-(local-note|more)/.test(tr.className));
const names = () => rows().map((tr) => tr.children[2].innerText);

const sec = () => (now - T0) / 1000;
const shown = () => (els.tbody._html.includes('Cargando') ? 'cargando' : (rows().length ? `filas:${rows().length}` : 'vacía'));
const stepTo = async (t) => { for (let s = sec(); s < t; s += 0.1) await advance(100); };
const idb = fakeIndexedDB();
const mkGC = () => C.create({ idb, fetch: (u, i) => global.fetch(u, i), now: () => now, document: global.document, subtle: crypto.subtle, eventId: 1, uuid: () => 'u', setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });

(async () => {
  ROSTER = [{ h: await fp('1001'), n: 'Ana Pérez', c: ['VIP'], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'Registrado' }, { h: await fp('1003'), n: 'Eva Ríos', c: ['Prensa'], s: 'No registrado' }];
  let GC = mkGC(); await GC.start({ eventId: 1, fastStart: true }); await flush(); await flush();          // con red: baja la copia local
  window.GoldenContingency = { instance: GC };
  assert.strictEqual(GC.state(), 'normal');

  // 1) RECARGA con la red MUERTA, sin estado recordado: la lista local en ≤ 3 s y la franja de contingencia en ≤ 5 s del primer fallo (la sonda corta falla a los 2 s; la segunda, a los 4 s)
  netDown = true; netCalls.length = 0; now = T0; timers = [];
  GC = mkGC(); window.GoldenContingency = { instance: GC }; window.GoldenContingency.instance.start = GC.start;
  await GC.start({ eventId: 1, fastStart: true }); await flush();
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
  await stepTo(1.9); assert.strictEqual(shown(), 'cargando', 'a los 1,9 s todavía espera (tope de 2 s)');
  await stepTo(2.3); assert.strictEqual(shown(), 'filas:3', 'a los ~2 s la lista local ya está pintada: ' + shown()); assert.deepStrictEqual(names(), ['Ana Pérez', 'Luis Gómez', 'Eva Ríos']);
  assert.ok(/LISTA LOCAL/.test((els.tbody.children.find((tr) => /directory-local-note/.test(tr.className)) || { children: [{ innerText: '' }] }).children[0].innerText), 'avisa que es la lista local');
  assert.notStrictEqual(GC.state(), 'contingency', 'a los 2,3 s aún no (primer fallo a los 2 s)');
  await stepTo(4.3); assert.strictEqual(GC.state(), 'contingency', 'franja de contingencia a los ≤ 4,3 s del arranque (≤ 2,3 s del primer fallo)');
  assert.strictEqual(shown(), 'filas:3');
  // sin reintentar la red en contingencia: ni cargas de la lista ni esperas largas
  const usersCallsBefore = netCalls.filter((p) => p.startsWith('/api/users')).length;
  await stepTo(40); assert.strictEqual(netCalls.filter((p) => p.startsWith('/api/users')).length, usersCallsBefore, 'en contingencia no se pide la lista');

  // 2) RECARGAR YA EN CONTINGENCIA (el estado se recuerda): entra directo, SIN ninguna petición, lista local y franja desde el primer instante
  netCalls.length = 0; now = T0; timers = [];
  GC = mkGC(); window.GoldenContingency = { instance: GC };
  await GC.start({ eventId: 1, fastStart: true }); await flush();
  assert.strictEqual(GC.state(), 'contingency', 'recordó la contingencia: franja inmediata');
  const d2 = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
  await advance(50); assert.strictEqual(shown(), 'filas:3', 'lista local al instante (≤ 0,1 s): ' + shown());
  assert.ok(!netCalls.some((p) => p.startsWith('/api/users')), 'no pidió la lista al servidor');
  await stepTo(5);
  assert.strictEqual(GC.state(), 'contingency', 'con la red muerta se queda en contingencia'); assert.strictEqual(shown(), 'filas:3');

  // 3) VUELVE LA RED: el arranque rápido (2 sondas buenas + la autenticada) saca de contingencia en < 1 s y la lista del servidor reemplaza a la local
  netDown = false; healthOk = true; usersCalls = 0;
  await GC.burst(); await advance(50); await flush();
  assert.strictEqual(GC.state(), 'normal', 'salió de contingencia'); assert.ok(usersCalls > 0, 'recargó desde el servidor'); assert.deepStrictEqual(names(), ['Ana']);
  assert.strictEqual(els.entidad.disabled, false);

  // 4) RED LENTA pero viva (la lista tarda 3 s; /health responde): a los 2 s se pinta la lista local, SIN entrar a contingencia, y se reintenta en segundo plano hasta traer la del servidor
  slowChanges = 3000; usersCalls = 0; netCalls.length = 0; now = T0; timers = [];
  GC = mkGC(); window.GoldenContingency = { instance: GC };
  await GC.start({ eventId: 1, fastStart: true }); await flush();
  assert.strictEqual(GC.state(), 'normal');
  const d3 = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
  await stepTo(2.3); assert.strictEqual(shown(), 'filas:3', 'a los ~2 s: lista local mientras la red lenta responde'); assert.strictEqual(GC.state(), 'normal', 'la red está viva: no es contingencia');
  slowChanges = 0; await stepTo(9); await flush();                                     // el reintento (a los 3 s del fallo) ya no es lento
  assert.deepStrictEqual(names(), ['Ana'], 'el reintento en segundo plano trajo la lista del servidor'); assert.ok(!els.tbody.children.some((tr) => /directory-local-note/.test(tr.className)));
  void d; void d2; void d3;
  console.log('offline-recarga: lista local ≤ 3 s, franja ≤ 5 s, estado recordado y red lenta OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
