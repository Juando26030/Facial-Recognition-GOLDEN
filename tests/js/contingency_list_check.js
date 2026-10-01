// Prueba de la TABLA desde la copia local (static/js/directory.js + contingency.js) con DOM, IndexedDB y red falsos. Correr: node tests/js/contingency_list_check.js
// Comprueba: sin red (o ya en contingencia) la tabla sale del roster local con nombre, categorías y estado (contando lo encolado) y los contadores; nada de «Error conectando al servidor»;
// búsqueda por nombre y por cédula EXACTA (huella); filtro de entidad desactivado con aviso; al volver la red se recarga la lista del servidor.
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
let now = 7_000_000, timers = [];
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
global.fetch = async (url) => {
  if (netDown) throw new TypeError('Failed to fetch');
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
const names = () => rows().map((tr) => tr.children[2].innerText);                 // columna «Nombres» (después de la de acción y la de ID)
const type = async (el, text) => { el.value = text; el.listeners.input(); await advance(300); };

(async () => {
  ROSTER = [{ h: await fp('1001'), n: 'Ana Pérez', c: ['VIP'], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'Registrado' }, { h: await fp('1003'), n: 'Eva Ríos', c: ['Prensa', 'Staff'], s: 'No registrado' }];
  const GC = C.create({ idb: fakeIndexedDB(), fetch: global.fetch, now: () => now, document: global.document, subtle: crypto.subtle, eventId: 1, uuid: () => 'u', setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });
  await GC.start(); await flush(); await flush();                              // con red: baja la copia local
  window.GoldenContingency = { instance: GC };

  // 1) la carga de la lista FALLA (sin red) pero todavía no se entró en contingencia: lista local, nada de «Error conectando al servidor»
  netDown = true;
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
  await d.reload(); await advance(10);
  assert.ok(!/Error conectando/.test(els.tbody._html) && !els.tbody.children.some((tr) => /Error conectando/.test(tr.innerHTML || '')), 'no dice «Error conectando al servidor»');
  assert.deepStrictEqual(names(), ['Ana Pérez', 'Luis Gómez', 'Eva Ríos']);
  const note = els.tbody.children.find((tr) => /directory-local-note/.test(tr.className)); assert.ok(note && /LISTA LOCAL/.test(note.children[0].innerText), 'avisa con claridad que es la lista local');
  assert.deepStrictEqual(rows().map((tr) => tr.children[4].innerText), ['VIP', '', 'Prensa, Staff'], 'categorías');
  assert.deepStrictEqual(rows().map((tr) => tr.children[5].innerText), ['No registrado', 'Registrado', 'No registrado'], 'estado');
  const counters = table.parentNode.children.filter((c) => /counter/.test(c.className)); assert.ok(/2 sin registrar/.test(counters[0].innerText) && /1 registrados de 3/.test(counters[1].innerText), 'contadores: ' + counters.map((c) => c.innerText));
  assert.strictEqual(els.entidad.disabled, true); assert.ok(/No disponible sin conexión/.test(els.entidad.placeholder), 'filtro de entidad desactivado con aviso');

  // 2) búsqueda por nombre (sobre el roster) y por cédula EXACTA (huella)
  await type(els.nombre, 'eva'); assert.deepStrictEqual(names(), ['Eva Ríos']); await type(els.nombre, '');
  await type(els.cedula, '1002'); assert.deepStrictEqual(names(), ['Luis Gómez'], 'cédula exacta por huella');
  await type(els.cedula, '100'); assert.deepStrictEqual(names(), [], 'una cédula parcial no coincide (la copia no tiene la cédula)'); await type(els.cedula, '');
  assert.strictEqual(names().length, 3);

  // 3) lo encolado sin red cuenta como «Registrado» en la lista y en los contadores
  healthOk = false; await GC.checkHealth(); await GC.checkHealth(); assert.strictEqual(GC.active(), true);
  await d.submitScannedCedula('1003'); await advance(10);
  assert.deepStrictEqual(names(), ['Eva Ríos'], 'tras acreditar se resalta a la persona (filtra por su cédula)'); assert.strictEqual(rows()[0].children[5].innerText, 'Registrado'); await type(els.cedula, '');
  assert.deepStrictEqual(rows().map((tr) => tr.children[5].innerText), ['No registrado', 'Registrado', 'Registrado']);
  assert.ok(/1 sin registrar/.test(counters[0].innerText) && /2 registrados de 3/.test(counters[1].innerText));
  assert.strictEqual((await GC.queueList()).length, 1);

  // 4) recargar la página YA EN CONTINGENCIA: ni se intenta la red; la lista sale de la copia (y de la cola)
  usersCalls = 0; netDown = false;                                             // la red «responde», pero en contingencia no se usa
  await d.reload(); await advance(10);
  assert.strictEqual(usersCalls, 0, 'en contingencia no se pide la lista al servidor'); assert.deepStrictEqual(names(), ['Ana Pérez', 'Luis Gómez', 'Eva Ríos']);
  assert.deepStrictEqual(rows().map((tr) => tr.children[5].innerText), ['No registrado', 'Registrado', 'Registrado']);

  // 5) vuelve la red: sale de contingencia y se recarga la lista del servidor (con cédula y entidad)
  healthOk = true; await GC.checkHealth(); await GC.checkHealth(); await advance(50);
  assert.strictEqual(GC.state(), 'normal'); assert.ok(usersCalls > 0, 'recargó desde el servidor'); assert.deepStrictEqual(names(), ['Ana']);
  assert.strictEqual(els.entidad.disabled, false); assert.strictEqual(els.entidad.placeholder, 'Entidad');
  assert.ok(!els.tbody.children.some((tr) => /directory-local-note/.test(tr.className)));
  console.log('directory.js: la tabla sale de la copia local sin red (nombre, categorías, estado, contadores, búsqueda por huella) OK');
})().catch((e) => { console.error(e); process.exit(1); });
