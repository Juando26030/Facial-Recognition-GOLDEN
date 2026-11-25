// Registro completo sin conexión (docs/28): peticiones guardadas de la bandeja (outbox.js › enqueueHttp) y reglas puras de Áreas e Inventario sin red (offline-data.js).
// Correr: node tests/js/offline_data_check.js
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const O = require('../../static/js/outbox.js');
const D = require('../../static/js/offline-data.js');

(async () => {
  // ---------- bandeja: peticiones guardadas, en orden, cifradas, con sus reglas de reenvío
  let now = 1_700_000_000_000, n = 0, net = true; const calls = [];
  const answers = [];
  const fetchFake = async (url, init) => {
    if (!net) throw new TypeError('Failed to fetch');
    calls.push({ url, method: init.method, body: init.body, op: init.headers && init.headers['X-Op-Id'], ct: init.headers && init.headers['Content-Type'] });
    if (url.endsWith('/outbox/sync')) { const b = JSON.parse(init.body); return { ok: true, status: 200, json: async () => ({ results: b.ops.map((o) => ({ op_id: o.op_id, result: 'ok' })) }) }; }
    const a = answers.shift() || { status: 200, body: {} };
    return { ok: a.status >= 200 && a.status < 300, status: a.status, json: async () => a.body };
  };
  const idb = fakeIndexedDB();
  const box = O.create({ idb, subtle: crypto.subtle, random: (k) => crypto.getRandomValues(new Uint8Array(k)), now: () => now++, fetch: fetchFake, eventId: 7, uuid: () => `op-${++n}` });
  await box.init(); assert.ok(box.supported);
  await box.enqueue({ id: '55', first_name: 'Nueva' }, 'Nueva Persona');                                                             // alta (lote de siempre)
  await box.enqueueHttp('/api/users/55?event_id=7', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ birth_date: '1990-01-02' }) }, 'Datos de: Nueva');
  await box.enqueueHttp('/api/users/55/cedula?event_id=7', { method: 'PUT', body: JSON.stringify({ new_id: '56' }) }, 'Cambio de cédula');
  await box.enqueueHttp('/api/events/7/areas/3/movement', { method: 'POST', body: JSON.stringify({ cedula: '56', direction: 'in' }), expect: ['OK'] }, 'Entrada');
  await box.enqueueHttp('/api/events/7/areas/3/movement', { method: 'POST', body: JSON.stringify({ cedula: '57', direction: 'in' }), expect: ['OK'] }, 'Entrada 2');
  const raw = [...idb.dbs.get('golden-outbox-7').stores.get('ops').data.values()];
  assert.ok(!JSON.stringify(raw.map((r) => ({ ...r, blob: null }))).includes('1990-01-02') && raw.every((r) => r.blob && r.blob.ct), 'la petición guardada va cifrada');
  // sin red no se pierde nada
  net = false; let sum = await box.sync(); assert.strictEqual(sum.stopped, 'red'); assert.strictEqual((await box.stats()).pending, 5);
  // con red: en el orden en que se hicieron; el 2.º movimiento lo rechaza el servidor (200 con otro `result`) y queda como error con su motivo
  net = true; answers.push({ status: 200, body: {} }, { status: 200, body: { message: 'ok' } }, { status: 200, body: { result: 'OK' } }, { status: 200, body: { result: 'ALREADY_ENTERED', details: 'YA había entrado' } });
  sum = await box.sync();
  assert.deepStrictEqual(calls.map((c) => c.url.replace(/\?.*$/, '').split('/').slice(-1)[0]), ['sync', '55', 'cedula', 'movement', 'movement'], 'orden de envío');
  assert.strictEqual(calls[1].method, 'PATCH'); assert.strictEqual(calls[1].ct, 'application/json'); assert.ok(calls[1].op, 'cada reenvío lleva su identificador');
  assert.strictEqual(JSON.parse(calls[1].body).birth_date, '1990-01-02');
  assert.strictEqual(sum.ok, 4); assert.strictEqual(sum.error, 1);
  const bad = (await box.list()).find((i) => i.status === 'error'); assert.strictEqual(bad.label, 'Entrada 2'); assert.ok(/YA había entrado/.test(bad.detail));
  // un 4xx queda como error con el detalle; un 5xx detiene y deja todo pendiente
  await box.enqueueHttp('/api/users/1?event_id=7', { method: 'DELETE' }, 'Eliminar');
  await box.enqueueHttp('/api/users/2?event_id=7', { method: 'DELETE' }, 'Eliminar 2');
  answers.push({ status: 404, body: { detail: 'No existe' } }, { status: 503, body: {} });
  sum = await box.sync(); assert.strictEqual(sum.error, 1); assert.strictEqual(sum.stopped, 'servidor'); assert.strictEqual((await box.stats()).pending, 1);

  // ---------- gwFetch: con red es fetch; si la red se cae JUSTO en ese instante (aún sin modo contingencia) el cambio va a la bandeja, sin «Error de red» (25-nov-2026)
  {
    const idb2 = fakeIndexedDB(); let m = 0, mode = 'ok', poked = 0; const seen = [];
    const box2 = O.create({ idb: idb2, subtle: crypto.subtle, random: (k) => crypto.getRandomValues(new Uint8Array(k)), now: () => now++, fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }), eventId: 9, uuid: () => `g-${++m}` });
    await box2.init();
    const keep = { fetch: globalThis.fetch, box: globalThis.GoldenOutbox, gc: globalThis.GoldenContingency };
    globalThis.GoldenOutbox = { instance: box2 }; globalThis.GoldenContingency = { instance: { active: () => false, noteNetFail: () => { poked++; } } };
    globalThis.fetch = async (url, init) => { seen.push(url); if (mode === 'caida') throw new TypeError('Failed to fetch'); if (mode === 'otro') throw new RangeError('otra cosa'); return { ok: true, status: 200, json: async () => ({ real: true }) }; };
    try {
      let r = await O.gwFetch('/api/users/1?event_id=9', { method: 'PATCH', body: '{}' }, 'Edición');
      assert.ok(r.ok && !r.queued && (await box2.stats()).pending === 0, 'con red: fetch de siempre');
      mode = 'caida'; r = await O.gwFetch('/api/users/1?event_id=9', { method: 'PATCH', body: '{"phone":"1"}' }, 'Edición');
      assert.ok(r.ok && r.queued && r.status === 202, 'la red se cayó en ese instante: a la bandeja'); assert.strictEqual((await box2.stats()).pending, 1); assert.strictEqual(poked, 1, 'y se avisa para pasar ya a contingencia');
      await assert.rejects(O.gwFetch('/api/users?event_id=9'), TypeError, 'una lectura (GET) nunca se encola');
      mode = 'otro'; await assert.rejects(O.gwFetch('/api/users/1', { method: 'PATCH', body: '{}' }, 'x'), RangeError, 'un error que no es de red no se disfraza');
      globalThis.GoldenContingency.instance.active = () => true; mode = 'ok'; const before = seen.length;
      r = await O.gwFetch('/api/users/2?event_id=9', { method: 'DELETE' }, 'Eliminar'); assert.ok(r.queued && seen.length === before, 'en contingencia ni se intenta la red');
    } finally { globalThis.fetch = keep.fetch; globalThis.GoldenOutbox = keep.box; globalThis.GoldenContingency = keep.gc; }
  }

  // ---------- Áreas sin red: mismas respuestas que el servidor para lo que el dispositivo puede comprobar
  const u = { id: '100', first_name: 'Ana', last_name: 'Ruiz' };
  const libre = { id: 1, name: 'Salón', allow_reentry: true }, unica = { id: 2, name: 'Almuerzo', allow_reentry: false };
  let r = D.areaDecide({ area: libre, presence: {}, user: u, direction: 'auto', autoRegister: true, now: Date.UTC(2026, 10, 25, 15, 0, 0) });
  assert.deepStrictEqual([r.result, r.direction, r.area, r.time], ['OK', 'in', 'Salón', '2026-11-25T15:00:00.000']);
  assert.strictEqual(D.areaDecide({ area: libre, presence: { 1: { 100: 'in' } }, user: u, direction: 'auto', autoRegister: true }).direction, 'out', 'automático alterna');
  assert.strictEqual(D.areaDecide({ area: libre, presence: {}, user: u, direction: 'out', autoRegister: true }).result, 'NOT_INSIDE');
  assert.strictEqual(D.areaDecide({ area: libre, presence: {}, user: u, direction: 'in' }).result, 'FOUND_PENDING', 'sin autoregistro pide confirmar');
  assert.strictEqual(D.areaDecide({ area: libre, presence: {}, user: u, direction: 'in', confirm: true }).result, 'OK');
  assert.strictEqual(D.areaDecide({ area: unica, presence: { 2: { 100: 'out' } }, user: u, direction: 'in', autoRegister: true }).result, 'ALREADY_ENTERED', 'sin reingresos: ya entró alguna vez');
  const grupo = { id: 10, name: 'Zona VIP', allow_reentry: false }, a = { id: 11, name: 'Puerta A', allow_reentry: true, parent_id: 10 }, b = { id: 12, name: 'Puerta B', allow_reentry: true, parent_id: 10 };
  r = D.areaDecide({ area: b, parent: grupo, siblings: [a, b], presence: { 11: { 100: 'in' } }, user: u, direction: 'in', autoRegister: true });
  assert.strictEqual(r.result, 'ALREADY_ENTERED'); assert.ok(/Zona VIP/.test(r.details), 'el grupo manda: entrar por A bloquea B'); assert.strictEqual(r.area, 'Zona VIP › Puerta B');

  // ---------- Inventario «lo define la base» sin red
  const pack = { assigned: { 100: [
    { key: 'h', qty: 1, delivered: 0, pending: 1, available: 5, problem: '', item_name: 'Kit', dependent: false },
    { key: 'du1', qty: 2, delivered: 1, pending: 1, available: 3, problem: '', item_name: 'Balón', dependent: true, who: 'Tomás' },
    { key: 'du2', qty: 1, delivered: 0, pending: 1, available: 0, problem: '', item_name: 'Gorra', dependent: true, who: 'Sofía' },
    { key: 'du3', qty: 1, delivered: 0, pending: 1, available: 9, problem: 'no está en el inventario', item_name: 'X', dependent: true } ] } };
  let v = D.assignedView(pack, { id: '100', first_name: 'Ana', status: 'Registrado' }, {});
  assert.strictEqual(v.registered, true); assert.strictEqual(v.pending, 3);
  let plan = D.assignedDeliver(v, { all: true });
  assert.deepStrictEqual(plan.keys, ['h', 'du1'], 'todo lo pendiente que se puede: sin problema y con existencias');
  assert.deepStrictEqual(plan.delivered, [{ qty: 1, name: 'Kit', who: '' }, { qty: 1, name: 'Balón', who: 'Tomás' }]);
  assert.deepStrictEqual(D.assignedDeliver(v, { keys: ['du1'] }).keys, ['du1']);
  v = D.assignedView(pack, { id: '100', status: 'Registrado' }, { h: 1, du1: 1 });                                                  // lo entregado en este dispositivo se suma encima
  assert.deepStrictEqual(v.lines.slice(0, 2).map((l) => [l.pending, l.done, l.delivered]), [[0, true, 1], [0, true, 2]]);
  assert.deepStrictEqual(D.assignedDeliver(v, { all: true }).keys, [], 'no se repite lo ya entregado');
  assert.strictEqual(D.assignedView(pack, { id: '100', status: 'No registrado' }, {}).registered, false);
  assert.deepStrictEqual(D.assignedView(pack, { id: '999', status: 'Registrado' }, {}).lines, []);
  console.log('offline_data_check: OK');
})().catch((e) => { console.error(e); process.exit(1); });
