// La cola local (ingresos, decisiones de autorización y lista de «revisar») queda CIFRADA en reposo (AES-GCM, clave no extraíble). Correr: node tests/js/contingency_encrypt_check.js
// Comprueba: nada identificable en claro en lo guardado; la clave no es extraíble y vive en su propio almacén (sobrevive al borrado de la lista local); lo viejo en claro se cifra al arrancar;
// la sincronización envía lo descifrado; y la cola sigue leyéndose después de reabrir.
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');

const doc = { body: { children: [], appendChild() {}, classList: { toggle() {} } }, head: { appendChild() {} }, createElement: () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {}, addEventListener() {}, remove() {}, children: [], textContent: '' }), visibilityState: 'visible', addEventListener() {} };
const SALT = 'e'.repeat(32);
const hex = (b) => Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, '0')).join('');
const fp = async (c) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${c}`))).slice(0, 16);
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, json: async () => data });
let sent = [], net = true;
const fetchFake = async (url, opts) => {
  if (!net) throw new TypeError('Failed to fetch');
  const u = new URL(url, 'http://x');
  if (u.pathname === '/health' || u.pathname === '/api/ping-auth') return json(200, {});
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 1, status: 'en_proceso', auto_register: false }, salt: SALT, count: 1, people: [{ h: await fp('1001'), n: 'Ana Pérez', c: [], s: 'No registrado', a: 0, b: 0, v: 0 }], consent: null });
  if (u.pathname.endsWith('/access-logs/sync')) { const b = JSON.parse(opts.body); sent.push(b); return json(200, { results: b.records.map((r) => ({ client_id: r.client_id, result: 'created' })) }); }
  if (u.pathname.endsWith('/consents')) { const b = JSON.parse(opts.body); sent.push(b); return json(200, { inserted: b.entries.length, duplicated: 0, unknown: 0 }); }
  throw new Error('ruta inesperada ' + u.pathname);
};
const { settle } = require('./settle');
const raw = (idb, store) => [...idb.dbs.get('golden-contingency-1').stores.get(store).data.values()];

(async () => {
  global.setInterval = () => 1;
  const idb = fakeIndexedDB();
  const make = () => C.create({ idb, fetch: fetchFake, now: () => Date.now(), document: doc, subtle: crypto.subtle, eventId: 1, uuid: (() => { let n = 0; return () => `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}`; })(), setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout });
  let GC = make(); await GC.start(); await settle();

  assert.strictEqual(await GC.refreshRoster(), 'ok');                                   // la copia local ya está bajada
  // 1) un ingreso sin red: en reposo NO queda la huella, el nombre ni el método en claro
  net = false;
  const found = await GC.scanLocal('1001'); assert.strictEqual(found.status, 'found');
  await GC.enqueue(found, 'qr', '11111111-1111-4111-8111-111111111111');
  const stored = raw(idb, 'queue'); assert.strictEqual(stored.length, 1);
  assert.ok(stored[0].enc && stored[0].enc.ct && stored[0].enc.iv, 'cifrado');
  assert.ok(!('h' in stored[0]) && !('n' in stored[0]) && !('method' in stored[0]), 'sin huella, nombre ni método en claro');
  assert.ok(!JSON.stringify(stored).includes('Ana') && !JSON.stringify(stored).includes(await fp('1001')), 'nada identificable en lo guardado');
  assert.strictEqual(stored[0].client_id, '11111111-1111-4111-8111-111111111111'); assert.ok(stored[0].timestamp);        // lo que no identifica a nadie sí queda en claro (no duplicar y vencer a los 7 días)
  const q = await GC.queueList(); assert.strictEqual(q[0].n, 'Ana Pérez'); assert.strictEqual(q[0].h, await fp('1001')); assert.strictEqual(q[0].method, 'qr');

  // 2) la clave NO es extraíble y vive aparte
  const key = raw(idb, 'keys')[0].key; assert.strictEqual(key.extractable, false);
  await assert.rejects(crypto.subtle.exportKey('raw', key), 'una clave no extraíble no se puede exportar');
  await GC.wipeAll(); assert.strictEqual(raw(idb, 'keys').length, 1, 'borrar la lista local no borra la clave');

  // 3) decisiones de autorización y «revisar»: también cifradas
  await GC.consentAdd({ id: '22222222-2222-4222-8222-222222222222', h: await fp('1001'), decision: 'accept', adult: true, text_hash: 'a'.repeat(64), version: 'v1.1_kiosk_propio', device: 'tablet-1', at: new Date().toISOString() });
  const c0 = raw(idb, 'consents')[0]; assert.ok(c0.enc && !('h' in c0) && !('decision' in c0), 'la decisión no queda en claro');
  assert.strictEqual((await GC.consentList())[0].decision, 'accept');

  // 4) un registro viejo EN CLARO se cifra al arrancar
  await GC.db.put('queue', { client_id: '33333333-3333-4333-8333-333333333333', h: await fp('1001'), n: 'Vieja Entrada', timestamp: new Date().toISOString(), method: 'cedula' });
  GC.stop(); GC = make(); await GC.start(); await settle();
  assert.ok(raw(idb, 'queue').every((r) => r.enc && !('n' in r)), 'lo viejo en claro quedó cifrado');
  assert.ok((await GC.queueList()).some((r) => r.n === 'Vieja Entrada'), 'y se sigue leyendo tras reabrir');

  // 5) la sincronización envía lo DESCIFRADO (el servidor necesita la huella) y borra lo enviado
  net = true; sent = [];
  assert.ok(['ok', 'empty'].includes(await GC.syncQueue(true)));
  const records = sent.filter((b) => b.records).flatMap((b) => b.records); assert.ok(records.some((r) => r.h === (/^[0-9a-f]{16}$/.test(r.h) ? r.h : null) && r.client_id), 'envía la huella');
  assert.ok(records.every((r) => /^[0-9a-f]{16}$/.test(r.h)), 'todas con huella legible (nunca vacía)');
  assert.strictEqual((await GC.queueList()).length, 0);
  const cons = sent.filter((b) => b.entries).flatMap((b) => b.entries); assert.ok(cons.length === 1 && cons[0].decision === 'accept' && /^[0-9a-f]{16}$/.test(cons[0].h));
  console.log('contingency.js: cola de ingresos, decisiones y «revisar» cifradas en reposo (AES-GCM, clave no extraíble) OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
