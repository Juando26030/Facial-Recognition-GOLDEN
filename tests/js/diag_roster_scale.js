// DIAGNÓSTICO de escala del cliente (no es prueba de CI). Mide con N personas la lista local sin red: lectura, pintado (tope RENDER_LIMIT), búsqueda y contadores. Correr: node tests/js/diag_roster_scale.js
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
const ms = (t) => (performance.now() - t).toFixed(0) + ' ms';
const counters = () => table.parentNode.children.filter((c) => /counter/.test(c.className)).map((c) => c.innerText).join(' | ');
(async () => {
  for (const N of (process.env.SCALE_SIZES || '8000,16000').split(',').map(Number)) {
    console.log(`\n== N=${N} (tiempos de JavaScript en Node con DOM falso: NO incluyen el pintado real del navegador)`);
    ROSTER = []; for (let i = 0; i < N; i++) ROSTER.push({ h: String(i).padStart(16, '0'), n: `Nombre${i} Apellido${i % 997}`, c: i % 10 ? [] : ['VIP'], s: i % 3 ? 'No registrado' : 'Registrado' });
    const GC = C.create({ idb: fakeIndexedDB(), fetch: global.fetch, now: () => now, document: global.document, subtle: crypto.subtle, eventId: 1, uuid: () => 'u', setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });
    let t = performance.now(); await GC.start(); await flush(); await flush(); console.log('descargar y guardar la copia local (IndexedDB falsa):', ms(t));
    window.GoldenContingency = { instance: GC }; netDown = true;
    t = performance.now(); const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
    await d.reload(); await advance(10); console.log('leer la copia y pintar la tabla:', ms(t));
    const note = els.tbody.children.find((tr) => /directory-more/.test(tr.className));
    console.log('filas pintadas:', rows().length, '· pie:', note ? note.children[0].innerText.slice(0, 70) : '(sin pie)', '· contadores:', counters());
    for (const q of ['nombre123', 'apellido5', 'zzz']) { t = performance.now(); els.nombre.value = q; els.nombre.listeners.input(); await advance(300); console.log(`buscar «${q}»:`, ms(t), '→ filas pintadas', rows().length, '·', counters()); }
    els.nombre.value = ''; els.nombre.listeners.input(); await advance(300);
    t = performance.now(); els.cedula.value = '555'; els.cedula.listeners.input(); await advance(300); for (let i = 0; i < 20; i++) await flush(); console.log('buscar cédula «555» (huella exacta; la copia no trae cédula):', ms(t), '→ filas', rows().length);
  }
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
