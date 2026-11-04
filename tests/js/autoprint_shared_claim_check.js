// PR3 (4a, causa B y T4/T5 de docs/etapa/0A) con la impresión compartida ENCENDIDA y el badge-render.js REAL como despachador de base: el candado de 30 s de la autoimpresión se confirma
// DESPUÉS del éxito. Si «¿está registrado?» falla, el envío no sale o la ventana se bloquea, el candado se suelta y el reintento imprime. La bandera de la página (EVENT_AUTO_PRINT, congelada
// al cargar) ya no decide: manda `opts.auto` de la respuesta del servidor. Correr: node tests/js/autoprint_shared_claim_check.js
const fs = require('fs');
const path = require('path');
const assert = require('assert');

/* ---------------------------------------------------------------- DOM mínimo con captura y burbujeo */
const docListeners = { capture: {}, bubble: {} };
class El {
  constructor(tag, id) { this.tagName = tag; this.id = id || ''; this.children = []; this.style = {}; this.dataset = {}; this.attrs = {}; this.listeners = {}; this.value = ''; this.hidden = false; this.textContent = ''; this.className = ''; this.offsetParent = {}; this.parentNode = null; this._sel = {}; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  prepend(c) { c.parentNode = this; this.children.unshift(c); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
  querySelector(sel) { return this._sel[sel] || (this._sel[sel] = new El('x', sel.replace('#', ''))); }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return { width: 234, height: 378, left: 0, top: 0 }; }
  closest() { return null; }
  focus() { document.activeElement = this; }
  blur() { this.blurred = true; document.activeElement = document.body; }
  setSelectionRange(a) { this.selectionStart = this.selectionEnd = a; }
  get classList() { const self = this; return { toggle(c, on) { self.className = on ? c : ''; }, contains(c) { return self.className === c; } }; }
  set innerHTML(v) { this._html = v; }
  get innerHTML() { return this._html; }
  getContext() { return { fillRect() {}, strokeRect() {}, fillText() {}, drawImage() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(w * h * 4).fill(255) }) }; }
  dispatchEvent(ev) {
    ev.target = this;
    for (const f of docListeners.capture[ev.type] || []) { f(ev); if (ev._stopped) return !ev.defaultPrevented; }
    for (const f of this.listeners[ev.type] || []) { f(ev); if (ev._stopped) return !ev.defaultPrevented; }
    if (ev.bubbles) for (const f of docListeners.bubble[ev.type] || []) f(ev);
    return !ev.defaultPrevented;
  }
}
class Ev {
  constructor(type, init = {}) { Object.assign(this, { bubbles: false, cancelable: false }, init); this.type = type; this.defaultPrevented = false; }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this._stopped = true; }
  stopImmediatePropagation() { this._stopped = true; }
}
global.Event = Ev;
global.KeyboardEvent = Ev;
const els = {};
for (const id of ['searchCedula', 'searchNombre', 'searchEntidad', 'regScanCedulaInput', 'manualIdField']) els[id] = new El('input', id);
const body = new El('body');
global.document = {
  readyState: 'complete', visibilityState: 'visible', activeElement: null, body, head: new El('head'),
  createElement: (t) => new El(t), getElementById: (id) => els[id] || null, querySelector: () => null,
  querySelectorAll: (sel) => (els[sel.replace('#', '')] ? [els[sel.replace('#', '')]] : []),
  addEventListener: (k, f, capture) => { const m = capture ? docListeners.capture : docListeners.bubble; (m[k] = m[k] || []).push(f); },
};

/* ---------------------------------------------------------------- red, impresora y avisos falsos */
const mem = { d: {}, getItem(k) { return k in this.d ? this.d[k] : null; }, setItem(k, v) { this.d[k] = String(v); }, removeItem(k) { delete this.d[k]; } };
const toasts = [];
const original = { open: [], auto: [] };
global.window = global;
const pageListeners = {};
global.addEventListener = (k, f) => { (pageListeners[k] = pageListeners[k] || []).push(f); };       // eventos de la página (online / offline / gw:session-replaced)
global.dispatchEvent = (ev) => { (pageListeners[ev.type] || []).forEach((f) => f(ev)); return true; };
const sharedCalls = [], beats = [];
Object.assign(global, {
  EVENT_ID: 7, EVENT_AUTO_PRINT: false, STAFF_ROLE: 'digitador', localStorage: mem, SHARED_PRINT_ENABLED: !process.env.SHARED_OFF,
  __me: process.env.STATION ? { admin: false, station: true, settings: Object.assign({ readerOnly: false, mode: 'driver', pageWidthMm: 60, rotation: 90 }, process.env.STATION === 'show' ? {} : { showConfig: false }) } : null,
  showToast: (m, t) => { toasts.push({ m, t }); }, showConfirm: async () => true,
});
const fakeUsb = process.env.NOWEBUSB ? undefined : { addEventListener() {}, getDevices: async () => [] };
Object.defineProperty(global, 'navigator', { configurable: true, value: { usb: fakeUsb, userAgent: process.env.MOBILE ? 'Mozilla/5.0 (Linux; Android 14) Chrome/130 Mobile' : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130' } });
const REGISTERED = new Set(['1001']);
let mode = 'self';
const jobs = [];
const reqIds = [];
let flaky = false;
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
global.fetch = async (url, init = {}) => {
  const u = new URL(url, 'http://x');
  if (u.pathname.endsWith('/print-station/me')) return json(200, global.__me || { admin: false, station: false, settings: null });
  if (process.env.SHARED_OFF && /print-devices|print-jobs|print-check/.test(u.pathname)) { sharedCalls.push(u.pathname); return json(409, { detail: 'La impresión compartida está desactivada' }); }
  if (u.pathname.endsWith('/print-devices/heartbeat')) { try { beats.push(JSON.parse(init.body)); } catch (e) { /* sin cuerpo */ } }
  if (u.pathname.endsWith('/print-devices/heartbeat')) return json(200, Object.assign({ enabled: true, mode, printer_name: mode === 'shared' ? 'dig1' : '', printer_ready: true, serving: 0, poll: false }, global.__hb || {}));
  let m = u.pathname.match(/\/print-check\/(.+)$/);
  if (m) return json(200, REGISTERED.has(m[1]) ? { registered: true } : { registered: false, detail: `No se puede imprimir: Persona ${m[1]} aún no está registrado. Acredítalo o guarda su registro primero.` });
  if (u.pathname.endsWith('/print-jobs') && init.method === 'POST') { const b = JSON.parse(init.body); reqIds.push(b.request_id); if (flaky && reqIds.length === 1) throw new TypeError('Failed to fetch'); jobs.push(b.user_id); return json(200, { id: jobs.length, status: 'queued', printer_name: 'dig1', printer_ready: true }); }
  if (/\/print-jobs\/\d+$/.test(u.pathname)) return json(200, { status: 'printed', printer_name: 'dig1' });
  if (u.pathname.endsWith('/print-count')) return json(200, { times_printed: 0 });
  if (u.pathname.endsWith('/print-log')) return json(200, {});
  throw new Error('ruta inesperada ' + u.pathname);
};
global.QLUsb = require(path.resolve(__dirname, '../../static/js/ql-usb.js'));
global.LabelCompose = require(path.resolve(__dirname, '../../static/js/label-compose.js'));
QLUsb.connect = async () => null;                                  // este equipo no tiene impresora USB: imprime con la ventana de siempre
const opened = [], names = [];
let blockWindows = false;
window.open = (url, name) => { names.push(name); if (blockWindows) return null; const w = { closed: false, close() { this.closed = true; }, location: { set href(v) { opened.push(v); } } }; if (url !== 'about:blank') opened.push(url); return w; };
eval(fs.readFileSync(path.resolve(__dirname, '../../static/js/badge-render.js'), 'utf8'));
eval(fs.readFileSync(path.resolve(__dirname, '../../static/js/shared-print.js'), 'utf8'));
const settle = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const lastToast = () => (toasts[toasts.length - 1] || {});
const printed = () => opened.filter((u) => /escarapela\/imprimir/.test(u)).length;

(async () => {
  await settle(200);
  const BP = window.BadgePrint;
  // 0) la bandera de la página está APAGADA (congelada al cargar) pero el servidor dice auto_print:true → imprime (causa A)
  assert.strictEqual(window.EVENT_AUTO_PRINT, false);
  await BP.maybeAutoPrint('1001', { auto: true }); await settle();
  assert.strictEqual(printed(), 1, 'imprime según la respuesta del servidor, no según la página: ' + JSON.stringify(opened));
  assert.strictEqual(window.EVENT_AUTO_PRINT, true, 'la bandera de la página se pone al día con la del servidor');
  // el servidor dice que NO (aunque la página creyera que sí)
  await BP.maybeAutoPrint('1001', { auto: false }); await settle();
  assert.strictEqual(printed(), 1); assert.strictEqual(window.EVENT_AUTO_PRINT, false);

  // 1) T4: «¿registrado?» falla por la red (2 intentos) → NO imprime, el candado NO se gasta, y el reintento a los pocos segundos imprime
  REGISTERED.add('1005');
  const realFetch = global.fetch; let failChecks = true;
  global.fetch = async (url, init) => { if (failChecks && /print-check/.test(url)) throw new TypeError('Failed to fetch'); return realFetch(url, init); };
  const before = printed();
  await BP.maybeAutoPrint('1005', { auto: true }); await settle(900);
  assert.strictEqual(printed(), before, 'sin poder comprobar, no se imprime'); assert.ok(toasts.some((t) => /no se pudo comprobar/.test(t.m)), JSON.stringify(toasts));
  failChecks = false;
  await BP.maybeAutoPrint('1005', { auto: true }); await settle(100);
  assert.strictEqual(printed(), before + 1, 'el reintento automático inmediato SÍ imprime (T4): el candado no se gastó');
  // y ya impresa, otra automática en la ventana de 30 s no se repite (el candado se confirmó tras el éxito)
  await BP.maybeAutoPrint('1005', { auto: true }); await settle();
  assert.strictEqual(printed(), before + 1, 'tras el éxito el candado queda firme 30 s');
  // «Deshacer»: releaseClaim → la misma persona vuelve a imprimirse sola (T5)
  BP.releaseClaim('1005');
  await BP.maybeAutoPrint('1005', { auto: true }); await settle(100);
  assert.strictEqual(printed(), before + 2, 'tras «Deshacer» imprime otra vez (T5)');

  // 2) ventana bloqueada por el navegador (window.open devuelve null): no se gasta el candado; al permitirla, el reintento imprime
  blockWindows = true;
  const b2 = printed();
  await BP.maybeAutoPrint('2002', { auto: true }); await settle(100);
  assert.strictEqual(printed(), b2);
  blockWindows = false;
  REGISTERED.add('2002');
  await BP.maybeAutoPrint('2002', { auto: true }); await settle(100);
  assert.strictEqual(printed(), b2 + 1, 'con la ventana permitida el reintento imprime');

  // 3) ruta COMPARTIDA (manda a otro equipo): si el envío falla el candado se suelta; si sale, queda firme
  mode = 'shared'; await GoldenSharedPrint.connectForTest(false); await settle();
  REGISTERED.add('3003');
  const sendFail = global.fetch; let failJobs = true;
  global.fetch = async (url, init = {}) => { if (failJobs && /print-jobs$/.test(new URL(url, 'http://x').pathname) && init.method === 'POST') throw new TypeError('Failed to fetch'); return sendFail(url, init); };
  jobs.length = 0;
  await BP.maybeAutoPrint('3003', { auto: true }); await settle(2200);
  assert.strictEqual(jobs.length, 0, 'el envío falló: no hay trabajo');
  failJobs = false;
  await BP.maybeAutoPrint('3003', { auto: true }); await settle(200);
  assert.deepStrictEqual(jobs, ['3003'], 'el reintento inmediato SÍ crea el trabajo (el candado se soltó)');
  await BP.maybeAutoPrint('3003', { auto: true }); await settle(100);
  assert.deepStrictEqual(jobs, ['3003'], 'ya enviado: no se duplica dentro de los 30 s');
  assert.ok(names.every((n) => n === 'goldenweb_print'), 'siempre la ventana de nombre fijo: ' + names.join(','));
  console.log('autoprint_shared_claim OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
