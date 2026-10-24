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
  getContext() { return { fillRect() {}, strokeRect() {}, fillText() {}, drawImage() {}, getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(w * h * 4).fill(255) }) }; }
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
Object.assign(global, {
  EVENT_ID: 7, EVENT_AUTO_PRINT: true, STAFF_ROLE: 'digitador', localStorage: mem,
  showToast: (m, t) => { toasts.push({ m, t }); }, showConfirm: async () => true,
  BadgePrint: { openPrintWindow: (id) => { original.open.push(id); }, maybeAutoPrint: (id) => { original.auto.push(id); } },
});
Object.defineProperty(global, 'navigator', { configurable: true, value: { userAgent: 'Mozilla/5.0 (Linux; Android 14) Chrome/130', usb: { addEventListener() {}, getDevices: async () => [] } } });
const REGISTERED = new Set(['1001']);
let mode = 'self';
const jobs = [];
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
global.fetch = async (url, init = {}) => {
  const u = new URL(url, 'http://x');
  if (u.pathname.endsWith('/print-devices/heartbeat')) return json(200, { enabled: true, mode, printer_name: mode === 'shared' ? 'dig1' : '', printer_ready: true, serving: 0, poll: false });
  let m = u.pathname.match(/\/print-check\/(.+)$/);
  if (m) return json(200, REGISTERED.has(m[1]) ? { registered: true } : { registered: false, detail: `No se puede imprimir: Persona ${m[1]} aún no está registrado. Acredítalo o guarda su registro primero.` });
  if (u.pathname.endsWith('/print-jobs') && init.method === 'POST') { const b = JSON.parse(init.body); jobs.push(b.user_id); return json(200, { id: jobs.length, status: 'queued', printer_name: 'dig1', printer_ready: true }); }
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

  console.log('shared_print_rules_check OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
