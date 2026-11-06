// Prueba de «✅ Acreditar» en TODAS las filas con «Deshacer» (docs/16, 7a) con DOM, IndexedDB y red falsos. Correr: node tests/js/row_accredit_check.js
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
const realSetTimeout = global.setTimeout;                       // el reloj virtual de abajo no sirve para esperar a crypto.subtle (hilos reales)
global.setTimeout = (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; };
global.clearTimeout = (t) => { timers = timers.filter((x) => x !== t); };
// Esperas por EVENTO, no por «N vueltas»: cifrar/descifrar la cola (crypto.subtle) corre en hilos reales del sistema y con la máquina cargada tarda más que cualquier número fijo de vueltas
// (fallaba 35 de 200 corridas con 48 en paralelo, siempre en «Deshacer la quitó de la cola»). settle() espera a que no quede crypto en vuelo; until() espera al aviso real.
const { settle: flush, until } = require('./settle');
const advance = async (ms) => { now += ms; const due = timers.filter((t) => t.at <= now); timers = timers.filter((t) => t.at > now); due.forEach((t) => t.f()); await flush(); };
const toasts = []; global.showToast = (m, t, o) => { toasts.push({ m, t, o }); return { close() {} }; };
global.CSS = { escape: (x) => x };

const hex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
const SALT = 'd'.repeat(32);
const fp = async (c) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${c}`))).slice(0, 16);
const json = (status, data, headers = {}) => ({ ok: status >= 200 && status < 300, status, headers: { get: (k) => headers[k] ?? null }, json: async () => data });
let netDown = false, healthOk = true, usersCalls = 0, ROSTER = [];
const SERVER = [{ id: '1001', first_name: 'Ana', last_name: 'Pérez', entity: 'ACME', status: 'No registrado' }];
const posts = []; let undoReply = { status: 200, body: { undone: true } };
global.fetch = async (url, init = {}) => {
  if (netDown) throw new TypeError('Failed to fetch');
  const u = new URL(url, 'http://x');
  if (u.pathname === '/api/checkin-cedula') { const fd = init.body; posts.push({ path: u.pathname, cedula: fd.get('cedula'), client_id: fd.get('client_id'), confirm: fd.get('confirm') }); return json(200, { result: 'SÍ', data: { id: fd.get('cedula'), first_name: 'Ana', last_name: 'Pérez' } }); }
  if (u.pathname.endsWith('/accreditations/undo')) { posts.push({ path: u.pathname, body: JSON.parse(init.body) }); return json(undoReply.status, undoReply.body); }
  if (u.pathname === '/health') { if (!healthOk) throw new TypeError('x'); return json(200, {}); }
  if (u.pathname === '/api/ping-auth') return json(200, {});
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 1, status: 'en_proceso', auto_register: true }, salt: SALT, count: ROSTER.length, people: ROSTER });
  if (u.pathname === '/api/users/changes') { usersCalls++; return json(200, { cursor: '1:1', total: SERVER.length, users: [] }); }
  if (u.pathname === '/api/users') { usersCalls++; return json(200, SERVER, { 'X-Total-Count': String(SERVER.length) }); }
  if (u.pathname.endsWith('/access-logs/sync')) return json(200, { results: [] });
  throw new Error('ruta inesperada ' + u.pathname);
};
eval(fs.readFileSync('static/js/directory.js', 'utf8'));

const actionBtn = (tr) => tr.children[0].children.find((b) => /btn-accredit-row/.test(b.className));
const rowByName = (name) => rows().find((tr) => tr.children[2].innerText === name);
const rows = () => els.tbody.children.filter((tr) => !/directory-(local-note|more)/.test(tr.className));
const lastToast = () => toasts[toasts.length - 1];

(async () => {
  window.EVENT_ID = 1;
  // ---- EN LÍNEA: botón «✅ Acreditar» en TODAS las filas; la ya acreditada muestra «Acreditado» sin acción
  SERVER.length = 0; SERVER.push({ id: '1001', first_name: 'Ana', last_name: 'Pérez', entity: 'ACME', status: 'No registrado' }, { id: '1002', first_name: 'Luis', last_name: 'Gómez', entity: 'ACME', status: 'Registrado' });
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
  await d.reload(); await advance(10);
  assert.strictEqual(rows().length, 2); const ana = actionBtn(rowByName('Ana')), luis = actionBtn(rowByName('Luis'));
  assert.ok(ana && !ana.disabled && /Acreditar/.test(ana.innerText), 'botón en la fila pendiente'); assert.ok(luis && luis.disabled && /Acreditado/.test(luis.innerText), 'la ya acreditada: «Acreditado», sin acción');
  // sin permiso de acreditar (cliente): ninguna fila lleva el botón
  const d0 = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: false }); await d0.reload(); await advance(10);
  assert.ok(!rows().some((tr) => actionBtn(tr)), 'sin fastCheckin no hay botones');
  const d1 = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true }); await d1.reload(); await advance(10);

  // clic: acredita con client_id y confirmación, y ofrece «Deshacer» ~8 s
  const click1 = actionBtn(rowByName('Ana')).listeners.click(); await click1; await advance(10);
  const checkin = posts.find((p) => p.path === '/api/checkin-cedula'); assert.ok(checkin && checkin.cedula === '1001' && checkin.confirm === 'true' && checkin.client_id, 'acredita con confirm y client_id: ' + JSON.stringify(checkin));
  const undoToast = toasts.find((t) => t.o && t.o.action); assert.ok(undoToast && undoToast.o.action.label === 'Deshacer' && undoToast.o.duration === 8000 && /Ana/.test(undoToast.m), 'ofrece Deshacer ~8 s');
  // Deshacer: llama al servidor con el MISMO client_id
  posts.length = 0; undoToast.o.action.onClick(); await until(() => /deshecha/.test((lastToast() || {}).m || ''), 'aviso «deshecha» (en línea)'); await advance(10);
  const undo = posts.find((p) => /undo/.test(p.path)); assert.ok(undo && undo.body.client_id === checkin.client_id, 'deshace con el mismo client_id'); assert.ok(/deshecha/.test(lastToast().m) && lastToast().t === 'success');
  // el servidor puede negarlo (otra persona / pasaron 15 s): se muestra su motivo
  toasts.length = 0; undoReply = { status: 409, body: { detail: 'Pasaron más de 15 segundos: ya no se puede deshacer desde aquí.' } };
  await actionBtn(rowByName('Ana')).listeners.click(); await advance(10); posts.length = 0;
  toasts.find((t) => t.o && t.o.action).o.action.onClick(); await until(() => /Pasaron más de 15 segundos/.test((lastToast() || {}).m || ''), 'motivo del servidor'); await advance(10);
  assert.ok(/Pasaron más de 15 segundos/.test(lastToast().m) && lastToast().t === 'error', lastToast().m);

  // ---- SIN RED: la fila local se acredita por huella (cola local) y «Deshacer» la quita de la cola (aún no se envió)
  ROSTER = [{ h: await fp('1001'), n: 'Ana Pérez', c: [], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'Registrado' }];
  const GC = C.create({ idb: fakeIndexedDB(), fetch: global.fetch, now: () => now, document: global.document, subtle: crypto.subtle, eventId: 1, uuid: () => 'u', setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });
  await GC.start(); await flush(); await flush(); window.GoldenContingency = { instance: GC };
  netDown = true; healthOk = false; await GC.checkHealth(); await GC.checkHealth(); assert.strictEqual(GC.active(), true);
  els.cedula.value = ''; els.nombre.value = ''; els.entidad.value = '';                  // el flujo en línea dejó la cédula escrita en el filtro
  const d2 = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true }); await d2.reload(); await advance(10);
  assert.strictEqual(rows().length, 2); const b = actionBtn(rowByName('Ana Pérez')); assert.ok(b && !b.disabled, 'botón también en la lista local');
  toasts.length = 0; await b.listeners.click(); await advance(10);
  assert.strictEqual((await GC.queueList()).length, 1, 'quedó en la cola local'); const offToast = toasts.find((t) => t.o && t.o.action); assert.ok(offToast, 'ofrece Deshacer');
  offToast.o.action.onClick(); await until(() => /deshecha|Ya se envió|No se pudo/.test((lastToast() || {}).m || ''), 'aviso de Deshacer (sin red)'); await advance(10);
  assert.strictEqual((await GC.queueList()).length, 0, 'Deshacer la quitó de la cola'); assert.ok(/deshecha/.test(lastToast().m));
  assert.strictEqual(rowByName('Ana Pérez').className, 'row-noregistrado', 'la fila vuelve a «No registrado»'); assert.ok(!actionBtn(rowByName('Ana Pérez')).disabled);
  // tarjeta del modo «Registro touch» (25-oct-2026): cada celda dice qué es (la tarjeta de dos filas se arma con CSS) y la empresa va en una celda que solo se ve en ese modo
  {
    const tr = rows()[0];
    const fields = tr.children.map((td) => td.dataset.field || td.className);
    assert.deepStrictEqual(fields, ['action-cell', 'id', 'first_name', 'last_name', 'opt_1', 'status', 'entity', 'origin', 'recent', 'reason'], fields.join(','));
    const ent = tr.children.find((td) => td.dataset.field === 'entity');
    assert.strictEqual(ent.className, 'touch-only'); assert.ok(typeof ent.innerText === 'string');
    assert.ok(tr.children[0].children.length >= 1, 'los botones siguen en su celda (mismo comportamiento)');
  }
  console.log('directory.js: «✅ Acreditar» en todas las filas con «Deshacer» (en línea y sin red) OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
