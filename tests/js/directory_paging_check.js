// Prueba de static/js/directory.js (carga por páginas + incremental) con un DOM y un servidor falsos. Correr: node tests/js/directory_paging_check.js
const fs = require('fs');
const assert = require('assert');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this._html = ''; this.offsetParent = {}; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c) { c.parentNode = this; this.children.unshift(c); return c; }
  addEventListener(k, f) { this.listeners[k] = f; }
  set innerHTML(v) { this._html = v; this.children = []; }
  get innerHTML() { return this._html; }
  closest() { return table; }
  setAttribute() {}
  querySelector() { return null; }
}
const container = new El('div');
const table = container.appendChild(new El('table'));
const tbody = new El('tbody');
const els = { tbody };
let intervalFn = null;
global.window = { EVENT_ID: 1, STAFF_ROLE: 'coordinador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [] };
global.document = { getElementById: id => els[id] || null, createElement: t => new El(t), visibilityState: 'visible', body: new El('body') };
global.setInterval = f => { intervalFn = f; return 1; };

// ---- servidor falso ----
let users = Array.from({ length: 2500 }, (_, i) => ({ id: String(100000 + i), first_name: 'P' + i, last_name: 'Q', status: 'No registrado' }));
let logId = 10, attId = 2500, changed = new Map();   // id -> logId en que cambió
const calls = [];
global.fetch = async url => {
  const u = new URL(url, 'http://x');
  calls.push(u.pathname + u.search);
  const json = (body, headers = {}) => ({ ok: true, status: 200, headers: { get: k => headers[k] ?? null }, json: async () => JSON.parse(JSON.stringify(body)) });
  if (u.pathname === '/api/users/changes') {
    const [since] = u.searchParams.get('cursor').split(':').map(Number);
    const rows = users.filter(x => (changed.get(x.id) || 0) > since);
    return json({ cursor: `${logId}:${attId}`, total: users.length, users: rows });
  }
  if (u.pathname === '/api/users') {
    const limit = +u.searchParams.get('limit'), offset = +u.searchParams.get('offset');
    return json(users.slice(offset, offset + limit), { 'X-Total-Count': String(users.length) });
  }
  throw new Error('ruta inesperada ' + url);
};

eval(fs.readFileSync('static/js/directory.js', 'utf8'));
const rows = () => tbody.children.length;
const settle = async () => { for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r)); };

(async () => {
  const dir = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: {} });
  await dir.reload();
  assert.strictEqual(rows(), 2500);
  assert.deepStrictEqual(calls.map(c => c.split('?')[0]), ['/api/users/changes', '/api/users', '/api/users', '/api/users']);

  // Otro kiosco registra a alguien: el sondeo trae SOLO esa persona.
  calls.length = 0;
  users[7] = { ...users[7], status: 'Registrado' }; logId++; changed.set(users[7].id, logId);
  intervalFn(); await settle();
  assert.strictEqual(calls.length, 1);
  assert.ok(calls[0].startsWith('/api/users/changes?cursor=10%3A2500'));
  assert.strictEqual(tbody.children.find(tr => tr.children[1].innerText === users[7].id).children.at(-1).innerText, 'Registrado');
  assert.strictEqual(rows(), 2500);

  // Nada cambió: una sola consulta pequeña, la tabla no se vuelve a dibujar.
  calls.length = 0;
  const before = tbody.children;
  intervalFn(); await settle();
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(tbody.children, before);

  // Una baja (el incremental no la ve): el total no cuadra y se recarga todo.
  calls.length = 0;
  users = users.slice(1);
  intervalFn(); await settle();
  assert.strictEqual(rows(), 2499);
  assert.ok(calls.length === 5 && calls[1].startsWith('/api/users/changes?cursor=9007'));
  console.log('directory.js: páginas + incremental OK');
})().catch(e => { console.error(e); process.exit(1); });
