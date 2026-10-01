// Prueba de la máquina de estados, el controlador y la sincronización de contingencia (static/js/contingency.js) con IndexedDB, red, reloj y DOM falsos.
// Correr: node tests/js/contingency_machine_check.js
// Comprueba: un fallo aislado NO activa contingencia; 2 fallos de salud seguidos o 2 escaneos seguidos sin reintentos sí; salida con 2 chequeos buenos Y una petición autenticada buena
// (sonda liviana, 429 = alcanzable); sesión vencida (401) = sigue en contingencia con la cola intacta; roster guardado/renovado/vencido/borrado con aviso; cola SIN cédula en claro;
// sincronización por lotes de 500 con espera creciente, borrado de lo sincronizado y lista de «revisar»; tope de 30 días; cierre de sesión; sin soporte de IndexedDB.
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
  constructor(tag) { this.tag = tag; this.style = {}; this.dataset = {}; this.attrs = {}; this.children = []; this.parentNode = null; this._text = ''; this.listeners = {}; }
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(k, f) { this.listeners[k] = f; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
}
const hex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
const SALT = 'a'.repeat(32);
const fp = async (cedula) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${cedula}`))).slice(0, 16);
const json = (status, data, headers = {}) => ({ ok: status >= 200 && status < 300, status, headers: { get: (k) => headers[k] ?? null }, json: async () => data });
const tick = () => new Promise((r) => setImmediate(r));

(async () => {
  const idb = fakeIndexedDB();
  const body = new El('body');
  const doc = { body, createElement: (t) => new El(t) };
  let now = 1_000_000, health = true, roster = 'ok', ping = 200, sync = 'ok', syncBatches = [], rosterCalls = 0, pingCalls = 0, healthCalls = 0, healthSignals = 0;
  let syncReview = new Set(), syncUnknown = new Set();
  const people = [{ h: await fp('1001'), n: 'Ana Pérez', c: ['VIP'], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'Registrado' }];
  const fetchFake = async (url, init = {}) => {
    if (url === '/health') { healthCalls++; if (init.signal) healthSignals++; if (!health) throw new TypeError('Failed to fetch'); return json(200, { status: 'ok' }); }
    if (url === '/api/ping-auth') { pingCalls++; if (ping === 'net') throw new TypeError('Failed to fetch'); return json(ping, {}); }
    if (url.endsWith('/access-logs/sync')) {
      if (sync === 'net') throw new TypeError('Failed to fetch');
      if (sync !== 'ok') return json(sync, {});
      const recs = JSON.parse(init.body).records; syncBatches.push(recs);
      recs.forEach((r) => { assert.ok(r.h && !('cedula' in r), 'el lote lleva la huella, nunca la cédula'); });
      return json(200, { results: recs.map((r) => (syncUnknown.has(r.client_id) ? { client_id: r.client_id, result: 'unknown' } : { client_id: r.client_id, result: 'created', ...(syncReview.has(r.client_id) ? { review: true } : {}) })) });
    }
    assert.ok(url.endsWith('/local-roster')); rosterCalls++;
    if (roster === 'ok') return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 7, status: 'en_proceso' }, salt: SALT, count: 2, people }, { ETag: '"v1"' });
    if (roster === '304') return json(304, null);
    return json(roster, {});                                  // 401 / 403 / 409 / 429
  };
  const intervals = [];
  const deps = { idb, fetch: fetchFake, now: () => now, document: doc, subtle: crypto.subtle, eventId: 7, uuid: () => 'uuid-' + (now++),
    setInterval: (f, ms) => { intervals.push(ms); return intervals.length; }, clearInterval() {}, setTimeout: () => 0, clearTimeout() {} };
  const c = C.create(deps);
  assert.strictEqual(c.active(), false);
  await c.start(); await tick(); await tick();
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

  // se admiten dos personas sin red: la cola guarda huella y nombre, NUNCA la cédula
  const a = await c.scanLocal('1001'), b = await c.scanLocal('1002');
  const qa = await c.enqueue(a, 'cedula', 'cid-a'); await c.enqueue(b, 'qr', 'cid-b');
  const qdump = JSON.stringify(await c.queueList());
  assert.ok(!qdump.includes('1001') && !qdump.includes('1002') && !qdump.includes('cedula":'), 'la cola no guarda la cédula en claro');
  assert.deepStrictEqual(Object.keys(qa).sort(), ['client_id', 'h', 'method', 'n', 'timestamp']); assert.strictEqual(c.queueSize, 2);
  assert.ok(/2 en cola/.test(body.children[0].textContent));

  // salida: 2 chequeos buenos + petición autenticada buena (sonda liviana). Con la sesión vencida (401) NO sale, la franja pide iniciar sesión y la cola queda intacta.
  health = true; ping = 401;
  await c.checkHealth(); assert.strictEqual(pingCalls, 0, 'con un solo chequeo bueno no se sonda');
  await c.checkHealth(); assert.strictEqual(pingCalls, 1); assert.strictEqual(c.state(), 'contingency'); assert.strictEqual(rosterCalls, 1, 'la sonda NO descarga el roster');
  assert.strictEqual(body.children[0].dataset.state, 'session');
  assert.ok(/Sesión vencida: inicia sesión de nuevo; 2 ingreso\(s\) guardados se sincronizarán/.test(body.children[0].textContent));
  assert.strictEqual(body.children[0].children[0].attrs.href, '/login'); assert.strictEqual((await c.queueList()).length, 2);
  await c.checkHealth(); assert.strictEqual(pingCalls, 1, 'espera de 30 s tras una sonda fallida');
  now += 31000; ping = 429;                                                  // un 429 = servidor alcanzable
  await c.checkHealth(); await tick(); await tick();
  assert.strictEqual(pingCalls, 2); assert.strictEqual(c.state(), 'normal'); assert.strictEqual(c.sessionExpired, false);
  // al volver la red: copia al día y cola al servidor (huellas, lote de 2); la 2.ª quedó «review»
  await tick(); await tick(); await tick();
  assert.deepStrictEqual(syncBatches.map((x) => x.map((r) => r.client_id)), [['cid-a', 'cid-b']], 'al salir se envía la cola (huellas, lote de 2)');
  assert.strictEqual((await c.queueList()).length, 0); assert.ok(rosterCalls >= 2, 'refresca el roster al salir');

  // sincronización: lotes de 500, espera creciente, borrado de lo sincronizado y lista de «revisar»
  await c.wipeAll(); await c.clearReview(); syncBatches = []; c.nextSyncAt = 0; c.syncFails = 0;
  for (let i = 0; i < 1200; i++) await c.db.put('queue', { client_id: `q${i}`, h: await fp(String(1000 + (i % 2))), n: 'X', timestamp: new Date(1_000_000 + i).toISOString(), method: 'cedula' });
  await c.db.put('queue', { client_id: 'qrev', h: await fp('1001'), n: 'Ana Pérez', timestamp: new Date(1_000_000 + 5000).toISOString(), method: 'qr' });
  await c.db.put('queue', { client_id: 'qunk', h: 'f'.repeat(16), n: 'Desconocida', timestamp: new Date(1_000_000 + 5001).toISOString(), method: 'cedula' });
  await c.recount();
  syncReview = new Set(['qrev']); syncUnknown = new Set(['qunk']);
  sync = 503; assert.strictEqual(await c.syncQueue(), 'error'); assert.strictEqual(c.syncFails, 1);
  assert.strictEqual(await c.syncQueue(), 'wait', 'espera antes de reintentar'); const firstWait = c.nextSyncAt - now;
  sync = 'net'; assert.strictEqual(await c.syncQueue(true), 'error'); assert.strictEqual(c.nextSyncAt - now, firstWait * 2, 'espera creciente');
  sync = 429; assert.strictEqual(await c.syncQueue(true), 'error');
  sync = 401; assert.strictEqual(await c.syncQueue(true), 'session'); assert.strictEqual(c.sessionExpired, true); assert.strictEqual((await c.queueList()).length, 1202, 'cola intacta con sesión vencida');
  assert.strictEqual(body.children[0].dataset.state, 'session');
  c.sessionExpired = false; sync = 403; assert.strictEqual(await c.syncQueue(true), 'denied'); assert.strictEqual((await c.queueList()).length, 1202);
  assert.strictEqual(body.children[0].dataset.state, 'notice'); assert.ok(/No se pudo sincronizar.*1202 ingreso\(s\) siguen guardados/.test(body.children[0].textContent));
  c.sessionExpired = false; sync = 'ok'; c.syncFails = 0;
  assert.strictEqual(await c.syncQueue(true), 'empty');
  assert.deepStrictEqual(syncBatches.map((x) => x.length), [500, 500, 202], 'lotes de 500');
  assert.strictEqual((await c.queueList()).length, 0, 'lo sincronizado se borra');
  assert.ok(syncBatches[0][0].timestamp < syncBatches[0][499].timestamp, 'en orden de marca de tiempo');
  const rev = (await c.reviewList()).sort((x, y) => (x.client_id < y.client_id ? -1 : 1));
  assert.deepStrictEqual(rev.map((x) => [x.client_id, x.reason]), [['qrev', 'review'], ['qunk', 'unknown']]); assert.strictEqual(c.reviewCount, 2);
  assert.strictEqual(body.children[0].dataset.state, 'review'); const reviewBtn = body.children[0].children.find((x) => /Revisar \(2\)/.test(x.textContent)); assert.ok(reviewBtn);
  await reviewBtn.listeners.click(); await tick(); await tick();
  const dialog = body.children.find((x) => x.attrs.role === 'dialog'); assert.ok(dialog, 'la lista de revisar se muestra'); assert.ok(/Ana Pérez/.test(dialog.textContent) && /otro quiosco/.test(dialog.textContent));
  await dialog.children[0].children[2].listeners.click(); await tick(); await tick();
  assert.strictEqual(c.reviewCount, 0); assert.strictEqual(body.children.filter((x) => x.attrs.role === 'dialog').length, 0);

  // tope de 30 días sin sincronizar: se descarta CON aviso
  await c.db.put('queue', { client_id: 'viejo', h: await fp('1001'), n: 'Ana', timestamp: new Date(now - 31 * 86400 * 1000).toISOString(), method: 'cedula' });
  await c.db.put('queue', { client_id: 'reciente', h: await fp('1001'), n: 'Ana', timestamp: new Date(now - 29 * 86400 * 1000).toISOString(), method: 'cedula' });
  assert.strictEqual(await c.pruneOld(), 1); assert.deepStrictEqual((await c.queueList()).map((x) => x.client_id), ['reciente']);
  assert.ok(/1 ingreso\(s\) llevaban más de 30 días sin sincronizar/.test(body.children[0].textContent)); assert.strictEqual(body.children[0].dataset.state, 'notice');
  await body.children[0].children.find((x) => x.textContent === 'Entendido').listeners.click(); assert.notStrictEqual(body.children[0] && body.children[0].dataset.state, 'notice');

  // cierre de sesión: intenta sincronizar y devuelve lo que queda sin sincronizar (la cola se conserva)
  sync = 503; c.nextSyncAt = 0; assert.strictEqual(await c.beforeLogout(), 1); assert.strictEqual((await c.queueList()).length, 1);
  sync = 'ok'; assert.strictEqual(await c.beforeLogout(), 0);

  // roster: 304 renueva, 429 es respuesta buena, vence a las 24 h
  roster = 'ok'; await c.refreshRoster(); roster = '304'; assert.strictEqual(await c.refreshRoster(), 'ok'); assert.strictEqual((await c.rosterMeta()).expires_at, now + 86400 * 1000, 'el 304 renueva la vigencia');
  const before = (await c.rosterMeta()).expires_at; roster = 429; now += 1000;
  assert.strictEqual(await c.refreshRoster(), 'ok'); assert.strictEqual((await c.rosterMeta()).expires_at, before);
  now += 86400 * 1000 + 1;
  assert.strictEqual(await c.rosterUsable(), false); assert.strictEqual((await c.scanLocal('1001')).status, 'expired');

  // 401 al refrescar: franja de sesión vencida con la cola; 409 (evento finalizado): roster borrado, aviso con los pendientes y, sincronizada la cola, se borra todo
  roster = 'ok'; assert.strictEqual(await c.refreshRoster(), 'ok');
  await c.enqueue(await c.scanLocal('1001'), 'cedula', 'ultimo');
  roster = 401; assert.strictEqual(await c.refreshRoster(), 'unauth'); assert.strictEqual(body.children[0].dataset.state, 'session');
  assert.ok(/inicia sesión de nuevo; 1 ingreso\(s\)/.test(body.children[0].textContent));
  roster = 409; assert.strictEqual(await c.refreshRoster(), 'denied');
  assert.strictEqual(await c.rosterMeta(), undefined); assert.strictEqual((await c.queueList()).length, 1, 'la cola sin sincronizar no se pierde al borrar el roster');
  c.sessionExpired = false; c.render();
  assert.strictEqual(body.children[0].dataset.state, 'notice'); assert.ok(/El evento finalizó: se borró la copia local\. 1 ingreso\(s\) pendientes de sincronizar/.test(body.children[0].textContent));
  c.nextSyncAt = 0; sync = 'ok'; assert.strictEqual(await c.syncQueue(true), 'empty');
  assert.strictEqual((await c.queueList()).length, 0, 'sincronizado y evento finalizado: no queda nada');

  // 403 (sin permiso): también borra el roster y avisa
  roster = 'ok'; const c4 = C.create({ ...deps, eventId: 8 }); await c4.start(); await tick(); await tick();
  roster = 403; assert.strictEqual(await c4.refreshRoster(), 'denied');
  assert.ok(/Ya no tienes acceso a este evento: se borró la copia local/.test(c4.notice.text(0))); c4.stop();

  // arranque con la copia ya vencida (el navegador estuvo cerrado): se borra sola
  roster = 'ok'; await c.refreshRoster(); now += 86400 * 1000 + 5; c.stop(); roster = 'net';
  const c2 = C.create(deps); await c2.start(); await tick(); await tick();
  assert.strictEqual(await c2.rosterMeta(), undefined, 'la copia vencida se borra al arrancar'); c2.stop();

  // almacenamiento persistente: se pide al arrancar sin bloquear; concedido, negado, ya persistente, API ausente o que falla: el arranque nunca se rompe
  for (const [label, storage, expected, persistCalls] of [
    ['concedido', { persisted: async () => false, persist: async () => true }, true, 1],
    ['negado', { persisted: async () => false, persist: async () => false }, false, 1],
    ['ya persistente', { persisted: async () => true, persist: async () => { throw new Error('no debe pedirlo otra vez'); } }, true, 0],
    ['persist falla', { persisted: async () => false, persist: async () => { throw new Error('boom'); } }, false, 1],
    ['sin API', undefined, null, 0],
    ['API incompleta', {}, null, 0],
  ]) {
    let calls = 0; const st = storage && storage.persist ? { ...storage, persist: (...a) => { calls++; return storage.persist(...a); } } : storage;
    const cp = C.create({ ...deps, eventId: 20 + calls + Math.floor(Math.random() * 1000), storage: st });
    await cp.start(); await cp.persistRequest; await tick();
    assert.strictEqual(cp.supported, true, `${label}: el arranque sigue`); assert.strictEqual(cp.persistent, expected, label); assert.strictEqual(calls, persistCalls, label); cp.stop();
  }
  let resolvePersist; const slow = { persisted: async () => false, persist: () => new Promise((r) => { resolvePersist = r; }) };
  const cs = C.create({ ...deps, eventId: 77, storage: slow }); const started = await Promise.race([cs.start().then(() => 'listo'), new Promise((r) => setTimeout(() => r('bloqueado'), 1500))]);
  assert.strictEqual(started, 'listo', 'start() no espera la respuesta del permiso'); resolvePersist(true); await cs.persistRequest; assert.strictEqual(cs.persistent, true); cs.stop();

  // sin IndexedDB: avisa y se queda en modo normal sin romper nada
  const body2 = new El('body');
  const c3 = C.create({ ...deps, idb: undefined, document: { body: body2, createElement: (t) => new El(t) } });
  await c3.start();
  assert.strictEqual(c3.supported, false); assert.strictEqual(c3.active(), false);
  assert.strictEqual(body2.children[0].dataset.state, 'unsupported'); assert.strictEqual(body2.children[0].attrs['aria-live'], 'polite');
  c3.noteScanExhausted(); c3.noteScanExhausted(); assert.strictEqual(c3.active(), false, 'sin soporte nunca entra en contingencia'); assert.strictEqual(c3.state(), 'normal');
  console.log('contingency.js: máquina de estados, sonda, sincronización, revisar, tope de 30 días y avisos OK');
})().catch((e) => { console.error(e); process.exit(1); });
