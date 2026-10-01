// Prueba de la máquina de estados de contingencia y del controlador (static/js/contingency.js) con IndexedDB, red, reloj y DOM falsos. Correr: node tests/js/contingency_machine_check.js
// Comprueba: un fallo aislado NO activa contingencia; 2 fallos de salud seguidos o 2 escaneos seguidos sin reintentos sí; salida con 2 chequeos buenos Y una petición autenticada buena;
// franja visible (aria-live); roster guardado/renovado (304)/vencido/borrado (409); sin soporte de IndexedDB: aviso y modo normal.
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');

// ---------------------------------------------------------------- 1) máquina pura
{
  const seen = [];
  let m = C.createMachine((s) => seen.push(s));
  m.health(false); assert.strictEqual(m.state, 'degraded');
  m.health(true); assert.strictEqual(m.state, 'normal', 'un fallo aislado se olvida con el siguiente acierto');
  m.health(false); m.health(true); m.health(false); m.health(true);
  assert.ok(!seen.includes('contingency'), 'fallos NO seguidos no activan contingencia');
  m.health(false); m.health(false); assert.strictEqual(m.state, 'contingency');

  m = C.createMachine();                                     // 2 escaneos seguidos que agotaron reintentos
  m.scanExhausted(); assert.strictEqual(m.state, 'degraded');
  m.scanExhausted(); assert.strictEqual(m.state, 'contingency');
  m = C.createMachine();                                     // pero con un acierto autenticado en medio, no
  m.scanExhausted(); m.authGood(); m.scanExhausted(); assert.strictEqual(m.state, 'degraded'); m.authGood(); assert.strictEqual(m.state, 'normal');
  m = C.createMachine();                                     // un escaneo agotado + salud buena: sigue degradado hasta una petición autenticada buena
  m.scanExhausted(); m.health(true); assert.strictEqual(m.state, 'degraded'); m.authGood(); assert.strictEqual(m.state, 'normal');

  m = C.createMachine();                                     // salida: 2 chequeos buenos SEGUIDOS Y una petición autenticada buena
  m.health(false); m.health(false);
  m.health(true); m.authGood(); assert.strictEqual(m.state, 'contingency', 'falta un segundo chequeo bueno');
  m.health(false); m.health(true); assert.strictEqual(m.readyToProbe(), false, 'un fallo en medio reinicia la cuenta');
  m.health(true); assert.strictEqual(m.readyToProbe(), true); assert.strictEqual(m.state, 'contingency', 'los chequeos solos no bastan');
  m.authGood(); assert.strictEqual(m.state, 'normal');
}

// ---------------------------------------------------------------- 2) controlador
class El {
  constructor(tag) { this.tag = tag; this.style = {}; this.dataset = {}; this.attrs = {}; this.children = []; this.parentNode = null; this.textContent = ''; }
  setAttribute(k, v) { this.attrs[k] = v; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
}
const hex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
const SALT = 'a'.repeat(32);
const fp = async (cedula) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${cedula}`))).slice(0, 16);
const json = (status, data, headers = {}) => ({ ok: status >= 200 && status < 300, status, headers: { get: (k) => headers[k] ?? null }, json: async () => data });

(async () => {
  const idb = fakeIndexedDB();
  const body = new El('body');
  const doc = { body, createElement: (t) => new El(t) };
  let now = 1_000_000, health = true, roster = 'ok', rosterCalls = [], healthCalls = 0, healthSignals = 0;
  const people = [{ h: await fp('1001'), n: 'Ana Pérez', c: ['VIP'], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'Registrado' }];
  const fetchFake = async (url, init = {}) => {
    if (url === '/health') { healthCalls++; if (init.signal) healthSignals++; if (!health) throw new TypeError('Failed to fetch'); return json(200, { status: 'ok' }); }
    assert.ok(url.endsWith('/local-roster')); rosterCalls.push(init.headers || {});
    if (roster === 'ok') return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 7, status: 'en_proceso' }, salt: SALT, count: 2, people }, { ETag: '"v1"' });
    if (roster === '304') return json(304, null);
    if (roster === 'net') throw new TypeError('Failed to fetch');
    return json(roster, {});                                  // 401 / 403 / 409 / 429
  };
  const intervals = [];
  const deps = { idb, fetch: fetchFake, now: () => now, document: doc, subtle: crypto.subtle, eventId: 7, uuid: () => 'uuid-' + (now++),
    setInterval: (f, ms) => { intervals.push(ms); return intervals.length; }, clearInterval() {}, setTimeout: (f, ms) => 0, clearTimeout() {} };
  const c = C.create(deps);
  assert.strictEqual(c.active(), false);
  await c.start();
  await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r));
  assert.deepStrictEqual(intervals, [5000, 240000], 'salud cada 5 s y refresco del roster cada 4 min');
  assert.strictEqual(c.supported, true); assert.strictEqual(c.state(), 'normal'); assert.strictEqual(body.children.length, 0, 'sin franja en modo normal');

  // roster guardado con vigencia de 24 h, SIN la cédula en claro
  const meta = await c.rosterMeta();
  assert.strictEqual(meta.v, 'v1'); assert.strictEqual(meta.expires_at, 1_000_000 + 86400 * 1000); assert.strictEqual(meta.salt, SALT);
  const dump = JSON.stringify([...idb.dbs.get('golden-contingency-7').stores.get('roster').data.values()]);
  assert.ok(!dump.includes('1001') && !dump.includes('1002'), 'el roster guardado no contiene cédulas en claro');
  assert.strictEqual((await c.scanLocal('1.001')).status, 'found', 'la cédula se normaliza (sin puntos) antes de la huella');
  assert.strictEqual((await c.scanLocal('9999')).status, 'not_found');

  // falso positivo: un fallo aislado de salud NO activa contingencia
  health = false; await c.checkHealth(); assert.strictEqual(c.state(), 'degraded'); assert.strictEqual(c.active(), false);
  assert.strictEqual(body.children[0].dataset.state, 'degraded');
  health = true; await c.checkHealth(); assert.strictEqual(c.state(), 'normal'); assert.strictEqual(body.children.length, 0);
  assert.ok(healthSignals === healthCalls, 'cada chequeo de salud lleva su tiempo de espera (AbortController)');

  // 2 fallos seguidos → contingencia, con franja visible y accesible
  health = false; await c.checkHealth(); await c.checkHealth();
  assert.strictEqual(c.state(), 'contingency'); assert.strictEqual(c.active(), true);
  const banner = body.children[0];
  assert.strictEqual(banner.attrs['aria-live'], 'polite'); assert.strictEqual(banner.attrs.role, 'status'); assert.ok(/MODO CONTINGENCIA/.test(banner.textContent));

  // salida: 2 chequeos buenos + petición autenticada buena. Si la sesión venció (401) NO sale, y no insiste antes de 30 s.
  health = true; roster = 401; rosterCalls = [];
  await c.checkHealth(); assert.strictEqual(rosterCalls.length, 0, 'con un solo chequeo bueno no se sonda');
  await c.checkHealth(); assert.strictEqual(rosterCalls.length, 1); assert.strictEqual(c.state(), 'contingency');
  await c.checkHealth(); assert.strictEqual(rosterCalls.length, 1, 'espera de 30 s tras una sonda fallida');
  now += 31000; roster = '304';
  await c.checkHealth(); assert.strictEqual(rosterCalls.length, 2); assert.strictEqual(rosterCalls[1]['If-None-Match'], '"v1"');
  assert.strictEqual(c.state(), 'normal'); assert.strictEqual(body.children.length, 0, 'la franja se quita al salir');
  assert.strictEqual((await c.rosterMeta()).expires_at, now + 86400 * 1000, 'el 304 renueva la vigencia');

  // un 429 cuenta como respuesta autenticada buena (el servidor contestó) pero no renueva nada
  const before = (await c.rosterMeta()).expires_at; roster = 429; now += 1000;
  assert.strictEqual(await c.refreshRoster(), 'ok'); assert.strictEqual((await c.rosterMeta()).expires_at, before);

  // vigencia: pasadas 24 h sin refrescar, la copia no sirve
  now += 86400 * 1000 + 1;
  assert.strictEqual(await c.rosterUsable(), false); assert.strictEqual((await c.scanLocal('1001')).status, 'expired');

  // 409 (evento finalizado) borra el roster pero NO la cola; wipeAll lo borra todo
  roster = 'ok'; assert.strictEqual(await c.refreshRoster(), 'ok'); assert.strictEqual((await c.scanLocal('1001')).status, 'found');
  await c.enqueue(await c.scanLocal('1001'), 'cedula');
  roster = 409; assert.strictEqual(await c.refreshRoster(), 'denied');
  assert.strictEqual(await c.rosterMeta(), undefined); assert.strictEqual((await c.queueList()).length, 1, 'la cola sin sincronizar no se pierde al borrar el roster');
  await c.wipeAll(); assert.strictEqual((await c.queueList()).length, 0);

  // arranque con la copia ya vencida (el navegador estuvo cerrado): se borra sola
  roster = 'ok'; await c.refreshRoster(); now += 86400 * 1000 + 5; c.stop(); roster = 'net';      // sin red al arrancar: solo queda lo vencido, que se borra
  const c2 = C.create(deps); await c2.start(); await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r));
  assert.strictEqual(await c2.rosterMeta(), undefined, 'la copia vencida se borra al arrancar');
  c2.stop();

  // sin IndexedDB: avisa y se queda en modo normal sin romper nada
  const body2 = new El('body');
  const c3 = C.create({ ...deps, idb: undefined, document: { body: body2, createElement: (t) => new El(t) } });
  await c3.start();
  assert.strictEqual(c3.supported, false); assert.strictEqual(c3.active(), false);
  assert.strictEqual(body2.children[0].dataset.state, 'unsupported'); assert.strictEqual(body2.children[0].attrs['aria-live'], 'polite');
  c3.noteScanExhausted(); c3.noteScanExhausted(); assert.strictEqual(c3.active(), false, 'sin soporte nunca entra en contingencia');
  assert.strictEqual(c3.state(), 'normal');
  console.log('contingency.js: máquina de estados, roster local y franja OK');
})().catch((e) => { console.error(e); process.exit(1); });
