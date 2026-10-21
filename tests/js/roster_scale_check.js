// Prueba de ESCALA de la lista local (8.000 y 16.000 personas) con DOM, IndexedDB y red falsos. Correr: node tests/js/roster_scale_check.js
// Criterio (J, 2026-10-05): todas las personas cargadas localmente y buscables por nombre y por cédula exacta; contador «LISTA LOCAL: N de N» frente al total del servidor, con aviso si no coincide; todas las filas alcanzables paginando.
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
const realSetTimeout = global.setTimeout;
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
const names = () => rows().map((tr) => tr.children[2].innerText);
const pagerText = () => (els.tbody.children.find((tr) => /directory-more/.test(tr.className)) || { children: [{ innerText: '' }] }).children[0].innerText;
const noteText = () => (els.tbody.children.find((tr) => /directory-local-note/.test(tr.className)) || { children: [{ innerText: '' }] }).children[0].innerText;
const until = async (ready) => { for (let i = 0; i < 1000 && !ready(); i++) { await new Promise((r) => realSetTimeout(r, 5)); await advance(10); } };

(async () => {
  for (const N of [8000, 16000]) {
    // LISTA LOCAL completa: TODAS las N personas en la copia, buscables por nombre y por cédula exacta, paginadas sin recortar nada
    ROSTER = [];
    for (let i = 0; i < N; i++) ROSTER.push({ h: i === N - 1 ? await fp('1099999') : String(i).padStart(16, '0'), n: i === N - 1 ? 'Última Persona' : `Nombre${i} Apellido${i % 997}`, c: [], s: i % 3 ? 'No registrado' : 'Registrado' });
    window.DIRECTORY_PAGE_SIZE = 50;
    const GC = C.create({ idb: fakeIndexedDB(), fetch: global.fetch, now: () => now, document: global.document, subtle: crypto.subtle, eventId: 1, uuid: () => 'u', setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });
    netDown = false; await GC.start(); await flush(); await flush();                 // con red: baja la copia local
    window.GoldenContingency = { instance: GC }; netDown = true;
    els.nombre.value = ''; els.cedula.value = '';
    const t0 = Date.now();
    const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
    await d.reload(); await advance(10);
    assert.ok(/LISTA LOCAL: \d+ de \?/.test(noteText()), 'N de ?: ' + noteText());
    assert.ok(new RegExp(`LISTA LOCAL: ${N} de`).test(noteText()), `la copia tiene las ${N}: ${noteText()}`);
    const counters = table.parentNode.children.filter((c) => /counter/.test(c.className)).map((c) => c.innerText).join(' | ');
    assert.ok(new RegExp(`de ${N}\\b`).test(counters), `los contadores cubren a las ${N}: ${counters}`);
    assert.strictEqual(rows().length, 50, 'una página de 50'); assert.ok(pagerText().includes(`de ${N} · Página 1 de ${N / 50}`), pagerText());
    // la última persona está en la última página (se llega a TODAS las filas)
    const pager = () => els.tbody.children.find((tr) => /directory-more/.test(tr.className)).children[0].children;
    pager()[2].value = String(N / 50); pager()[3].listeners.click();
    assert.ok(names().includes('Última Persona'), 'la última persona se alcanza paginando');
    // búsqueda por nombre sobre todas (la última, escrita sin tilde) y por cédula EXACTA (huella) de esa misma persona
    els.nombre.value = 'ultima persona'; els.nombre.listeners.input(); await advance(300); assert.deepStrictEqual(names(), ['Última Persona']);
    els.nombre.value = ''; els.nombre.listeners.input(); await advance(300);
    els.cedula.value = '1099999'; els.cedula.listeners.input(); await advance(300); await until(() => names().length === 1);
    assert.deepStrictEqual(names(), ['Última Persona'], 'cédula exacta por huella entre ' + N);
    els.cedula.value = ''; els.cedula.listeners.input(); await advance(300);
    // el total del servidor se compara: si difiere, avisa
    now += 61_000; await GC.noteServerTotal(N + 7); await d.reload(); await advance(10);
    assert.ok(new RegExp(`LISTA LOCAL: ${N} de ${N + 7} — NO COINCIDE`).test(noteText()) && /faltan 7/.test(noteText()), noteText());
    now += 61_000; await GC.noteServerTotal(N); await d.reload(); await advance(10);
    assert.ok(new RegExp(`LISTA LOCAL: ${N} de ${N}[^0-9]`).test(noteText()) && !/NO COINCIDE/.test(noteText()), noteText());
    assert.ok(Date.now() - t0 < 20000, `tardó ${Date.now() - t0} ms`);
  }
  console.log('lista local con 8.000 y 16.000 personas: todas cargadas, paginadas, buscables por nombre y cédula exacta, contador N de N OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
