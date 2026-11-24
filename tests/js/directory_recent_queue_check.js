// Prueba de la cola compartida de recién registrados (recent_at) dentro del Directorio (static/js/directory.js, mountSearch con unified:true) con DOM y servidor falsos.
// Correr: node tests/js/directory_recent_queue_check.js
const fs = require('fs');
const assert = require('assert');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this._html = ''; this.offsetParent = {}; this.value = ''; this.className = ''; this.textContent = ''; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c) { c.parentNode = this; this.children.unshift(c); return c; }
  addEventListener(k, f) { this.listeners[k] = f; }
  set innerHTML(v) { this._html = v; this.children = []; }
  get innerHTML() { return this._html; }
  closest() { return table; }
  setAttribute() {}
  focus() { this.focused = true; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this); }
  get cells() { return this.children; }
  querySelector() { return null; }
  querySelectorAll(sel) {
    const cls = sel.slice(1);
    const out = []; const walk = (n) => n.children.forEach((c) => { if ((c.className || '').split(' ').includes(cls)) out.push(c); walk(c); }); walk(this); return out;
  }
  replaceChildren(...c) { c.forEach((x) => { x.parentNode = this; }); this.children = c; this._html = ''; }
}
const container = new El('div');
const table = container.appendChild(new El('table'));
let els = {};
const fresh = (withExtra) => { els = { tbody: new El('tbody'), cedula: new El('input'), hint: new El('p') }; if (withExtra) { els.nombre = new El('input'); els.entidad = new El('input'); } };
global.window = { EVENT_ID: 1, STAFF_ROLE: 'coordinador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [] };
global.document = { getElementById: (id) => (id === 'gwSearchHint' ? els.hint : els[id] || null), createElement: (t) => new El(t), visibilityState: 'visible', body: new El('body'), addEventListener: () => {} };
global.showToast = () => {};
global.setInterval = () => 1;
let now = 0, timers = [];
global.setTimeout = (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; };
global.clearTimeout = (t) => { timers = timers.filter((x) => x !== t); };
const advance = (ms) => { now += ms; const due = timers.filter((t) => t.at <= now); timers = timers.filter((t) => t.at > now); due.forEach((t) => t.f()); };


const store = {};
global.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
const base = Date.parse('2026-11-04T15:00:00Z');
const iso = (minAgo) => new Date(base - minAgo * 60000).toISOString().replace('.000Z', 'Z');
let users = [];
let delta = [];
for (let i = 0; i < 30; i++) users.push({ id: 'P' + String(i).padStart(2, '0'), first_name: 'Persona' + i, last_name: 'X', entity: 'E', status: 'Registrado', recent_at: null });
// 25 con recent_at distintos (en desorden); P25..P29 sin acción
const order = [...Array(25).keys()].sort((a, b) => ((a * 7) % 25) - ((b * 7) % 25));
order.forEach((idx, k) => { users[idx].recent_at = iso(k * 2); });         // k=0 la más nueva; k*2 min hacia atrás
global.fetch = async (url) => {
  const u = new URL(url, 'http://x');
  const json = (body, headers = {}) => ({ ok: true, status: 200, headers: { get: (k) => headers[k] ?? null }, json: async () => JSON.parse(JSON.stringify(body)) });
  if (u.pathname === '/api/users/changes') return json({ cursor: '1:1', total: users.length, users: delta });
  const limit = +u.searchParams.get('limit'), offset = +u.searchParams.get('offset');
  return json(users.slice(offset, offset + limit), { 'X-Total-Count': String(users.length) });
};
window.SearchCore = require('../../static/js/search-core.js');
eval(fs.readFileSync('static/js/directory.js', 'utf8'));
const rows = () => els.tbody.children.filter((tr) => tr.className !== 'directory-more' && tr.className !== 'directory-local-note');
const ids = () => rows().map((tr) => tr.dataset.userId);
const slot = (tr, f) => tr.children.find((c) => c.dataset && c.dataset.field === f);          // «Recién registrado» vive en su casilla propia (data-field=recent), junto al nombre
const tags = () => rows().filter((tr) => slot(tr, 'recent').children.some((c) => c.className.includes('gw-recent-tag'))).map((tr) => tr.dataset.userId);
const type = (el, text) => { el.value = text; el.listeners.input(); advance(250); };
const tick = () => new Promise((r) => setImmediate(r));
const mount = (extra) => window.GoldenDirectory.mountSearch(Object.assign({ tbodyId: 'tbody', unified: true, pageSize: 200, searchIds: { cedula: 'cedula', nombre: 'searchNombre', entidad: 'searchEntidad' } }, extra || {}));
const sortedServed = order.map((idx) => 'P' + String(idx).padStart(2, '0'));      // ya en orden de k (más nueva primero)

(async () => {
  fresh(false);
  const d = mount();
  await d.reload();
  assert.deepStrictEqual(ids(), sortedServed.concat(['P25', 'P26', 'P27', 'P28', 'P29']), 'orden completo sin tope: 25 con recent_at, luego nulos en su orden');
  // etiqueta: solo dentro de 15 min de la más nueva (k*2 < 15 -> k = 0..7)
  assert.deepStrictEqual(tags(), sortedServed.slice(0, 8));
  assert.ok(rows().slice(0, 8).every((tr) => tr.dataset.recent === '1') && rows().slice(8).every((tr) => tr.dataset.recent !== '1'));
  assert.strictEqual(slot(rows()[0], 'recent').children.find((c) => c.className.includes('gw-recent-tag')).textContent, 'Recién registrado');
  assert.ok(slot(rows()[0], 'recent').children.find((c) => c.className.includes('gw-recent-tag')).className.includes('gw-badge gw-recent-tag'));
  // alta manual («Registrar nuevo») = «Recién creado» en azul; acreditar a alguien de la base sigue siendo «Recién registrado» en verde (5-nov-2026)
  const nuevoId = rows()[0].dataset.userId; users.find((u) => u.id === nuevoId).origin = 'manual'; users.find((u) => u.id === rows()[1].dataset.userId).origin = 'base';
  await d.reload();
  const tagOf = (i) => slot(rows()[i], 'recent').children.find((c) => c.className.includes('gw-recent-tag'));
  assert.strictEqual(tagOf(0).textContent, 'Recién creado'); assert.ok(tagOf(0).className.includes('gw-recent-tag--new'), 'la píldora de «Recién creado» es la azul');
  assert.strictEqual(tagOf(1).textContent, 'Recién registrado'); assert.ok(!tagOf(1).className.includes('gw-recent-tag--new'), 'la de «Recién registrado» sigue verde');
  // 24-nov-2026: guardar cambiando el estado a «No registrado» (coordinador+) deja a la persona No registrada → «Recién editado», nunca «Recién registrado»
  users.find((u) => u.id === rows()[1].dataset.userId).status = 'No registrado';
  await d.reload();
  assert.strictEqual(tagOf(1).textContent, 'Recién editado');

  // con consulta: manda SearchCore, no la recencia
  type(els.cedula, 'persona');
  assert.notDeepStrictEqual(ids().slice(0, 3), sortedServed.slice(0, 3), 'con consulta no se reordena por recencia');
  type(els.cedula, '');
  assert.deepStrictEqual(ids().slice(0, 25), sortedServed, 'al vaciar la caja vuelve la cola');
  d.clearFilters(); assert.deepStrictEqual(ids().slice(0, 25), sortedServed, 'Limpiar filtros también');
  assert.strictEqual(tags().length, 8, 'las etiquetas no se duplican al redibujar');

  // locales primero (aún sin recent_at del servidor), la más reciente primero; su valor del servidor manda cuando llega
  window.GoldenDirectory.noteRecent('P28'); window.GoldenDirectory.noteRecent('P27');
  d.clearFilters();
  assert.deepStrictEqual(ids().slice(0, 4), ['P27', 'P28', sortedServed[0], sortedServed[1]]);
  assert.ok(tags().includes('P27') && tags().includes('P28'), 'las locales sin recent_at llevan insignia');
  assert.strictEqual(ids().slice(-3).join(), 'P25,P26,P29', 'el resto conserva su orden original');

  // polling: recent_at de P29 llega y manda sobre lo local; P27 sigue local
  delta = [Object.assign({}, users[29], { recent_at: iso(-1) })];          // 1 minuto DESPUÉS de la más nueva
  await d.refresh();
  assert.deepStrictEqual(ids().slice(0, 3), ['P27', 'P28', 'P29'].slice(0, 2).concat(['P29']), 'locales primero y luego la nueva del servidor');
  assert.strictEqual(ids()[2], 'P29');
  assert.strictEqual(ids()[3], sortedServed[0]);
  assert.ok(tags().includes('P29'));
  delta = [Object.assign({}, users[24], { recent_at: iso(-5) })];          // la ventana se mide contra la nueva máxima: se cae la que estaba a 14 min
  await d.refresh();
  assert.ok(!tags().includes(sortedServed[7]), 'la ventana es relativa a la recent_at más nueva');
  delta = [];

  // sin red (lista local): solo lo local y el aviso
  fresh(false);
  window.GoldenContingency = { instance: {
    ready: Promise.resolve(), supported: true, active: () => true, rosterUsable: async () => true,
    localPeople: async () => [{ n: 'Carla Soto', c: [], s: 'No registrado', h: 'H:1' }, { n: 'Otro', c: [], s: 'No registrado', h: 'H:2' }],
    hashFor: async (c) => 'H:' + c, noteAuthGood() {}, noteScanExhausted() {},
  } };
  const dl = mount();
  await dl.reload(); await tick();
  assert.strictEqual(rows().length, 2); assert.deepStrictEqual(tags(), []);
  assert.ok(els.hint.textContent.includes('Ves lo que registra este equipo; lo de los demás llega al reconectar.'));
  type(els.cedula, 'carla');
  assert.ok(!els.hint.textContent.includes('Sin red: ves'), 'con consulta el aviso de cola no aplica');
  console.log('directory.js: cola de recien registrados OK');
})().catch((e) => { console.error(e); process.exit(1); });
