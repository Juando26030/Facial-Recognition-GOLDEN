// Prueba del modal «Editar» limitado sin red (static/js/directory.js::buildOfflineEditModal + contingency.js) con DOM, IndexedDB y red falsos. Correr: node tests/js/contingency_modal_check.js
// Comprueba: en contingencia Editar solo ofrece nombre (lectura) y «Estado de registro» con el aviso exacto; «Registrado» se encola como un escaneo (client_id, huella de la copia local, método «manual»),
// con el aviso de DUPLICADO si ya consta o está en la cola; «No registrado» y quien no está en la copia no se encolan; nunca «Error de red» genérico; si vuelve la red con el modal abierto se avisa.
const fs = require('fs');
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this.attrs = {}; this.textContent = ''; this.value = ''; this.className = ''; this.disabled = false; this.offsetParent = {}; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c) { c.parentNode = this; this.children.unshift(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
  addEventListener(k, f) { this.listeners[k] = f; }
  closest() { return null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
const body = new El('body');
global.window = { EVENT_ID: 1, STAFF_ROLE: 'digitador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [] };
global.document = { getElementById: () => null, createElement: (t) => new El(t), visibilityState: 'visible', head: new El('head'), body, addEventListener() {} };
global.setInterval = () => 1;
let now = 9_000_000;
const toasts = [];
global.showToast = (m, t) => toasts.push([m, t]);
let dupAnswer = false, dupCalls = 0;
global.confirmDuplicateRegistration = async () => { dupCalls++; return dupAnswer; };
global.CSS = { escape: (x) => x };
const flush = async () => { for (let i = 0; i < 15; i++) await new Promise((r) => setImmediate(r)); };

const hex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
const SALT = 'e'.repeat(32);
const fp = async (c) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${c}`))).slice(0, 16);
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, json: async () => data });
let healthOk = true, ROSTER = [], fetches = [];
global.fetch = async (url) => {
  fetches.push(String(url));
  const u = new URL(url, 'http://x');
  if (u.pathname === '/health') { if (!healthOk) throw new TypeError('x'); return json(200, {}); }
  if (u.pathname === '/api/ping-auth') return json(200, {});
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 1, status: 'en_proceso', auto_register: false }, salt: SALT, count: ROSTER.length, people: ROSTER });
  if (u.pathname.endsWith('/access-logs/sync')) return json(200, { results: [] });
  throw new TypeError('sin red: ' + u.pathname);
};
eval(fs.readFileSync('static/js/directory.js', 'utf8'));

(async () => {
  ROSTER = [{ h: await fp('1001'), n: 'Ana Pérez', c: [], s: 'No registrado' }, { h: await fp('1002'), n: 'Luis Gómez', c: [], s: 'Registrado' }, { h: await fp('1003'), n: 'Eva Ríos', c: [], s: 'No registrado' }];
  const GC = C.create({ idb: fakeIndexedDB(), fetch: global.fetch, now: () => now, document: global.document, subtle: crypto.subtle, eventId: 1, uuid: (() => { let n = 0; return () => 'u' + (++n); })(), setInterval: () => 1, clearInterval() {}, setTimeout: () => 0, clearTimeout() {} });
  await GC.start(); await flush();
  window.GoldenContingency = { instance: GC };
  const open = (user) => window.GoldenDirectory.openEdit(user);
  const reset = () => { toasts.length = 0; fetches.length = 0; };

  // sin contingencia el modal no es el limitado (aquí no se construye el normal: necesita FieldRender); con contingencia sí
  healthOk = false; await GC.checkHealth(); await GC.checkHealth(); assert.strictEqual(GC.active(), true);
  fetches.length = 0;

  // 1) fila cargada con red (tiene cédula): solo nombre de lectura + estado, con el aviso exacto
  let m = open({ id: '1001', first_name: 'Ana', last_name: 'Pérez', status: 'No registrado' });
  assert.strictEqual(m.notice.textContent, 'Sin conexión: solo se puede cambiar el estado de registro; para editar datos espera a que vuelva la red'); assert.strictEqual(m.notice.attrs.role, 'status');
  assert.strictEqual(m.name.value, 'Ana Pérez'); assert.ok(m.name.readOnly && m.name.disabled, 'el nombre es de solo lectura');
  assert.deepStrictEqual(m.box.children.map((c) => c.tagName), ['h4', 'p', 'input', 'label', 'select', 'div'], 'no hay más campos');
  assert.strictEqual(m.select.value, 'registrado'); assert.deepStrictEqual(m.select.children.map((o) => o.value), ['no_registrado', 'registrado']);
  await m.save.listeners.click(); await flush();
  const q = await GC.queueList(); assert.strictEqual(q.length, 1);
  assert.deepStrictEqual([q[0].method, q[0].h, q[0].n, typeof q[0].client_id, !Number.isNaN(Date.parse(q[0].timestamp)), 'cedula' in q[0]], ['manual', await fp('1001'), 'Ana Pérez', 'string', true, false], 'cola: client_id, huella, marca de tiempo y método manual (sin cédula)');
  assert.ok(toasts.some(([t, k]) => /^Acreditado: Ana Pérez/.test(t) && k === 'success')); assert.ok(!body.children.includes(m.overlay), 'el modal se cierra');
  assert.ok(!toasts.some(([t]) => /Error de red/.test(t)), 'nunca «Error de red» genérico'); assert.ok(!fetches.some((u) => /api\/(users|events\/1\/users)/.test(u)), 'no intenta guardar por la red');

  // 2) ya consta (está en la cola de este quiosco): pide DUPLICADO; sin confirmar no se encola, confirmando sí (otro client_id)
  reset(); dupAnswer = false; m = open({ id: '1001', first_name: 'Ana', last_name: 'Pérez', status: 'Registrado' }); await m.save.listeners.click(); await flush();
  assert.strictEqual(dupCalls, 1); assert.strictEqual((await GC.queueList()).length, 1); assert.ok(body.children.includes(m.overlay), 'si se rechaza el duplicado el modal sigue abierto');
  dupAnswer = true; await m.save.listeners.click(); await flush(); const q2 = await GC.queueList(); assert.strictEqual(q2.length, 2); assert.strictEqual(new Set(q2.map((x) => x.client_id)).size, 2); assert.ok(!body.children.includes(m.overlay));

  // 3) ya constaba como registrado en la copia local (otro quiosco): también avisa
  reset(); dupCalls = 0; dupAnswer = false; m = open({ id: '1002', first_name: 'Luis', last_name: 'Gómez', status: 'Registrado' }); await m.save.listeners.click(); await flush();
  assert.strictEqual(dupCalls, 1); assert.strictEqual((await GC.queueList()).length, 2); m.close();

  // 4) fila de la LISTA LOCAL (sin cédula, solo huella)
  reset(); m = open({ id: '', first_name: 'Eva Ríos', last_name: '', status: 'No registrado', __h: await fp('1003'), __local: true }); await m.save.listeners.click(); await flush();
  const q3 = await GC.queueList(); assert.strictEqual(q3.length, 3); assert.strictEqual(q3.find((x) => x.n === 'Eva Ríos').h, await fp('1003')); assert.strictEqual(q3.find((x) => x.n === 'Eva Ríos').method, 'manual');

  // 5) «No registrado» no se puede aplicar sin red; quien no está en la copia no se admite
  reset(); m = open({ id: '1001', first_name: 'Ana', last_name: 'Pérez', status: 'Registrado' }); m.select.value = 'no_registrado'; await m.save.listeners.click(); await flush();
  assert.deepStrictEqual(toasts, [['Sin conexión: solo se puede registrar; para quitar un registro espera a que vuelva la red', 'error']]); assert.strictEqual((await GC.queueList()).length, 3); assert.ok(body.children.includes(m.overlay)); m.close();
  reset(); m = open({ id: '9999', first_name: 'Nadie', last_name: '', status: 'No registrado' }); await m.save.listeners.click(); await flush();
  assert.deepStrictEqual(toasts, [['No registrado: verificar manualmente', 'error']]); assert.strictEqual((await GC.queueList()).length, 3); m.close();

  // 6) vuelve la red con el modal abierto: se avisa en vez de intentar guardar sin red
  reset(); m = open({ id: '1003', first_name: 'Eva', last_name: 'Ríos', status: 'Registrado' });
  healthOk = true; await GC.checkHealth(); await GC.checkHealth(); await flush(); assert.strictEqual(GC.state(), 'normal');
  await m.save.listeners.click(); await flush(); assert.ok(toasts.some(([t]) => /Volvió la conexión/.test(t))); assert.ok(!body.children.includes(m.overlay));
  console.log('directory.js: Editar sin red (solo estado de registro, método manual, DUPLICADO, sin «Error de red») OK');
})().catch((e) => { console.error(e); process.exit(1); });
