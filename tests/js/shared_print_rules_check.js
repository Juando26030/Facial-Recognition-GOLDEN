// Reglas de la pantalla de Registro con la impresión compartida ENCENDIDA (orden del 22-oct-2026), con DOM, red e impresora falsos. Correr: node tests/js/shared_print_rules_check.js
//  1) Solo se imprime a quien está «Registrado»: botón, autoimpresión y Cola; en su propio equipo y en el de otro.
//  2) Enter del teclado en pantalla = buscar (beforeinput / keyup cuando el teclado no manda la tecla), sin repetir el Enter del lector USB.
//  3) Pegar en cédula: Ctrl+V pasa el blindaje del lector y se limpian espacios y puntos.
//  4) Preferencias del equipo (corte, margen) en la etiqueta que se manda por USB.
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
const pageListeners = {};
global.addEventListener = (k, f) => { (pageListeners[k] = pageListeners[k] || []).push(f); };       // pagehide / beforeunload de la página
global.window = global;
Object.assign(global, {
  EVENT_ID: 7, EVENT_AUTO_PRINT: true, STAFF_ROLE: 'digitador', localStorage: mem,
  showToast: (m, t) => { toasts.push({ m, t }); }, showConfirm: async () => true,
  BadgePrint: { openPrintWindow: (id) => { original.open.push(id); }, maybeAutoPrint: (id) => { original.auto.push(id); } },
});
Object.defineProperty(global, 'navigator', { configurable: true, value: { userAgent: 'Mozilla/5.0 (Linux; Android 14) Chrome/130', usb: { addEventListener() {}, getDevices: async () => [] } } });
const REGISTERED = new Set(['1001']);
let mode = 'self';
const jobs = [];
const reqIds = [];
let flaky = false;
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
global.fetch = async (url, init = {}) => {
  const u = new URL(url, 'http://x');
  if (u.pathname.endsWith('/print-devices/heartbeat')) return json(200, { enabled: true, mode, printer_name: mode === 'shared' ? 'dig1' : '', printer_ready: true, serving: 0, poll: false });
  let m = u.pathname.match(/\/print-check\/(.+)$/);
  if (m) return json(200, REGISTERED.has(m[1]) ? { registered: true } : { registered: false, detail: `No se puede imprimir: Persona ${m[1]} aún no está registrado. Acredítalo o guarda su registro primero.` });
  if (u.pathname.endsWith('/print-jobs') && init.method === 'POST') { const b = JSON.parse(init.body); reqIds.push(b.request_id); if (flaky && reqIds.length === 1) throw new TypeError('Failed to fetch'); jobs.push(b.user_id); return json(200, { id: jobs.length, status: 'queued', printer_name: 'dig1', printer_ready: true }); }
  if (/\/print-jobs\/\d+$/.test(u.pathname)) return json(200, { status: 'printed', printer_name: 'dig1' });
  if (u.pathname.endsWith('/print-count')) return json(200, { times_printed: 0 });
  if (u.pathname.endsWith('/print-log')) return json(200, {});
  throw new Error('ruta inesperada ' + u.pathname);
};
global.QLUsb = require(path.resolve(__dirname, '../../static/js/ql-usb.js'));
QLUsb.connect = async () => null;                                  // este equipo no tiene impresora USB: imprime con la ventana de siempre
eval(fs.readFileSync(path.resolve(__dirname, '../../static/js/shared-print.js'), 'utf8'));
const settle = () => new Promise((r) => setTimeout(r, 30));
const lastToast = () => (toasts[toasts.length - 1] || {});

(async () => {
  await settle();
  const BP = window.BadgePrint;

  // ---- 1a) en su propio equipo: el botón y la autoimpresión NO imprimen a quien no está Registrado (aviso claro); sí a quien lo está
  await BP.openPrintWindow('1003');
  assert.deepStrictEqual(original.open, [], 'no abre la impresión');
  assert.ok(/No se puede imprimir: .*1003 aún no está registrado\. Acredítalo o guarda su registro primero\./.test(lastToast().m) && lastToast().t === 'error', lastToast().m);
  await BP.openPrintWindow('1001');
  assert.deepStrictEqual(original.open, ['1001']);
  BP.maybeAutoPrint('1003'); await settle();
  assert.deepStrictEqual(original.auto, [], 'la autoimpresión no dispara sin Registrado');
  BP.maybeAutoPrint('1001'); await settle();
  assert.deepStrictEqual(original.auto, ['1001']);
  window.EVENT_AUTO_PRINT = false; BP.maybeAutoPrint('1001'); await settle(); window.EVENT_AUTO_PRINT = true;
  assert.deepStrictEqual(original.auto, ['1001'], 'sin autoimpresión encendida no se imprime solo');

  // ---- 1b) en el equipo de otro (compartida): no se crea trabajo para quien no está Registrado; sí para quien lo está (y «Impreso en dig1»). La Cola igual.
  mode = 'shared';
  document.listeners = null; for (const f of docListeners.bubble.visibilitychange || []) f(new Ev('visibilitychange')); await settle();
  assert.strictEqual(GoldenSharedPrint.state().route.mode, 'shared');
  await BP.openPrintWindow('1003');
  BP.maybeAutoPrint('1003'); await settle();
  await GoldenSharedPrint.printFor('1003', false, true);               // «Reimprimir» desde la Cola
  assert.deepStrictEqual(jobs, [], 'ningún trabajo para quien no está Registrado');
  // 4) «cédula exacta + Enter» acredita y llama a la autoimpresión: con la persona ya Registrada, el MISMO despachador crea el trabajo compartido
  REGISTERED.add('1002');
  BP.maybeAutoPrint('1002');
  await new Promise((r) => setTimeout(r, 1300));
  assert.deepStrictEqual(jobs, ['1002']);
  assert.ok(toasts.some((t) => t.m === '✅ Impreso en dig1.'), 'X ve «Impreso en dig1»');
  // red intermitente: el primer pedido se pierde y se reintenta con el MISMO request_id (el servidor lo deduplica): un solo trabajo
  REGISTERED.add('1009'); flaky = true; reqIds.length = 0; jobs.length = 0;
  await GoldenSharedPrint.printFor('1009', false, true);
  flaky = false;
  assert.strictEqual(reqIds.length, 2, 'se reintentó una vez');
  assert.strictEqual(reqIds[0], reqIds[1], 'con el mismo identificador de solicitud');
  assert.deepStrictEqual(jobs, ['1009'], 'y se creó un solo trabajo');
  mode = 'self'; for (const f of docListeners.bubble.visibilitychange || []) f(new Ev('visibilitychange')); await settle();

  // ---- 2) Enter del teclado en pantalla
  const ced = els.searchCedula;
  const enters = [];
  ced.addEventListener('keydown', (e) => { if (e.key === 'Enter') enters.push(e); });          // lo que hace directory.js: buscar con Enter
  assert.strictEqual(ced.getAttribute('enterkeyhint'), 'search', 'la tecla del teclado dice «Buscar»');
  const bi = new Ev('beforeinput', { inputType: 'insertLineBreak', cancelable: true });
  ced.dispatchEvent(bi);
  assert.strictEqual(enters.length, 1, 'el salto de línea del teclado (keyCode 229) se convierte en Enter');
  assert.ok(bi.defaultPrevented);
  ced.dispatchEvent(new Ev('keyup', { key: 'Enter', keyCode: 13 }));
  assert.strictEqual(enters.length, 1, 'y no se repite al soltar');
  await new Promise((r) => setTimeout(r, 1100));
  ced.dispatchEvent(new Ev('keydown', { key: 'Unidentified', keyCode: 229 }));                  // teclado que solo manda el Enter al soltar
  ced.dispatchEvent(new Ev('keyup', { key: 'Enter', keyCode: 13 }));
  assert.strictEqual(enters.length, 2, 'Enter al soltar (sin keydown Enter) también busca');
  await new Promise((r) => setTimeout(r, 1100));
  ced.dispatchEvent(new Ev('keydown', { key: 'Enter', keyCode: 13 }));                           // lector USB: Enter normal
  ced.dispatchEvent(new Ev('keyup', { key: 'Enter', keyCode: 13 }));
  assert.strictEqual(enters.length, 3, 'el lector USB busca una sola vez');
  const nom = els.searchNombre;
  let inputs = 0;
  nom.addEventListener('input', () => { inputs++; });
  const kd = new Ev('keydown', { key: 'Enter', keyCode: 13, cancelable: true });
  nom.dispatchEvent(kd);
  assert.ok(kd.defaultPrevented && inputs === 1 && nom.blurred, 'en nombre, Enter busca (no pasa al campo siguiente) y baja el teclado');
  assert.strictEqual(els.searchEntidad.getAttribute('enterkeyhint'), 'search');

  // ---- 3) pegar en cédula
  let guard = 0;
  ced.addEventListener('keydown', (e) => { if (e.ctrlKey) { guard++; e.preventDefault(); } });     // el blindaje de directory.js contra atajos del lector
  const cv = new Ev('keydown', { key: 'v', ctrlKey: true, cancelable: true });
  ced.dispatchEvent(cv);
  assert.ok(guard === 0 && !cv.defaultPrevented, 'Ctrl+V pasa');
  ced.dispatchEvent(new Ev('keydown', { key: 'j', ctrlKey: true, cancelable: true }));
  assert.strictEqual(guard, 1, 'otros atajos siguen bloqueados');
  ced.value = ''; ced.selectionStart = ced.selectionEnd = 0;
  const pe = new Ev('paste', { cancelable: true, clipboardData: { getData: () => ' 1.023. 456 789 ' } });
  ced.dispatchEvent(pe);
  assert.ok(pe.defaultPrevented && ced.value === '1023456789', ced.value);
  assert.strictEqual(GoldenSharedPrint.cleanCedula('79.123.456'), '79123456');

  // ---- 4) preferencias del equipo en la etiqueta USB: corte cada etiqueta y margen 1,5 mm por defecto; se respetan si se cambian
  const has = (job, bytes) => Array.from(job).join(',').includes(bytes.join(','));
  let job = GoldenSharedPrint.testJob();
  assert.ok(has(job, [0x1b, 0x69, 0x4d, 0x40]) && has(job, [0x1b, 0x69, 0x41, 0x01]) && has(job, [0x1b, 0x69, 0x64, 18, 0]), 'corte automático y margen de 18 puntos por defecto');
  QLUsb.savePrefs(mem, { cut: false, feedMm: 3 });
  job = GoldenSharedPrint.testJob();
  assert.ok(has(job, [0x1b, 0x69, 0x4d, 0x00]) && !has(job, [0x1b, 0x69, 0x41, 0x01]) && has(job, [0x1b, 0x69, 0x64, 35, 0]), 'sin corte y margen de 3 mm');
  QLUsb.savePrefs(mem, { cut: true, feedMm: 1.5, lengthMm: 50, crop: false });          // alto fijo manual: sin recorte al contenido
  job = GoldenSharedPrint.testJob();
  const lines = QLUsb.mmToDots(50);
  assert.ok(has(job, [0x1b, 0x69, 0x7a, 0x86, 0x0a, 62, 0, lines & 255, lines >> 8]), 'alto fijo de 50 mm');

  // ---- 5) impresión compartida con los parámetros del equipo QUE PIDE (24-oct-2026): X manda los suyos ya resueltos; Y imprime con esos, no con los propios
  const bodies = [];
  const realFetch = global.fetch;
  global.fetch = async (url, init = {}) => { if (String(url).endsWith('/print-jobs') && init.method === 'POST') bodies.push(JSON.parse(init.body)); return realFetch(url, init); };
  QLUsb.clearPrefs(mem);
  QLUsb.savePrefs(mem, { cut: false, feedMm: 4, mirror: true, rotation: 270 });                 // los de ESTE equipo (X)
  mode = 'shared'; for (const f of docListeners.bubble.visibilitychange || []) f(new Ev('visibilitychange')); await settle();
  REGISTERED.add('1010');
  await GoldenSharedPrint.printFor('1010', false, true);
  const sent = bodies[bodies.length - 1];
  assert.ok(sent && sent.prefs, 'el pedido lleva los parámetros');
  assert.strictEqual(sent.prefs.cut, false); assert.strictEqual(sent.prefs.feedMm, 4); assert.strictEqual(sent.prefs.mirror, true); assert.strictEqual(sent.prefs.rotation, 270);
  BP.maybeAutoPrint('1010'); await new Promise((r) => setTimeout(r, 40));                       // la autoimpresión pasa por el mismo despachador: también los lleva
  assert.ok(bodies.every((b) => b.prefs && b.prefs.feedMm === 4), 'autoimpresión y Cola con los mismos parámetros');
  global.fetch = realFetch;
  // Y (este mismo código en el equipo con la impresora) con OTROS valores locales: el pedido manda
  QLUsb.clearPrefs(mem); QLUsb.savePrefs(mem, { cut: true, feedMm: 1, mirror: false, rotation: 90 });
  let r = GoldenSharedPrint.prefsForJob({ prefs: sent.prefs });
  assert.strictEqual(r.prefs.cut, false); assert.strictEqual(r.prefs.feedMm, 4); assert.strictEqual(r.prefs.mirror, true); assert.strictEqual(r.prefs.rotation, 270);
  assert.ok(/el equipo que la pidió/.test(QLUsb.describePrefs(r.prefs, r.source)), QLUsb.describePrefs(r.prefs, r.source));
  // pedido viejo en cola (sin parámetros): los del EVENTO, nunca los locales de Y
  r = GoldenSharedPrint.prefsForJob({ id: 1, user_id: '1001' });
  assert.strictEqual(r.prefs.feedMm, 1.5); assert.strictEqual(r.prefs.cut, true); assert.strictEqual(r.prefs.rotation, 'auto');
  assert.ok(!Object.values(r.source).includes('equipo'), 'no usa nada de este equipo');
  const src = fs.readFileSync(path.resolve(__dirname, '../../static/js/shared-print.js'), 'utf8');
  assert.ok(src.includes('printUsb(job.user_id, prefsForJob(job))'), 'Y imprime cada pedido con prefsForJob');
  mode = 'self'; QLUsb.clearPrefs(mem);

  // ---- 6) la impresora la tiene OTRA pestaña de este navegador (25-oct-2026): el estado sale «conectada» (se imprime a través de ella) y el latido lo anuncia; si Chrome dice «Access denied», se explica qué hacer
  const beats = [];
  const f0 = global.fetch;
  global.fetch = async (url, init = {}) => { if (String(url).endsWith('/print-devices/heartbeat')) beats.push(JSON.parse(init.body)); return f0(url, init); };
  const realConnect = QLUsb.connect, realOwner = QLUsb.remoteOwner;
  const busy = Object.assign(new Error(QLUsb.BUSY_MSG), { busy: true, code: 'busy', friendly: true });
  QLUsb.connect = async () => { throw busy; };
  QLUsb.remoteOwner = async () => ({ name: 'QL-800', here: false });
  mode = 'self'; beats.length = 0;
  for (const f of docListeners.bubble.visibilitychange || []) f(new Ev('visibilitychange'));
  await settle();
  let st = GoldenSharedPrint.state();
  assert.ok(st.usb.ok && st.usb.viaTab && st.usb.name === 'QL-800' && !st.usb.busy, 'conectada a través de la otra pestaña');
  assert.ok(beats.length && beats[beats.length - 1].printer_connected === true && beats[beats.length - 1].printer_name === 'QL-800', 'el latido anuncia la impresora (se imprime a través de la pestaña dueña)');
  // «Conectar» con la impresora ya conectada: «Ya conectada», sin intentar abrirla otra vez
  let calls = 0; QLUsb.connect = async () => { calls++; throw busy; };
  toasts.length = 0; await GoldenSharedPrint.connectUsb(true);
  assert.strictEqual(calls, 0, 'no se vuelve a abrir'); assert.ok(toasts.some((t) => /ya está conectada/.test(t.m)), 'dice «ya está conectada»');
  // nadie la tiene y Chrome dice «Access denied»: mensaje claro, estado desconectado y reintento posible
  QLUsb.remoteOwner = async () => null;
  const denied = Object.assign(new Error("Failed to execute 'open' on 'USBDevice': Access denied."), { name: 'SecurityError' });
  QLUsb.connect = async () => { throw QLUsb.friendlyError(denied); };
  await GoldenSharedPrint.disconnectForTest();
  toasts.length = 0; await GoldenSharedPrint.connectUsb(true);
  st = GoldenSharedPrint.state();
  assert.ok(!st.usb.ok && st.usb.code === 'denied' && /Cierra otras pestañas o programas de Brother/.test(st.usb.lastError), st.usb.lastError);
  assert.ok(toasts.some((t) => t.t === 'error' && /Cierra otras pestañas o programas de Brother/.test(t.m)), 'el aviso trae la acción a seguir');
  // dos toques a la vez: un solo intento
  const realReady = QLUsb.ready; QLUsb.ready = () => true;
  calls = 0; QLUsb.connect = async () => { calls++; await new Promise((r) => setTimeout(r, 20)); return { productName: 'QL-800' }; };
  await Promise.all([GoldenSharedPrint.connectUsb(false), GoldenSharedPrint.connectUsb(true), GoldenSharedPrint.connectUsb(true)]);
  assert.strictEqual(calls, 1, 'un solo intento de conexión aunque lo pidan tres veces');
  // al cerrar o recargar la página se suelta la impresora
  let released = 0; QLUsb.releaseNow = () => { released++; };
  for (const ev of ['pagehide', 'beforeunload']) (pageListeners[ev] || []).forEach((f) => f());
  assert.strictEqual(released, 2, 'pagehide y beforeunload sueltan la impresora');
  QLUsb.ready = realReady; QLUsb.connect = realConnect; QLUsb.remoteOwner = realOwner; global.fetch = f0;

  console.log('shared_print_rules_check OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
