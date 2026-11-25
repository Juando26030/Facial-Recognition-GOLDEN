// PR3 (4a, docs/etapa/0A): flujo de autoimpresión de la pantalla de Registro con badge-render.js y directory.js REALES, DOM, red, IndexedDB y ventanas falsos.
// Correr: node tests/js/autoprint_flow_check.js
//  A  la bandera de la página está congelada (false) pero el servidor responde auto_print:true → imprime sin recargar; y al revés.
//  B  «Deshacer» suelta el candado de 30 s: volver a acreditar a la misma persona imprime (T5); si el navegador bloquea la ventana el candado no se gasta.
//  C  la ventana `goldenweb_print` se abre DENTRO del gesto (antes de cualquier llamada de red) y luego se navega; si no hay impresión se cierra; sin autorregistro no se abre.
//  E  cada sondeo del directorio (flags de /users/changes) deja la bandera de autorregistro en la copia local.
//  F  el guardia de openRegisterModal ya no existe en la plantilla; todo maybeAutoPrint de la puerta recibe la respuesta del servidor.
const fs = require('fs');
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this._html = ''; this.offsetParent = {}; this.value = ''; this.attrs = {}; this.innerText = ''; this.className = ''; this.placeholder = ''; this.disabled = false; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) { c.parentNode = this; const i = ref ? this.children.indexOf(ref) : -1; if (i >= 0) this.children.splice(i, 0, c); else if (ref === null) this.children.push(c); else this.children.unshift(c); return c; }
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
const els = { tbody: new El('tbody'), cedula: new El('input'), nombre: new El('input'), entidad: new El('input') };
els.entidad.placeholder = 'Entidad';

const events = [];                                              // línea de tiempo: ventanas y llamadas de red, en orden
const wins = [];
let blockPopups = false;
global.window = {
  EVENT_ID: 1, STAFF_ROLE: 'digitador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [], EVENT_AUTO_PRINT: false,       // EVENT_AUTO_PRINT congelado en false (la pantalla se abrió con el interruptor apagado)
  open(url, name) {
    events.push('open:' + url);
    if (blockPopups) return null;
    const w = { url, name, closed: false, close() { this.closed = true; events.push('close'); }, _href: '' };
    Object.defineProperty(w, 'location', { value: { set href(v) { w._href = v; events.push('nav:' + v); } } });
    wins.push(w);
    return w;
  },
};
global.document = { getElementById: (id) => els[id] || null, createElement: (t) => new El(t), visibilityState: 'visible', head: new El('head'), body: new El('body'), addEventListener() {} };
global.setInterval = () => 1;
let now = 7_000_000, timers = [];
global.setTimeout = (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; };
global.clearTimeout = (t) => { timers = timers.filter((x) => x !== t); };
const { settle: flush, until } = require('./settle');
const advance = async (ms) => { now += ms; const due = timers.filter((t) => t.at <= now); timers = timers.filter((t) => t.at > now); due.forEach((t) => t.f()); await flush(); };
const toasts = []; global.showToast = (m, t, o) => { toasts.push({ m, t, o }); return { close() {} }; };
global.CSS = { escape: (x) => x };
global.confirmDuplicateRegistration = async () => false;

const hex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
const SALT = 'e'.repeat(32);
const json = (status, data, headers = {}) => ({ ok: status >= 200 && status < 300, status, headers: { get: (k) => headers[k] ?? null }, json: async () => data });
const SERVER = [{ id: '1001', first_name: 'Ana', last_name: 'Pérez', entity: 'ACME', status: 'No registrado' }, { id: '1002', first_name: 'Luis', last_name: 'Gómez', entity: 'ACME', status: 'No registrado' }];
let checkinReply = null, changesFlags = { auto_print: false, auto_register: false }, rosterAuto = false, undoReply = { status: 200, body: { undone: true, user_id: '1001', auto_print: true, auto_register: true } };
global.fetch = async (url, init = {}) => {
  const u = new URL(url, 'http://x');
  events.push('fetch:' + u.pathname);
  if (u.pathname === '/api/checkin-cedula') { const fd = init.body; return json(200, checkinReply(fd)); }
  if (u.pathname.endsWith('/accreditations/undo')) return json(undoReply.status, undoReply.body);
  if (/print-log$/.test(u.pathname)) return json(200, {});
  if (u.pathname === '/health') return json(200, {});
  if (u.pathname === '/api/ping-auth') return json(200, {});
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 1, status: 'en_proceso', auto_register: rosterAuto }, salt: SALT, count: 0, people: [] });
  if (u.pathname === '/api/users/changes') return json(200, { cursor: '1:1', total: SERVER.length, users: [], flags: changesFlags });
  if (u.pathname === '/api/users') return json(200, SERVER, { 'X-Total-Count': String(SERVER.length) });
  if (u.pathname.endsWith('/access-logs/sync')) return json(200, { results: [] });
  throw new Error('ruta inesperada ' + u.pathname);
};
require('../../static/js/badge-render.js'); global.BadgePrint = window.BadgePrint;        // el despachador REAL (en el navegador window es el global)
eval(fs.readFileSync('static/js/directory.js', 'utf8'));

const sinceTick = () => events.splice(0, events.length);
const printUrl = (id) => `/kiosk/1/escarapela/imprimir/${id}`;
const rows = () => els.tbody.children.filter((tr) => !/directory-(local-note|more)/.test(tr.className));
const rowByName = (name) => rows().find((tr) => tr.children[2].innerText === name);
const actionBtn = (tr) => tr.children[0].children.find((b) => /btn-accredit-row/.test(b.className));
const ok = (id, extra = {}) => (fd) => Object.assign({ result: 'SÍ', data: { id: fd.get('cedula'), first_name: 'Ana', last_name: 'Pérez' } }, extra);

(async () => {
  const d = window.GoldenDirectory.mountSearch({ tbodyId: 'tbody', searchIds: { cedula: 'cedula', nombre: 'nombre', entidad: 'entidad' }, fastCheckin: true });
  await d.reload(); await advance(10);
  assert.strictEqual(window.EVENT_AUTO_PRINT, false, 'punto de partida: la página cree que la autoimpresión está apagada');

  // ---- A: el servidor dice auto_print:true aunque la página tenga false → imprime sin recargar
  changesFlags = { auto_print: true, auto_register: true };            // el coordinador encendió los interruptores con esta pantalla ya abierta
  sinceTick(); checkinReply = ok('1001', { auto_print: true, auto_register: true });
  await d.submitScannedCedula('1001', null); await advance(10);
  assert.ok(events.includes('open:' + printUrl('1001')) || events.some((e) => e === 'nav:' + printUrl('1001')), 'imprimió según la respuesta del servidor: ' + events.join(' | '));
  assert.strictEqual(window.EVENT_AUTO_PRINT, true, 'y la bandera de la página se puso al día');
  assert.strictEqual(window.EVENT_AUTO_REGISTER, true);

  // ---- A (al revés): la página cree que sí, el servidor dice que no → no imprime
  changesFlags = { auto_print: false, auto_register: true };
  sinceTick(); checkinReply = ok('1002', { auto_print: false, auto_register: true });
  await d.submitScannedCedula('1002', null); await advance(10);
  assert.ok(!events.some((e) => /imprimir/.test(e)), 'el servidor dijo auto_print:false: no se imprime: ' + events.join(' | '));
  assert.ok(!wins.some((w) => !w.closed && w.url === 'about:blank'), 'y no queda una ventana en blanco abierta');
  assert.strictEqual(window.EVENT_AUTO_PRINT, false);

  // ---- C: con la bandera al día (true) la ventana se abre ANTES de la primera llamada de red, dentro del gesto, y luego se navega a la impresión
  window.EVENT_AUTO_PRINT = true; window.EVENT_AUTO_REGISTER = true; changesFlags = { auto_print: true, auto_register: true };
  window.BadgePrint.releaseClaim('1001');                              // (1001 ya imprimió arriba dentro de los 30 s)
  sinceTick(); wins.length = 0; checkinReply = ok('1001', { auto_print: true, auto_register: true });
  await d.submitScannedCedula('1001', null); await advance(10);
  const iOpen = events.indexOf('open:about:blank'), iNet = events.indexOf('fetch:/api/checkin-cedula');
  assert.ok(iOpen >= 0 && iNet > iOpen, 'ventana abierta antes de la llamada de red: ' + events.join(' | '));
  assert.strictEqual(wins.length, 1, 'una sola ventana'); assert.strictEqual(wins[0].name, 'goldenweb_print', 'nombre fijo goldenweb_print');
  assert.strictEqual(wins[0]._href, printUrl('1001'), 'la misma ventana se navega a la página de impresión');
  assert.ok(!events.includes('open:' + printUrl('1001')), 'no se abrió una segunda ventana');
  assert.ok(!wins[0].closed, 'y no se cerró');

  // ---- C: el check-in no termina en impresión (autorregistro apagado → FOUND_PENDING): la ventana en blanco se cierra
  window.EVENT_AUTO_REGISTER = undefined; changesFlags = { auto_print: true, auto_register: false };                             // un digitador no sabe todavía: se prepara la ventana
  sinceTick(); wins.length = 0; checkinReply = (fd) => ({ result: 'FOUND_PENDING', data: { id: fd.get('cedula'), first_name: 'Luis', last_name: 'Gómez' }, auto_print: true, auto_register: false });
  await d.submitScannedCedula('1002', null); await advance(10);
  assert.ok(wins.length === 1 && wins[0].closed, 'sin impresión la ventana preparada se cierra: ' + events.join(' | '));
  assert.strictEqual(window.EVENT_AUTO_REGISTER, false, 'y se aprendió que el autorregistro está apagado');
  // con el autorregistro conocido-apagado y sin confirmar, ni siquiera se abre
  sinceTick(); wins.length = 0;
  await d.submitScannedCedula('1002', null); await advance(10);
  assert.ok(!events.some((e) => /^open:/.test(e)), 'no se abre ventana si no se va a acreditar: ' + events.join(' | '));

  // ---- B/T5: «✅ Acreditar» → «Deshacer» → volver a acreditar a la misma persona dentro de 30 s SÍ imprime
  window.EVENT_AUTO_PRINT = true; window.EVENT_AUTO_REGISTER = true;
  checkinReply = (fd) => ({ result: 'SÍ', data: { id: fd.get('cedula'), first_name: 'Luis', last_name: 'Gómez' }, auto_print: true, auto_register: true });
  await d.reload(); await advance(10);
  sinceTick(); wins.length = 0;
  await actionBtn(rowByName('Luis')).listeners.click(); await advance(10);
  const printsOf = (id) => events.filter((e) => e === 'nav:' + printUrl(id) || e === 'open:' + printUrl(id)).length;
  assert.strictEqual(printsOf('1002'), 1, 'primera acreditación imprime: ' + events.join(' | '));
  const undoToast = toasts.filter((t) => t.o && t.o.action).pop(); assert.ok(undoToast, 'ofrece Deshacer');
  undoReply = { status: 200, body: { undone: true, user_id: '1002', auto_print: true, auto_register: true } };
  undoToast.o.action.onClick(); await until(() => /deshecha/.test((toasts[toasts.length - 1] || {}).m || ''), 'aviso de deshacer'); await advance(10);
  sinceTick(); wins.length = 0;
  await d.reload(); await advance(10);
  await actionBtn(rowByName('Luis')).listeners.click(); await advance(10);
  assert.strictEqual(printsOf('1002'), 1, 'tras «Deshacer» la misma persona vuelve a imprimirse sola (no queda bloqueada 30 s): ' + events.join(' | '));
  // sin «Deshacer», una segunda automática de la misma persona dentro de la ventana no se repite (el candado se confirmó tras el éxito)
  sinceTick(); wins.length = 0;
  await d.submitScannedCedula('1002', null); await advance(10);
  assert.strictEqual(printsOf('1002'), 0, 'dentro de los 30 s no se repite: ' + events.join(' | '));

  // ---- B: ventanas emergentes bloqueadas (window.open → null): no se gasta el candado; al permitirlas el reintento imprime
  window.BadgePrint.releaseClaim('1001'); blockPopups = true; sinceTick(); wins.length = 0; checkinReply = ok('1001', { auto_print: true, auto_register: true });
  await d.submitScannedCedula('1001', null); await advance(10);
  assert.strictEqual(wins.length, 0, 'bloqueada: no hay ventana (el intento sí se hizo: ' + events.filter((e) => /^open:/.test(e)).join(',') + ')');
  blockPopups = false; sinceTick();
  await d.submitScannedCedula('1001', null); await advance(10);
  assert.strictEqual(printsOf('1001'), 1, 'con la ventana permitida el reintento imprime (el bloqueo no gastó el candado): ' + events.join(' | '));

  // ---- E: cada sondeo deja la bandera de autorregistro en la copia local (ya no vale la de la descarga de hace minutos)
  rosterAuto = false;
  const GC = C.create({ idb: fakeIndexedDB(), fetch: global.fetch, now: () => now, document: global.document, subtle: crypto.subtle, eventId: 1, uuid: () => 'u', setInterval: () => 1, clearInterval() {}, setTimeout: global.setTimeout, clearTimeout: global.clearTimeout });
  await GC.start(); await flush(); await flush(); window.GoldenContingency = { instance: GC };
  assert.strictEqual(await GC.autoRegister(), false, 'la copia se descargó con el autorregistro apagado');
  changesFlags = { auto_print: true, auto_register: true };            // el coordinador lo encendió después de la descarga
  await d.reload(); await advance(10); await flush();
  assert.strictEqual(await GC.autoRegister(), true, 'el sondeo puso al día la bandera local (causa E)');
  changesFlags = { auto_print: true, auto_register: false };
  await d.reload(); await advance(10); await flush();
  assert.strictEqual(await GC.autoRegister(), false, 'y también al apagarlo');
  delete window.GoldenContingency;

  // ---- F: la plantilla ya no contradice el botón de «Registrar nuevo» sin red
  const tpl = fs.readFileSync('templates/kiosk_registro.html', 'utf8');
  const fn = tpl.slice(tpl.indexOf('function openRegisterModal()'), tpl.indexOf('function closeRegisterModal()'));
  assert.ok(fn.includes("registerModal.style.display = 'flex'"), 'abre el modal');
  assert.ok(!/active\(\)/.test(fn) && !/Sin conexión: no se pueden registrar/.test(fn), 'sin guardia de contingencia en openRegisterModal (causa F):\n' + fn);
  assert.ok(/openRegisterModalBtn\.disabled = \(off && !canQueue\)/.test(tpl), 'el habilitado del botón sigue decidido por la bandeja de salida');
  assert.ok(/addEventListener\('gw:flags'/.test(tpl), 'los interruptores del coordinador se repintan con las banderas del servidor');

  // ---- toda llamada de la puerta pasa la respuesta del servidor (solo el escáner facial, sin banderas, usa la de la página)
  const callsOf = (file) => (fs.readFileSync(file, 'utf8').match(/BadgePrint\.maybeAutoPrint\([^)]*\)/g) || []);
  const dir = callsOf('static/js/directory.js'), app = callsOf('static/js/app.js');
  assert.ok(dir.length === 4 && dir.every((c) => /auto:/.test(c)), 'directory.js: ' + dir.join(' ; '));          // 4.º: offlineAutoPrint (sin red no hay respuesta del servidor: vale la bandera de la página, docs/28)
  assert.deepStrictEqual(app.filter((c) => !/auto:/.test(c)), ['BadgePrint.maybeAutoPrint(userId)'], 'app.js: solo offerPrint (facial) sin respuesta de banderas: ' + app.join(' ; '));
  console.log('autoprint_flow OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
