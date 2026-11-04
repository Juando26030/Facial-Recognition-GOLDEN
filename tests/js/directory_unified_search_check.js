// Prueba del buscador único dentro del Directorio (static/js/directory.js, mountSearch con unified:true) con DOM y servidor falsos.
// Correr: node tests/js/directory_unified_search_check.js
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
    if (sel !== '.gw-reason') return [];
    const out = []; const walk = (n) => n.children.forEach((c) => { if ((c.className || '').includes('gw-reason')) out.push(c); walk(c); }); walk(this); return out;
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

const users = [
  { id: '1012345678', first_name: 'Ana', last_name: 'Pérez', entity: 'Acme', status: 'No registrado' },
  { id: '10123', first_name: 'Luis', last_name: 'Mora', entity: 'Zeta', status: 'No registrado' },
  { id: '1012399', first_name: 'Pedro', last_name: 'Gómez', entity: 'Acme Logística', status: 'No registrado' },
  { id: '555000111', first_name: 'Marta', last_name: 'Ruiz', entity: 'Beta', status: 'No registrado' },
];
const checkins = [];
global.FormData = class { constructor() { this.m = {}; } append(k, v) { this.m[k] = v; } };
global.fetch = async (url, init) => {
  const u = new URL(url, 'http://x');
  const json = (body, headers = {}) => ({ ok: true, status: 200, headers: { get: (k) => headers[k] ?? null }, json: async () => JSON.parse(JSON.stringify(body)) });
  if (u.pathname === '/api/checkin-cedula') { checkins.push(init && init.body && init.body.m ? init.body.m.cedula : '?'); return json({ status: 'NO_MATCH' }); }
  if (u.pathname === '/api/users/changes') return json({ cursor: '1:1', total: users.length, users: [] });
  const limit = +u.searchParams.get('limit'), offset = +u.searchParams.get('offset');
  return json(users.slice(offset, offset + limit), { 'X-Total-Count': String(users.length) });
};

window.SearchCore = require('../../static/js/search-core.js');
eval(fs.readFileSync('static/js/directory.js', 'utf8'));
const rows = () => els.tbody.children.filter((tr) => tr.className !== 'directory-more' && tr.className !== 'directory-local-note');
const ids = () => rows().map((tr) => tr.dataset.userId);
const nameTd = (tr) => tr.children[2];
const reasonOf = (tr) => nameTd(tr).children.filter((c) => c.className.includes('gw-reason')).map((c) => c.textContent);
const type = (el, text) => { el.value = text; el.listeners.input(); advance(250); };
const enter = (el, text) => { el.value = text; let prevented = false; el.listeners.keydown({ key: 'Enter', preventDefault() { prevented = true; }, stopPropagation() {} }); return prevented; };
const tick = () => new Promise((r) => setImmediate(r));

(async () => {
  // --- modo unificado, con red
  fresh(false);
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', unified: true, fastCheckin: true, searchIds: { cedula: 'cedula', nombre: 'searchNombre', entidad: 'searchEntidad' } });
  await d.reload();
  assert.strictEqual(els.cedula.focused, true, 'la caja única recibe el foco al montar');
  assert.strictEqual(rows().length, 4);
  assert.strictEqual(els.hint.textContent, '');

  type(els.cedula, '10123');                                          // exacta primero, luego prefijo
  assert.deepStrictEqual(ids(), ['10123', '1012345678', '1012399']);
  assert.deepStrictEqual(reasonOf(rows()[0]), ['Cédula exacta']);
  assert.ok(reasonOf(rows()[1])[0].startsWith('Cédula (empieza por 10123'));
  assert.strictEqual(els.hint.textContent, '3 coincidencias');

  type(els.cedula, 'marta');                                          // nombre
  assert.deepStrictEqual(ids(), ['555000111']); assert.deepStrictEqual(reasonOf(rows()[0]), ['Nombre']);
  assert.strictEqual(els.hint.textContent, '1 coincidencia');
  type(els.cedula, 'logistica');                                      // empresa (sin tildes)
  assert.deepStrictEqual(ids(), ['1012399']); assert.deepStrictEqual(reasonOf(rows()[0]), ['Empresa']);
  type(els.cedula, 'zzzz');
  assert.strictEqual(rows().length, 0);
  assert.strictEqual(els.hint.textContent, 'Sin coincidencias. Revisa la cédula o prueba con el nombre.');
  type(els.cedula, '10123'); type(els.cedula, '10123');               // filas en caché: el motivo no se duplica
  assert.strictEqual(reasonOf(rows()[0]).length, 1);
  type(els.cedula, '');
  assert.strictEqual(rows().length, 4); assert.strictEqual(els.hint.textContent, '');
  assert.ok(rows().every((tr) => reasonOf(tr).length === 0), 'sin consulta no hay motivos');

  // Enter: nombre -> solo busca; cédula -> fastCheckin
  els.cedula.value = 'marta'; assert.ok(enter(els.cedula, 'marta'));
  await tick();
  assert.strictEqual(checkins.length, 0, 'Enter con nombre NO acredita');
  assert.strictEqual(els.cedula.value, 'marta', 'Enter con nombre no limpia la caja');
  assert.deepStrictEqual(ids(), ['555000111'], 'Enter con nombre filtra de inmediato');
  enter(els.cedula, '12'); await tick();
  assert.strictEqual(checkins.length, 0, 'menos de 3 dígitos no acredita');
  enter(els.cedula, '1012345678'); await tick();
  assert.deepStrictEqual(checkins, ['1012345678'], 'Enter con cédula sí acredita');
  assert.strictEqual(els.cedula.value, '', 'tras acreditar se limpia la caja');
  enter(els.cedula, 'AB123456'); await tick();                        // pasaporte: letras y dígitos sin espacios
  assert.strictEqual(checkins[1], 'AB123456');

  d.clearFilters(); assert.strictEqual(rows().length, 4);

  // --- lista local por huella (sin cédula en claro)
  fresh(false); checkins.length = 0;
  window.GoldenContingency = { instance: {
    ready: Promise.resolve(), supported: true, active: () => true, rosterUsable: async () => true,
    localPeople: async () => [{ n: 'Carla Soto', c: ['VIP'], s: 'No registrado', h: 'H:98765432' }, { n: 'Otro Nombre', c: [], s: 'No registrado', h: 'H:111' }],
    hashFor: async (c) => 'H:' + c, noteAuthGood() {}, noteScanExhausted() {},
  } };
  const dl = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', unified: true, fastCheckin: true, searchIds: { cedula: 'cedula', nombre: 'searchNombre', entidad: 'searchEntidad' } });
  await dl.reload(); await tick();
  assert.strictEqual(rows().length, 2); assert.strictEqual(els.hint.textContent, 'Sin red: se busca por nombre y por cédula completa. Ves lo que registra este equipo; lo de los demás llega al reconectar.');
  type(els.cedula, 'carla'); assert.strictEqual(rows().length, 1); assert.deepStrictEqual(reasonOf(rows()[0]), ['Nombre']);
  type(els.cedula, '98765432'); await dl.hashesSettled(); advance(0);
  assert.strictEqual(rows().length, 1, 'la cédula completa coincide por huella'); assert.deepStrictEqual(reasonOf(rows()[0]), ['Cédula exacta']);
  type(els.cedula, '987'); assert.strictEqual(rows().length, 0, 'sin cédula en claro no hay prefijo en la lista local');
  delete window.GoldenContingency;

  // --- unified=false: comportamiento de siempre (tres cajas)
  fresh(true); checkins.length = 0;
  const o = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', fastCheckin: true, searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' } });
  await o.reload();
  assert.strictEqual(els.cedula.focused, undefined);
  type(els.cedula, '10123'); assert.deepStrictEqual(ids().sort(), ['10123', '1012345678', '1012399'].sort());   // subcadena, sin orden por exactitud
  assert.ok(rows().every((tr) => reasonOf(tr).length === 0), 'sin modo unificado no hay motivos');
  assert.strictEqual(els.hint.textContent, '');
  type(els.cedula, ''); type(els.nombre, 'ana'); assert.deepStrictEqual(ids(), ['1012345678']);
  type(els.nombre, ''); type(els.entidad, 'acme'); assert.strictEqual(rows().length, 2);
  enter(els.cedula, 'marta'); await tick();
  assert.deepStrictEqual(checkins, ['marta'], 'sin modo unificado Enter siempre acredita');
  assert.strictEqual(els.cedula.value, '');
  console.log('directory.js: buscador unico OK');
})().catch((e) => { console.error(e); process.exit(1); });
