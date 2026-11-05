// Formulario de persona SIN RED (Fase 1A, pieza 5): la definición VERSIONADA vive en la copia local (contingency.js, `meta`) y la bandeja de salida (outbox.js) manda esa versión con cada alta y cada
// edición. Correr: node tests/js/person_form_offline_check.js  (IndexedDB falso + WebCrypto real de Node; sin jsdom)
// Comprueba: la definición se guarda y se lee sin red; sobrevive a los borrados de la lista local (cerrar sesión, vencer, finalizar); el refresco la actualiza o la borra si el servidor la apagó;
// SIN la opción `personForm` no se hace ninguna petición nueva (el flujo de siempre); un alta y una edición hechas sin red llevan `form_version`/`form_sig`, quedan cifradas, se envían al volver la red
// (con los avisos que devuelva el servidor) y reenviar nunca duplica; una edición vieja sigue saliendo con SU versión.
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');
const O = require('../../static/js/outbox.js');
const PF = require('../../static/js/person-form.js');

const doc = { body: { children: [], appendChild() {}, classList: { toggle() {} } }, head: { appendChild() {} }, createElement: () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {}, addEventListener() {}, remove() {}, classList: { add() {}, remove() {} } }), getElementById: () => null, addEventListener() {} };
const SALT = 'f'.repeat(32);
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, json: async () => data });
const defV = (v, extra) => ({ enabled: true, form_version: v, form_sig: `sig${v}`, sheets: [{ id: 'datos', title: 'Datos', open: true }], rows: [{ sheet: 'datos', items: ['id', 'first_name'] }], fields: { first_name: { required: true, text_case: 'upper' } }, ...(extra || {}) });
let net = true, pfBody = { env_enabled: true, enabled: true, definition: defV(2) }, calls = [], syncReply = null;
const fetchFake = async (url, opts) => {
  if (!net) throw new TypeError('Failed to fetch');
  const u = new URL(url, 'http://x');
  calls.push(u.pathname);
  if (u.pathname === '/health' || u.pathname === '/api/ping-auth') return json(200, {});
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 1, status: 'en_proceso', auto_register: false }, salt: SALT, count: 0, people: [] });
  if (u.pathname.endsWith('/person-form')) return json(200, pfBody);
  if (u.pathname.endsWith('/outbox/sync')) { const b = JSON.parse(opts.body); return syncReply ? syncReply(b) : json(200, { results: b.ops.map((o) => ({ op_id: o.op_id, result: 'ok' })) }); }
  throw new Error('ruta inesperada ' + u.pathname);
};
const { settle } = require('./settle');

(async () => {
  global.setInterval = () => 1;
  const idb = fakeIndexedDB();
  const make = (personForm) => C.create({ idb, fetch: fetchFake, now: () => Date.now(), document: doc, subtle: crypto.subtle, eventId: 1, personForm, uuid: (() => { let n = 0; return () => `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}`; })() });

  // 1) SIN la opción: el refresco de siempre, ninguna petición al formulario de persona
  let GC = make(false); await GC.start(); await settle();
  assert.strictEqual(await GC.refreshRoster(), 'ok'); assert.ok(!calls.some((p) => p.endsWith('/person-form')), 'sin la opción no se pide el formulario de persona');
  assert.strictEqual(await GC.personForm(), null);
  GC.stop();

  // 2) CON la opción: el refresco guarda la definición (versionada) en la copia local, y se lee sin red
  GC = make(true); await GC.start(); await settle();
  assert.strictEqual(await GC.refreshRoster(), 'ok');
  assert.ok(calls.some((p) => p.endsWith('/person-form')), 'con la opción, el refresco la pide');
  let stored = await GC.personForm(); assert.strictEqual(stored.form_version, 2); assert.strictEqual(stored.fields.first_name.text_case, 'upper');
  net = false;
  assert.strictEqual((await GC.personForm()).form_version, 2, 'sin red se lee igual');
  assert.strictEqual(await GC.refreshRoster(), 'error'); assert.strictEqual((await GC.personForm()).form_version, 2, 'un refresco fallido no pierde la copia');
  net = true;

  // 3) sobrevive a los borrados de la lista local (cerrar sesión, vencer, finalizar el evento): no es un dato de nadie
  await GC.wipeRoster(); assert.strictEqual((await GC.personForm()).form_version, 2, 'wipeRoster la conserva');
  await GC.wipeAll(); assert.strictEqual((await GC.personForm()).form_version, 2, 'wipeAll la conserva');
  assert.strictEqual(await GC.rosterMeta(), undefined, 'la lista sí se borró');

  // 4) el servidor publica una versión nueva → se actualiza; lo apaga → se borra (la pantalla vuelve a la de siempre)
  pfBody = { env_enabled: true, enabled: true, definition: defV(3) }; await GC.refreshPersonForm(); assert.strictEqual((await GC.personForm()).form_version, 3);
  assert.strictEqual((await PF.sync(GC, defV(1))).form_version, 3, 'página en caché con la versión 1: manda la copia del dispositivo (3)');
  assert.strictEqual((await PF.sync(GC, defV(4))).form_version, 4); assert.strictEqual((await GC.personForm()).form_version, 4, 'la de la página era más nueva: se guardó');
  pfBody = { env_enabled: true, enabled: false, definition: defV(5) }; assert.strictEqual(await GC.refreshPersonForm(), null); assert.strictEqual(await GC.personForm(), null, 'apagado por el servidor: se borra la copia');
  pfBody = { env_enabled: false, enabled: false, definition: null }; await GC.savePersonForm(defV(6)); assert.strictEqual(await GC.refreshPersonForm(), null); assert.strictEqual(await GC.personForm(), null, 'entorno apagado: también');
  GC.stop();

  // 5) la bandeja: alta y edición sin red llevan la versión; cifradas; se envían al volver la red; reenviar no duplica
  const DAY = 86400000; let now = 1_800_000_000_000, n = 0;
  const box = await O.create({ idb, subtle: crypto.subtle, random: (k) => crypto.getRandomValues(new Uint8Array(k)), now: () => now, eventId: 9, uuid: () => `op-${++n}`, fetch: fetchFake }).init();
  const pf = defV(4); const alta = { id: '7001', first_name: 'nora', phone: '3001112222' }; PF.applyCase(alta, pf);
  assert.strictEqual(alta.first_name, 'NORA', 'el texto se normaliza también al encolar');
  await box.enqueue(alta, 'NORA', { form_version: pf.form_version, form_sig: pf.form_sig });
  await box.enqueue({ id: '7002', phone: '3009998888' }, 'Edición: Beto', { type: 'edit_person', form_version: 3, form_sig: 'sig3' });      // edición hecha con una copia VIEJA (3)
  await box.enqueue({ id: '7003', first_name: 'Sin versión' }, 'Sin versión');                                                                  // alta de siempre: sin formulario de persona
  const recs = [...idb.dbs.get('golden-outbox-9').stores.get('ops').data.values()];
  assert.deepStrictEqual(recs.map((r) => [r.type, r.form_version]), [['create_person', 4], ['edit_person', 3], ['create_person', undefined]]);
  const rest = recs.map((r) => JSON.stringify({ ...r, blob: undefined }) + Buffer.from(r.blob.ct).toString('latin1')).join('|');
  for (const secret of ['7001', '7002', 'NORA', '3009998888']) assert.ok(!rest.includes(secret), `«${secret}» no debe estar en claro`);
  assert.ok(rest.includes('"form_version":4'), 'la versión no es un dato personal: va a la vista');

  let bodies = [];
  syncReply = (b) => { bodies.push(b); return json(200, { results: b.ops.map((o) => ({ op_id: o.op_id, result: 'ok', ...(o.type === 'edit_person' ? { warnings: ['Faltan campos que ahora son obligatorios: Talla'] } : {}) })), form_version: 4 }); };
  net = false; assert.strictEqual((await box.sync()).stopped, 'red', 'sin red no sale nada y no se pierde nada'); assert.strictEqual(await box.countUnsent(), 3);
  net = true;
  const s = await box.sync();
  assert.deepStrictEqual(bodies[0].ops.map((o) => [o.type, o.form_version, o.form_sig]), [['create_person', 4, 'sig4'], ['edit_person', 3, 'sig3'], ['create_person', undefined, undefined]], 'cada operación sale con la versión con que se hizo');
  assert.deepStrictEqual(bodies[0].ops[1].fields, { id: '7002', phone: '3009998888' }, 'al servidor sí viaja en claro (TLS)');
  assert.strictEqual(s.ok, 3); assert.deepStrictEqual(s.warnings, ['Faltan campos que ahora son obligatorios: Talla'], 'los avisos del servidor llegan a la pantalla');
  assert.strictEqual(await box.countUnsent(), 0); bodies = []; await box.sync(); assert.strictEqual(bodies.length, 0, 'lo ya enviado no se reenvía');
  now += DAY + 1; await box.purge(); assert.strictEqual((await box.list()).length, 0);
  console.log('person_form_offline_check: OK');
})().catch((e) => { console.error(e); process.exit(1); });
