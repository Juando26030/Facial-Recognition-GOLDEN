// Copia COMPLETA para trabajar sin red (static/js/contingency.js › people*). Correr: node tests/js/contingency_full_check.js
// Comprueba: las filas del directorio se guardan CIFRADAS por bloques (nada legible en IndexedDB), se leen completas, los cambios parciales solo tocan su bloque, acreditar/deshacer
// sin red se refleja en la copia, la cola sigue sin guardar la cédula, y la copia se borra con la lista local y no vale para otro evento ni vencida.
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');

const doc = { body: { children: [], appendChild() {}, classList: { toggle() {} } }, head: { appendChild() {} }, createElement: () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {}, addEventListener() {}, remove() {}, children: [], textContent: '', classList: { toggle() {}, add() {}, remove() {} } }), getElementById: () => null, addEventListener() {}, visibilityState: 'visible' };
const SALT = 'e'.repeat(32);
const hex = (b) => Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, '0')).join('');
const fp = async (c) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${c}`))).slice(0, 16);
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, json: async () => data });
const users = [], people = [];
let now = Date.now(), net = true;
const fetchFake = async (url) => {
  if (!net) throw new TypeError('Failed to fetch');
  const u = new URL(url, 'http://x');
  if (u.pathname === '/health' || u.pathname === '/api/ping-auth') return json(200, {});
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: new Date(now).toISOString(), max_age_s: 3600, event: { id: 7, status: 'en_proceso', auto_register: false }, salt: SALT, count: people.length, people });
  throw new Error('ruta inesperada ' + u.pathname);
};
const { settle } = require('./settle');
const raw = (idb, store) => [...idb.dbs.get('golden-contingency-7').stores.get(store).data.values()];

(async () => {
  global.setInterval = () => 1;
  for (let i = 0; i < 950; i++) { const id = String(52000000 + i); people.push({ h: await fp(id), n: 'Persona ' + i, c: [], s: 'No registrado' }); users.push({ id, first_name: 'Persona', last_name: String(i), entity: 'Entidad ' + (i % 7), phone: '300' + i, email: `p${i}@correo.test`, status: 'No registrado', categories: [], extra_fields: { opcional_1: 'x' + i }, __interno: 1 }); }
  const idb = fakeIndexedDB();
  const mk = () => C.create({ idb, fetch: fetchFake, now: () => now, document: doc, subtle: crypto.subtle, eventId: 7, uuid: (() => { let n = 0; return () => `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}`; })(), setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout });
  const c = mk(); await c.start(); await settle();
  assert.strictEqual(await c.refreshRoster(), 'ok');
  net = false;

  assert.strictEqual(await c.peopleSave(users), 950);
  const rawp = raw(idb, 'people');
  assert.strictEqual(rawp.length, 3, 'bloques de 400');
  const dump = Buffer.concat(rawp.map((r) => Buffer.from(r.enc.ct))).toString('latin1') + JSON.stringify(rawp.map((r) => ({ k: r.k, n: r.n })));
  assert.ok(!dump.includes('52000001') && !dump.includes('correo.test') && !dump.includes('Entidad'), 'nada legible en reposo');
  const back = await c.peopleLoad();
  assert.strictEqual(back.length, 950); assert.strictEqual(back[10].email, 'p10@correo.test'); assert.strictEqual(back[10].extra_fields.opcional_1, 'x10');
  assert.ok(!('__interno' in back[0]), 'las marcas internas de la pantalla no se guardan');

  // cambios parciales: una editada y una nueva
  await c.peoplePatch([{ ...users[5], entity: 'Nueva entidad' }, { id: '99', first_name: 'Nueva', last_name: 'Persona', status: 'No registrado' }]);
  const b2 = await c.peopleLoad();
  assert.strictEqual(b2.length, 951); assert.strictEqual(b2.find((u) => u.id === '52000005').entity, 'Nueva entidad'); assert.ok(b2.find((u) => u.id === '99'));
  assert.strictEqual((await c.peopleMeta()).n, 951);

  // editar sin red: mezcla campos y opcionales
  const row = await c.peopleApply('52000007', { phone: '111', extra_fields: { opcional_2: 'z' } });
  assert.strictEqual(row.phone, '111'); assert.deepStrictEqual(row.extra_fields, { opcional_1: 'x7', opcional_2: 'z' });
  assert.strictEqual(await c.peopleApply('no-existe', { phone: '1' }), null);

  // acreditar y deshacer sin red se reflejan en la copia; la cola no guarda la cédula
  const found = await c.scanLocal('52000003');
  assert.strictEqual(found.status, 'found');
  await c.enqueue(found, 'cedula', 'cid-1');
  assert.strictEqual((await c.peopleLoad()).find((u) => u.id === '52000003').status, 'Registrado');
  assert.ok(!JSON.stringify(await c.queueList()).includes('52000003'), 'la cola no guarda la cédula');
  assert.ok(await c.unqueue('cid-1'));
  assert.strictEqual((await c.peopleLoad()).find((u) => u.id === '52000003').status, 'No registrado');

  // otra instancia (recarga de la página): se lee del disco con la misma clave
  const c2 = mk(); await c2.start(); await settle();
  assert.strictEqual((await c2.peopleLoad()).length, 951);
  assert.strictEqual((await c2.peopleApply('52000900', { entity: 'E' })).entity, 'E');

  // vencida la lista local, la copia completa tampoco vale; al borrar la lista se borra
  now += 3600_001;
  assert.strictEqual(await c2.peopleLoad(), null, 'vencida');
  now -= 3600_001;
  await c2.wipeRoster();
  assert.strictEqual(raw(idb, 'people').length, 0); assert.strictEqual(await c2.peopleLoad(), null);
  console.log('contingency_full_check: OK');
})().catch((e) => { console.error(e); process.exit(1); });
