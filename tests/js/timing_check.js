// Prueba del cronómetro del registro (static/js/timing.js) y de cómo viaja sin red (static/js/contingency.js). Correr: node tests/js/timing_check.js
// Comprueba: la primera tecla arranca y las siguientes no reinician; `payload()` no cierra la medición (un reintento o el aviso de DUPLICADO siguen contando); `done()`/`cancel()` la cierran; sin medición
// no se manda nada (registro sin teclear); más de 10 min se descarta; el FormData no duplica campos; la etiqueta sale de window.UI_FLOW (por defecto «v0»); y sin red el tiempo queda en la cola y se
// envía al sincronizar (sin cédula), mientras un registro sin tiempo sigue saliendo como antes.
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const T = require('../../static/js/timing.js');
const C = require('../../static/js/contingency.js');
const settle = require('./settle').settle;

class FD { constructor() { this.m = new Map(); } set(k, v) { this.m.set(k, v); } append(k, v) { const a = this.m.get(k); this.m.set(k, a === undefined ? v : `${a},${v}`); } get(k) { return this.m.has(k) ? this.m.get(k) : null; } }

(async () => {
  // ---- cronómetro puro
  let now = 1_000_000;
  const t = T.create({ now: () => now, flow: () => 'v0' });
  assert.strictEqual(t.payload(), null, 'sin primera tecla no hay medición (registro desde la lista de recientes)');
  t.start(); now += 1500; t.start();                                         // una segunda tecla NO reinicia
  now += 500;
  assert.deepStrictEqual(t.payload(), { took_ms: 2000, ui_flow: 'v0' });
  now += 1000; assert.deepStrictEqual(t.payload(), { took_ms: 3000, ui_flow: 'v0' }, 'payload() no cierra: el reintento o el DUPLICADO siguen contando desde la misma primera tecla');
  t.done(); assert.strictEqual(t.payload(), null, 'tras registrar, la siguiente persona empieza de cero');
  t.start(); now += 400; assert.strictEqual(t.payload().took_ms, 400);
  t.cancel(); assert.strictEqual(t.payload(), null, 'se vaciaron los buscadores: se descarta');
  t.start(); now += T.MAX_MS + 1; assert.strictEqual(t.payload(), null, 'más de 10 min: pestaña olvidada, no se manda');
  assert.strictEqual(t.startedAt, null, 'y se reinicia');
  t.start(); now += T.MAX_MS; assert.strictEqual(t.payload().took_ms, T.MAX_MS, 'justo en el tope todavía vale');

  // ---- FormData: `set`, nunca duplica
  t.cancel(); t.start(); now += 700;
  const fd = new FD();
  assert.strictEqual(t.appendTo(fd).took_ms, 700);
  now += 300; t.appendTo(fd);
  assert.strictEqual(fd.get('took_ms'), '1000', 'el reintento con el mismo FormData reemplaza el valor, no lo duplica'); assert.strictEqual(fd.get('ui_flow'), 'v0');
  t.done(); const empty = new FD(); assert.strictEqual(t.appendTo(empty), null); assert.strictEqual(empty.get('took_ms'), null, 'sin medición no se agrega nada');

  // ---- etiqueta de pantalla: window.UI_FLOW o «v0»
  global.window = {};
  const t2 = T.create({ now: () => now });
  t2.start(); assert.strictEqual(t2.payload().ui_flow, 'v0');
  global.window.UI_FLOW = '1a'; assert.strictEqual(t2.payload().ui_flow, '1a');
  delete global.window;

  // ---- sin red: el tiempo viaja en la cola y se envía al sincronizar
  const SALT = 'a'.repeat(32);
  const hex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
  const fp = async (cedula) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${cedula}`))).slice(0, 16);
  const people = [{ h: await fp('1001'), n: 'Ana Pérez', c: [], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'No registrado' }];
  const json = (status, data) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, json: async () => data });
  const sent = [];
  const fetchFake = async (url, init = {}) => {
    if (url.endsWith('/access-logs/sync')) {
      const recs = JSON.parse(init.body).records; sent.push(recs);
      return json(200, { results: recs.map((r) => ({ client_id: r.client_id, result: 'created' })) });
    }
    if (url === '/health' || url === '/api/ping-auth') return json(200, {});
    return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 7, status: 'en_proceso' }, salt: SALT, count: 2, people });
  };
  const doc = { body: { appendChild() {}, children: [] }, createElement: () => ({ style: {}, dataset: {}, children: [], appendChild() {}, setAttribute() {}, addEventListener() {}, remove() {} }) };
  const c = C.create({ idb: fakeIndexedDB(), fetch: fetchFake, now: () => 2_000_000, document: doc, subtle: crypto.subtle, eventId: 7, uuid: () => 'u', setInterval: () => 1, clearInterval() {}, setTimeout: () => 0, clearTimeout() {} });
  await c.start(); await settle(); await settle();
  const a = await c.scanLocal('1001'), b = await c.scanLocal('1002');
  const qa = await c.enqueue(a, 'cedula', 'cid-a', { took_ms: 4321, ui_flow: 'v0' });
  const qb = await c.enqueue(b, 'qr', 'cid-b');                              // sin medición (cliente viejo o registro sin teclear)
  assert.strictEqual(qa.took_ms, 4321); assert.strictEqual(qa.ui_flow, 'v0'); assert.ok(!('took_ms' in qb), 'sin medición la cola queda exactamente como antes');
  const dump = JSON.stringify(await c.queueList());
  assert.ok(!dump.includes('1001') && !dump.includes('1002'), 'ni el tiempo ni nada más trae la cédula');
  const bad = await c.enqueue(await c.scanLocal('1001'), 'cedula', 'cid-bad', { took_ms: NaN, ui_flow: 'v0' });
  assert.ok(!('took_ms' in bad), 'un tiempo no numérico no entra a la cola');
  assert.strictEqual(await c.syncQueue(true), 'empty');
  const recs = sent.flat();
  const ra = recs.find((r) => r.client_id === 'cid-a'), rb = recs.find((r) => r.client_id === 'cid-b');
  assert.strictEqual(ra.took_ms, 4321); assert.strictEqual(ra.ui_flow, 'v0'); assert.ok(ra.h && !('cedula' in ra), 'el lote lleva la huella, nunca la cédula');
  assert.ok(!('took_ms' in rb) && !('ui_flow' in rb), 'el registro sin medición viaja igual que antes (JSON sin los campos)');
  console.log('timing_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
