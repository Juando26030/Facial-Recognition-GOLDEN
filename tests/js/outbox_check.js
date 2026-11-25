// Prueba de la BANDEJA DE SALIDA (static/js/outbox.js, B8 R1) con IndexedDB falso y WebCrypto REAL de Node. Correr: node tests/js/outbox_check.js
// Comprueba: cifrado en reposo (nada en claro y clave no extraíble), borrado de los campos tras sincronizar, resultados por ítem, reenvío sin duplicar, caducidad de 7 días con avisos desde el día 3
// y SIN borrado silencioso, lotes de ≤ 50, caída de red/sesión sin perder nada.
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const O = require('../../static/js/outbox.js');

const DAY = 86400000;
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
const fields = (id, n = 'Nora') => ({ id, first_name: n, last_name: 'Sin Red', phone: '3001112222', email: `${n}@x.co`, entity: 'ACME' });
const okAll = async (body) => json(200, { results: body.ops.map((o) => ({ op_id: o.op_id, result: 'ok' })) });

(async () => {
  const idb = fakeIndexedDB();
  let now = 1_800_000_000_000, calls = [], reply = okAll, n = 0;
  const mk = () => O.create({ idb, subtle: crypto.subtle, random: (k) => crypto.getRandomValues(new Uint8Array(k)), now: () => now, eventId: 7, uuid: () => `op-${++n}`,
    fetch: async (url, init) => { const body = JSON.parse(init.body); calls.push({ url, body }); return reply(body); } });
  let box = await mk().init();
  assert.strictEqual(box.supported, true);
  const records = () => [...idb.dbs.get('golden-outbox-7').stores.get('ops').data.values()];

  // 1) CIFRADO EN REPOSO: ni la cédula, ni el nombre, ni el teléfono, ni el correo aparecen en lo guardado; la clave no se puede extraer
  await box.enqueue(fields('1055999888'), 'Nora Sin Red');
  const stored = records().map((r) => JSON.stringify({ ...r, blob: undefined }) + Buffer.from(r.blob.ct).toString('latin1') + Buffer.from(r.blob.iv).toString('latin1')).join('|');
  for (const secret of ['1055999888', 'Nora', 'Sin Red', '3001112222', '@x.co', 'ACME']) assert.ok(!stored.includes(secret), `«${secret}» no debe estar en claro`);
  assert.strictEqual(box.key.extractable, false, 'clave NO extraíble'); await assert.rejects(crypto.subtle.exportKey('raw', box.key));
  const listed = await box.list(); assert.strictEqual(listed.length, 1); assert.strictEqual(listed[0].label, 'Nora Sin Red'); assert.ok(!JSON.stringify(listed).includes('1055999888'), 'la lista de la pantalla nunca lleva la cédula');
  assert.strictEqual(listed[0].status, 'pendiente'); assert.ok(Math.abs(listed[0].days_left - 7) < 0.01, 'caduca a los 7 días');
  box.stop(); box = await mk().init(); assert.strictEqual((await box.list())[0].label, 'Nora Sin Red', 'tras recargar la página: misma clave, se descifra igual');

  // 2) SINCRONIZAR: ok => se BORRAN los campos (queda solo el nombre para mostrar 24 h) y el reenvío no duplica
  let s = await box.sync(); assert.strictEqual(s.ok, 1); assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url, '/api/events/7/outbox/sync'); assert.strictEqual(calls[0].body.ops[0].fields.id, '1055999888', 'al servidor sí viaja en claro (TLS)'); assert.strictEqual(calls[0].body.ops[0].type, 'create_person');
  const rec = records()[0]; assert.strictEqual(rec.status, 'ok');
  const dec = async (r) => JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: r.blob.iv }, box.key, r.blob.ct)));
  assert.deepStrictEqual(await dec(rec), { fields: null, label: 'Nora Sin Red' }, 'tras sincronizar no queda ningún dato personal salvo el nombre');
  calls = []; s = await box.sync(); assert.strictEqual(calls.length, 0, 'lo ya enviado no se reenvía');
  now += DAY + 1; await box.purge(); assert.strictEqual((await box.list()).length, 0, 'lo entregado se limpia solo a las 24 h');

  // 3) RESULTADOS POR ÍTEM: existente (revisión), duplicado, error con motivo; los que necesitan una persona NO se borran
  const ids = []; for (const id of ['A1', 'A2', 'A3', 'A4']) ids.push((await box.enqueue(fields(id), `Persona ${id}`)).op_id);
  const four = [(o) => ({ op_id: o.op_id, result: 'ok' }), (o) => ({ op_id: o.op_id, result: 'existente', existing_name: 'Luis Original' }), (o) => ({ op_id: o.op_id, result: 'duplicado', existing_name: 'Eva' }),
    (o) => ({ op_id: o.op_id, result: 'error', detail: 'Faltan campos obligatorios: phone' })];
  reply = async (body) => json(200, { results: body.ops.map((o, i) => four[i](o)) });
  s = await box.sync(); assert.deepStrictEqual([s.ok, s.revision, s.duplicado, s.error], [1, 1, 1, 1]);
  let st = await box.stats(); assert.strictEqual(st.needs_attention, 3); assert.strictEqual(st.unsent, 3);
  const byLabel = Object.fromEntries((await box.list()).map((i) => [i.label, i]));
  assert.strictEqual(byLabel['Persona A2'].status, 'revision'); assert.strictEqual(byLabel['Persona A2'].detail, 'Luis Original'); assert.strictEqual(byLabel['Persona A4'].detail, 'Faltan campos obligatorios: phone');
  await box.retry(ids[3]); assert.strictEqual((await box.list()).find((i) => i.op_id === ids[3]).status, 'pendiente');
  await box.retry(ids[1]); assert.strictEqual((await box.list()).find((i) => i.op_id === ids[1]).status, 'revision', 'solo se reintenta lo que dio error');

  // 4) CAÍDA DE RED / SESIÓN a media operación: nada se pierde ni se marca; se reintenta
  reply = async () => { throw new TypeError('Failed to fetch'); }; s = await box.sync(); assert.strictEqual(s.stopped, 'red'); assert.strictEqual((await box.list()).find((i) => i.op_id === ids[3]).status, 'pendiente');
  reply = async () => json(401, {}); s = await box.sync(); assert.strictEqual(s.stopped, 'sesion');
  reply = async () => json(500, {}); s = await box.sync(); assert.strictEqual(s.stopped, 'servidor');
  reply = async (body) => json(200, { results: body.ops.map((o) => ({ op_id: o.op_id, result: 'replayed' })) }); s = await box.sync(); assert.strictEqual(s.ok, 1, 'un reenvío ya procesado (replayed) cuenta como entregado');
  assert.strictEqual((await box.stats()).pending, 0);

  // 5) CADUCIDAD DE 7 DÍAS: avisos desde el día 3, rojo el 6; a los 7 se ELIMINA solo (texto C''' de la auditora) con un aviso persistente: nunca en silencio
  for (const i of await box.list()) if (i.base_status !== 'ok') await box.discard(i.op_id);                      // limpiar (acciones explícitas)
  reply = okAll;
  const oldId = (await box.enqueue(fields('B1'), 'Beatriz Antigua')).op_id;
  assert.strictEqual((await box.stats()).level, 'ok');
  now += 2 * DAY; assert.strictEqual((await box.stats()).level, 'ok');
  now += DAY; st = await box.stats(); assert.strictEqual(st.level, 'warn'); assert.ok(/1 cambio sin enviar \(la más antigua, hace 3 días; caduca en 4 días\)/.test(st.banner), st.banner);
  now += 3 * DAY; st = await box.stats(); assert.strictEqual(st.level, 'urgent'); assert.ok(/hace 6 días; caduca en 1 día\)/.test(st.banner), st.banner);
  now += 2 * DAY; calls = []; st = await box.stats();
  assert.ok(!(await box.list()).some((i) => i.op_id === oldId), 'a los 7 días se eliminó del dispositivo'); assert.strictEqual(calls.length, 0, 'y no se envió');
  assert.strictEqual(st.pruned, 1); assert.strictEqual(st.level, 'expired'); assert.ok(/se eliminaron de este dispositivo/.test(st.banner), 'NO fue en silencio: ' + st.banner);
  assert.strictEqual((await box.stats()).pruned, 1, 'el aviso persiste hasta que la persona lo ve'); await box.dismissPruned(); assert.strictEqual((await box.stats()).pruned, 0);
  const again = (await box.enqueue(fields('B2'), 'Otra')).op_id; now += 8 * DAY; await box.init();
  assert.ok(!(await box.list()).some((i) => i.op_id === again) && (await box.stats()).pruned === 1, 'init también aplica el plazo y avisa'); await box.dismissPruned();

  // 6) LOTES de ≤ 50
  calls = []; now += DAY; for (let i = 0; i < 120; i++) await box.enqueue(fields(`C${i}`), `Persona C${i}`);
  s = await box.sync(); assert.deepStrictEqual(calls.map((c) => c.body.ops.length), [50, 50, 20]); assert.strictEqual(s.ok, 120);

  // 7) SIN soporte (sin IndexedDB o WebCrypto): no rompe y lo dice
  const bad = await O.create({ idb: undefined, subtle: undefined, eventId: 7, fetch: async () => json(200, {}) }).init();
  assert.strictEqual(bad.supported, false); await assert.rejects(bad.enqueue({}, 'x'), /no puede guardar/);
  console.log('outbox.js: cifrado en reposo, borrado tras sincronizar, caducidad de 7 días con eliminación automática y aviso, lotes y resultados OK');
})().catch((e) => { console.error(e); process.exit(1); });
