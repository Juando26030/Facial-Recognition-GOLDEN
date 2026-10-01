// Prueba del registro sin red (static/js/directory.js + static/js/contingency.js) con DOM, reloj, IndexedDB y servidor falsos. Correr: node tests/js/contingency_scan_check.js
// Comprueba: en contingencia el escaneo NO usa la red; quien está en la copia local se admite (mismo toast «Acreditado: …») y se encola con client_id, marca de tiempo y método (cédula/QR);
// quien no está NO se admite («No registrado: verificar manualmente»); un repetido pide confirmación (DUPLICADO) y sin confirmar no se encola; copia vencida; y el paso automático:
// 2 escaneos seguidos que agotan sus reintentos activan la contingencia y el segundo ya se atiende sin red; en modo normal todo sigue por el servidor.
const fs = require('fs');
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this._html = ''; this.offsetParent = {}; this.value = ''; this.attrs = {}; this.textContent = ''; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c) { c.parentNode = this; this.children.unshift(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
  addEventListener(k, f) { this.listeners[k] = f; }
  set innerHTML(v) { this._html = v; this.children = []; }
  get innerHTML() { return this._html; }
  closest() { return table; }
  setAttribute(k, v) { this.attrs[k] = v; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  replaceChildren(...c) { c.forEach((x) => { x.parentNode = this; }); this.children = c; this._html = ''; }
}
const container = new El('div');
const table = container.appendChild(new El('table'));
const els = { tbody: new El('tbody'), cedula: new El('input') };
const body = new El('body');
global.window = { EVENT_ID: 7, STAFF_ROLE: 'digitador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [] };
global.document = { getElementById: (id) => els[id] || null, createElement: (t) => new El(t), visibilityState: 'visible', body, addEventListener() {} };
global.setInterval = () => 1;
global.CSS = { escape: (x) => x };
let now = 5_000_000, timers = [];
global.setTimeout = (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; };
global.clearTimeout = (t) => { timers = timers.filter((x) => x !== t); };
const flush = () => new Promise((r) => setImmediate(r));
const advance = async (ms) => { now += ms; const due = timers.filter((t) => t.at <= now); timers = timers.filter((t) => t.at > now); due.forEach((t) => t.f()); await flush(); await flush(); };
const toasts = [];
global.showToast = (m, t) => toasts.push([m, t]);
let confirmAnswer = false, confirmCalls = 0;
global.confirmDuplicateRegistration = async () => { confirmCalls++; return confirmAnswer; };

const hex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
const SALT = 'b'.repeat(32);
const fp = async (cedula) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${cedula}`))).slice(0, 16);
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, json: async () => data });
let checkinCalls = 0, checkinStatus = 200, healthOk = true, AUTO = true, netDown = false;
global.fetch = async (url, init = {}) => {
  if (netDown) throw new TypeError('Failed to fetch');
  const u = new URL(url, 'http://x');
  if (u.pathname === '/health') { if (!healthOk) throw new TypeError('Failed to fetch'); return json(200, { status: 'ok' }); }
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 7, status: 'en_proceso', auto_register: AUTO }, salt: SALT, count: 3, people: ROSTER });
  if (u.pathname === '/api/users/changes') return json(200, { cursor: '1:1', total: 0, users: [] });
  if (u.pathname === '/api/users') return json(200, []);
  assert.strictEqual(u.pathname, '/api/checkin-cedula'); checkinCalls++;
  if (checkinStatus !== 200) return json(checkinStatus, {});
  return json(200, { result: 'SÍ', data: { id: init.body.get('cedula'), first_name: 'Ana', last_name: 'Pérez' } });
};
let ROSTER = [];

eval(fs.readFileSync('static/js/directory.js', 'utf8'));

(async () => {
  ROSTER = [{ h: await fp('1001'), n: 'Ana Pérez', c: [], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'Registrado' }, { h: await fp('1003'), n: 'Eva Ríos', c: [], s: 'No registrado' }];
  const fpEva = await fp('1003');
  let seq = 0;
  const GC_IDB = fakeIndexedDB();
  const GC = C.create({ idb: GC_IDB, fetch: global.fetch, now: () => now, document: global.document, subtle: crypto.subtle, eventId: 7, uuid: () => `cid-${++seq}`,
    setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });
  await GC.start(); await flush(); await flush();
  window.GoldenContingency = { instance: GC };
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula' }, fastCheckin: true });
  const reset = () => { toasts.length = 0; checkinCalls = 0; };
  const goContingency = async () => { healthOk = false; await GC.checkHealth(); await GC.checkHealth(); assert.strictEqual(GC.active(), true); };

  // 0) modo normal: todo por el servidor, como siempre
  await d.submitScannedCedula('1001');
  assert.strictEqual(checkinCalls, 1); assert.ok(toasts.some(([m]) => /Acreditado: Ana Pérez/.test(m))); assert.strictEqual((await GC.queueList()).length, 0);

  // 1) contingencia: el escaneo NO toca la red, admite al que está en la copia local, con el mismo toast
  await goContingency(); reset();
  await d.submitScannedCedula('1001');
  assert.strictEqual(checkinCalls, 0, 'en contingencia no se espera a la red'); assert.ok(toasts.some(([m, t]) => /^Acreditado: Ana Pérez/.test(m) && t === 'success'));
  let q = await GC.queueList();
  assert.strictEqual(q.length, 1); assert.ok(typeof q[0].client_id === 'string' && q[0].client_id.length >= 8, 'client_id generado por la estación'); assert.strictEqual(q[0].h, await fp('1001')); assert.ok(!('cedula' in q[0]), 'la cola no guarda la cédula'); assert.strictEqual(q[0].method, 'cedula');
  assert.ok(!Number.isNaN(Date.parse(q[0].timestamp)) && q[0].timestamp.endsWith('Z'), 'marca de tiempo ISO UTC');
  assert.strictEqual(confirmCalls, 0, 'quien no constaba como registrado se admite sin preguntar');

  // 2) QR: mismo flujo, método «qr»
  reset(); await d.submitScannedCedula('1003', null, 'qr');
  q = await GC.queueList(); assert.strictEqual(q.length, 2); assert.strictEqual(q.find((x) => x.h === fpEva).method, 'qr');

  // 3) repetido en este quiosco: pide confirmación (DUPLICADO); si se rechaza no se encola; si se acepta se encola con OTRO client_id
  reset(); confirmAnswer = false; await d.submitScannedCedula('1001');
  assert.strictEqual(confirmCalls, 1); assert.strictEqual((await GC.queueList()).length, 2); assert.ok(!toasts.some(([m]) => /Acreditado/.test(m)));
  confirmAnswer = true; await d.submitScannedCedula('1001');
  q = await GC.queueList(); assert.strictEqual(q.length, 3); assert.strictEqual(new Set(q.map((x) => x.client_id)).size, 3);

  // 4) ya constaba como registrado en la copia local (otro quiosco, antes del corte): también avisa, y se admite si se confirma
  reset(); confirmCalls = 0; confirmAnswer = true; await d.submitScannedCedula('1002');
  assert.strictEqual(confirmCalls, 1); assert.strictEqual((await GC.queueList()).length, 4);

  // 5) quien NO está en la copia local no se admite: «No registrado: verificar manualmente», nada en la cola
  reset(); await d.submitScannedCedula('9999');
  assert.deepStrictEqual(toasts, [['No registrado: verificar manualmente', 'error']]); assert.strictEqual((await GC.queueList()).length, 4); assert.strictEqual(checkinCalls, 0);

  // 6) copia vencida: no se admite a nadie
  reset(); const realNow = now; now += 86400 * 1000 + 10;
  await d.submitScannedCedula('1003');
  assert.deepStrictEqual(toasts, [['No hay copia local vigente: verificar manualmente', 'error']]); assert.strictEqual((await GC.queueList()).length, 4);
  now = realNow;

  // 7) paso automático: 2 escaneos seguidos que agotan sus reintentos activan la contingencia y el 2.º ya se atiende sin red
  healthOk = true; checkinStatus = 200;
  await GC.refreshRoster(); GC.machine.health(true); GC.machine.health(true);
  assert.strictEqual(GC.active(), true); GC.noteAuthGood(); assert.strictEqual(GC.active(), false, 'salió tras 2 chequeos buenos y una petición buena');
  await GC.wipeAll(); await GC.refreshRoster(); reset(); checkinStatus = 502;
  const scan = async () => { const p = d.submitScannedCedula('1003'); await flush(); await advance(400); await advance(800); await p; };
  await scan();                                                                          // 1.º: 3 intentos, todos 502 → «degradado», se muestra el error de siempre
  assert.strictEqual(checkinCalls, 3); assert.strictEqual(GC.state(), 'degraded'); assert.strictEqual((await GC.queueList()).length, 0);
  await scan();                                                                          // 2.º: agota otra vez → contingencia y ESTE escaneo se admite sin red
  assert.strictEqual(GC.active(), true); assert.strictEqual(checkinCalls, 6);
  q = await GC.queueList(); assert.strictEqual(q.length, 1); assert.strictEqual(q[0].h, fpEva);
  assert.ok(toasts.some(([m]) => /Acreditado: Eva Ríos/.test(m)));
  // 8) «Modo autoregistro» APAGADO: sin red SOLO busca y resalta (como FOUND_PENDING en línea); acredita únicamente con el botón «Acreditar» de la fila
  AUTO = false; healthOk = true; checkinStatus = 200;
  await GC.refreshRoster(); GC.machine.health(true); GC.machine.health(true); GC.noteAuthGood(); await goContingency();
  await GC.wipeAll(); ROSTER = ROSTER.map((r) => ({ ...r, s: r.h === ROSTER[1].h ? 'Registrado' : 'No registrado' })); await GC.refreshRoster(); netDown = true; reset();
  assert.strictEqual(await GC.autoRegister(), false, 'el modo viaja con la copia');
  const actionTd = new El('td'); const fakeRow = { querySelector: (sel) => (sel === '.action-cell' ? actionTd : null) };
  els.tbody.querySelector = (sel) => (/data-user-id="1001"/.test(sel) ? fakeRow : null);
  await d.submitScannedCedula('1001');
  assert.strictEqual((await GC.queueList()).length, 0, 'con el modo apagado escanear NO acredita'); assert.ok(toasts.some(([m]) => /autoregistro está apagado/.test(m)) && !toasts.some(([m]) => /^Acreditado/.test(m)));
  assert.strictEqual(els.cedula.value, '1001', 'resalta a la persona (filtra por su cédula)');
  const pending = actionTd.children.find((x) => /btn-accredit-pending/.test(x.className)); assert.ok(pending, 'botón «Acreditar» en la fila');
  await pending.listeners.click(); await flush(); await flush();
  assert.strictEqual((await GC.queueList()).length, 1); assert.ok(toasts.some(([m]) => /^Acreditado: Ana Pérez/.test(m)), 'el botón sí acredita (y encola)');
  reset(); await d.submitScannedCedula('9999'); assert.deepStrictEqual(toasts, [['No registrado: verificar manualmente', 'error']]);
  // y con el modo ENCENDIDO acredita al escanear (ya probado arriba): el valor sobrevive a recargar la página SIN red (se lee de IndexedDB)
  for (const mode of [false, true]) {
    netDown = false; AUTO = mode; await GC.refreshRoster(); netDown = true;
    const reloaded = C.create({ idb: GC_IDB, fetch: global.fetch, now: () => now, document: global.document, subtle: crypto.subtle, eventId: 7, uuid: () => 'z', setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });
    await reloaded.start(); await flush(); assert.strictEqual(await reloaded.autoRegister(), mode, `tras recargar sin red el modo sigue en ${mode}`); reloaded.stop();
  }
  console.log('contingency: registro sin red OK (sin red, roster local, DUPLICADO, no registrado, vencida, paso automático)');
})().catch((e) => { console.error(e); process.exit(1); });
