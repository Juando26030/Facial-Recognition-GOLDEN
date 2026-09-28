// Prueba del buscador del Directorio (static/js/directory.js) con un DOM y un servidor falsos. Correr: node tests/js/directory_search_check.js
// Comprueba: espera de 250 ms tras la última tecla, tope de 200 filas dibujadas con «Mostrar más», filas reutilizadas entre búsquedas,
// búsqueda sin tildes / con error de tipeo, y que una tecla no cueste casi nada con 10.000 personas.
const fs = require('fs');
const assert = require('assert');

let created = 0;
class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this._html = ''; this.offsetParent = {}; this.value = ''; if (tag === 'tr') created++; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c) { c.parentNode = this; this.children.unshift(c); return c; }
  addEventListener(k, f) { this.listeners[k] = f; }
  set innerHTML(v) { this._html = v; this.children = []; }
  get innerHTML() { return this._html; }
  closest() { return table; }
  setAttribute() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  replaceChildren(...c) { c.forEach(x => { x.parentNode = this; }); this.children = c; this._html = ''; }
}
const container = new El('div');
const table = container.appendChild(new El('table'));
const els = { tbody: new El('tbody'), cedula: new El('input'), nombre: new El('input'), entidad: new El('input') };
global.window = { EVENT_ID: 1, STAFF_ROLE: 'coordinador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [] };
global.document = { getElementById: id => els[id] || null, createElement: t => new El(t), visibilityState: 'visible', body: new El('body'), addEventListener: (k, f) => { docListeners[k] = f; } };
const docListeners = {};
global.setInterval = () => 1;
// Reloj falso para la espera de la búsqueda.
let now = 0, timers = [];
global.setTimeout = (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; };
global.clearTimeout = t => { timers = timers.filter(x => x !== t); };
const advance = ms => { now += ms; const due = timers.filter(t => t.at <= now); timers = timers.filter(t => t.at > now); due.forEach(t => t.f()); };

const N = 10000;
const users = Array.from({ length: N }, (_, i) => ({ id: String(1000000000 + i), first_name: i === 4321 ? 'María José' : 'Persona' + i, last_name: 'Gómez', entity: i % 2 ? 'Compañía Ñañez' : 'Otra', status: 'No registrado' }));
global.fetch = async url => {
  const u = new URL(url, 'http://x');
  const json = (body, headers = {}) => ({ ok: true, status: 200, headers: { get: k => headers[k] ?? null }, json: async () => JSON.parse(JSON.stringify(body)) });
  if (u.pathname === '/api/users/changes') return json({ cursor: '1:1', total: users.length, users: [] });
  const limit = +u.searchParams.get('limit'), offset = +u.searchParams.get('offset');
  return json(users.slice(offset, offset + limit), { 'X-Total-Count': String(users.length) });
};

eval(fs.readFileSync('static/js/directory.js', 'utf8'));
const body = () => els.tbody.children;
const dataRows = () => body().filter(tr => tr.className !== 'directory-more');
const more = () => body().find(tr => tr.className === 'directory-more');
const type = (el, text) => { el.value = text; el.listeners.input(); };

(async () => {
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' } });
  await d.reload();

  // Tope: 200 filas + la fila «Mostrando 200 de 10000» con su botón.
  assert.strictEqual(dataRows().length, 200);
  assert.ok(more().children[0].innerText.includes('Mostrando 200 de 10000'));
  more().children[0].children[0].listeners.click();
  assert.strictEqual(dataRows().length, 400);

  // Espera: nada se filtra mientras se escribe; sí 250 ms después de la ÚLTIMA tecla.
  const before = body();
  type(els.nombre, 'm'); advance(100);
  type(els.nombre, 'ma'); advance(100);
  type(els.nombre, 'mari'); advance(200);
  assert.strictEqual(body(), before, 'no debe redibujar antes de 250 ms sin teclear');
  advance(50);
  assert.strictEqual(dataRows().length, 1);
  assert.strictEqual(dataRows()[0].children[2].innerText, 'María José');       // sin tilde encuentra con tilde

  type(els.nombre, 'maira jose'); advance(250);                                  // error de tipeo (transposición)
  assert.strictEqual(dataRows().length, 1);

  // Filas reutilizadas: volver a una búsqueda ya vista no construye filas nuevas.
  type(els.nombre, ''); type(els.entidad, 'compania'); advance(250);
  assert.strictEqual(dataRows().length, 200);
  assert.ok(more().children[0].innerText.includes('de 5000'));
  const createdBefore = created;
  type(els.entidad, 'otra'); advance(250);
  type(els.entidad, 'compania'); advance(250);
  assert.ok(created - createdBefore <= 402, `se construyeron ${created - createdBefore} filas: deberían reutilizarse`);   // «otra» (200 nuevas) + 2 filas de «Mostrar más»

  // Costo por tecla con 10.000 personas: escribir no filtra nada (solo programa la espera), y filtrar+dibujar es barato.
  let t = process.hrtime.bigint();
  for (let i = 0; i < 100; i++) type(els.cedula, '10000' + i);
  const perKeyMs = Number(process.hrtime.bigint() - t) / 1e6 / 100;
  t = process.hrtime.bigint();
  advance(250);
  const filterMs = Number(process.hrtime.bigint() - t) / 1e6;
  type(els.cedula, ''); type(els.entidad, ''); type(els.nombre, 'persona'); t = process.hrtime.bigint(); advance(250);
  const worstMs = Number(process.hrtime.bigint() - t) / 1e6;
  assert.ok(perKeyMs < 1, `una tecla tardó ${perKeyMs} ms`);
  assert.ok(worstMs < 150, `filtrar 10.000 por nombre tardó ${worstMs} ms`);
  console.log(`directory.js: buscador OK (tecla ${perKeyMs.toFixed(3)} ms; filtrar por cédula ${filterMs.toFixed(1)} ms; por nombre sobre ${N} ${worstMs.toFixed(1)} ms)`);
})().catch(e => { console.error(e); process.exit(1); });
