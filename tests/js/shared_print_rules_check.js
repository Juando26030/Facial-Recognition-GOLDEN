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
  getBoundingClientRect() { return { width: 222, height: 378, left: 0, top: 0 }; }
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
  EVENT_ID: 7, EVENT_AUTO_PRINT: true, SHARED_PRINT_ENABLED: !process.env.SHARED_OFF, __me: process.env.STATION ? { admin: false, station: true, settings: Object.assign({ mode: 'driver', noDialog: false, pageWidthMm: 60, dx: 1.5, dy: -0.5, rotation: 90, crop: false, feedMm: 4 }, process.env.STATION === 'show' ? {} : { showConfig: false }) } : null, STAFF_ROLE: 'digitador', localStorage: mem,
  showToast: (m, t) => { toasts.push({ m, t }); }, showConfirm: async () => true,
  BadgePrint: { openPrintWindow: (id) => { original.open.push(id); }, maybeAutoPrint: (id) => { original.auto.push(id); } },
});
Object.defineProperty(global, 'navigator', { configurable: true, value: { userAgent: process.env.MOBILE ? 'Mozilla/5.0 (Linux; Android 14) Chrome/130 Mobile' : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130', usb: { addEventListener() {}, getDevices: async () => [] } } });
const sharedCalls = [];
const REGISTERED = new Set(['1001']);
let mode = 'self';
const jobs = [];
const reqIds = [];
let flaky = false;
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
global.fetch = async (url, init = {}) => {
  const u = new URL(url, 'http://x');
  if (process.env.SHARED_OFF && /print-devices|print-jobs|print-check/.test(u.pathname)) { sharedCalls.push(u.pathname); return json(409, { detail: 'La impresión compartida está desactivada' }); }
  if (u.pathname.endsWith('/print-station/me')) return json(200, global.__me || { admin: true, station: false, settings: null });
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
global.DriverPrint = require(path.resolve(__dirname, '../../static/js/driver-print.js'));
const driverPages = [];                                                   // lo que se manda a imprimir por el controlador (tamaño exacto)
DriverPrint.bitmapToDataUrl = () => 'data:image/png;base64,AAA';
DriverPrint.printPage = async (spec, url) => { driverPages.push({ spec, url }); return { printed: true }; };
QLUsb.connect = async () => null;                                  // este equipo no tiene impresora USB: imprime con la ventana de siempre
eval(fs.readFileSync(path.resolve(__dirname, '../../static/js/shared-print.js'), 'utf8'));
const settle = () => new Promise((r) => setTimeout(r, 30));
const lastToast = () => (toasts[toasts.length - 1] || {});

(async () => {
  await settle();
  const BP = window.BadgePrint;
  if (process.env.MOBILE) {                                             // celular/tablet: nunca «controlador de Windows» ni «cuadro de diálogo»
    const sp = () => GoldenSharedPrint; QLUsb.releaseNow = () => {};
    const denied = Object.assign(new Error("Failed to execute 'open' on 'USBDevice': Access denied."), { name: 'SecurityError' });
    QLUsb.connect = async () => { throw QLUsb.friendlyError(denied); };
    QLUsb.remoteOwner = async () => null;
    mem.d = {}; sp().setPrintMode('auto'); await settle(); await sp().connectUsb(false); await settle();
    assert.ok(!sp().driverOn(), 'en celular no se pasa al controlador');
    sp().setPrintMode('driver'); await settle();
    assert.ok(!sp().driverOn(), 'aunque el modo diga controlador');
    const txt = sp().stationState().line + ' ' + toasts.map((t) => t.m).join(' ');
    assert.ok(!/controlador|Windows|cuadro de di/i.test(txt), txt);
    assert.ok(/Sin impresora/.test(sp().stationState().line), sp().stationState().line);
    console.log('mobile_bar OK'); process.exit(0);
  }
  if (process.env.STATION === 'show') {                                 // «Mostrar» (por defecto): un DIGITADOR ve y usa el menú; lo que cambie vale solo para este computador
    const sp = () => GoldenSharedPrint; QLUsb.releaseNow = () => {};
    mem.d = { gw_print_mode: 'usb', ql_rotation: '270', gw_driver_page_mm: '62' };      // lo que el navegador tenía de ANTES: no reaparece (gana Parámetros)
    await new Promise((r) => setTimeout(r, 300));
    let st = sp().stationState();
    assert.ok(!st.isAdmin && st.shown, 'digitador con el menú visible');
    assert.ok(!st.bar.prefs && !st.bar.queue, 've ⚙️ y la Cola sin ser admin: ' + JSON.stringify(st.bar));
    assert.ok(sp().driverOn(), 'modo del puesto (controlador), no el «usb» viejo del navegador');
    const f0 = global.fetch, tpl0 = { width_mm: 100, height_mm: 58.9, orientation: 'horizontal', background_type: 'color', background_value: '#fff', elements: [] };
    global.fetch = async (url, init = {}) => { const u = new URL(url, 'http://x'); if (u.pathname.includes('/badge-print-data')) return json(200, { id: '1001', first_name: 'Ana', last_name: 'Mora', has_photo: false }); return f0(url, init); };
    global.BadgeRender = { loadFonts: async () => {}, renderBadge() {}, fetchTemplate: async () => json(200, tpl0) };
    global.html2canvas = async () => ({ width: Math.round(100 * 300 / 25.4), height: Math.round(58.9 * 300 / 25.4), getContext: () => null });
    driverPages.length = 0; await sp().printFor('1001', false, true);
    assert.ok(Math.abs(driverPages[0].spec.pageWidthMm - 60) < 0.01, 'base = Parámetros (60), no lo viejo del navegador (62): ' + driverPages[0].spec.pageWidthMm);
    DriverPrint.setPageWidthMm(sp().storageForTest(), 61);                // el panel de ESTE computador cambia el ancho
    driverPages.length = 0; await sp().printFor('1001', false, true);
    assert.ok(Math.abs(driverPages[0].spec.pageWidthMm - 61) < 0.01, 'con el menú visible, el cambio local vale en este computador: ' + driverPages[0].spec.pageWidthMm);
    assert.strictEqual(mem.d.gw_driver_page_mm, '62', 'lo viejo del navegador no se tocó'); assert.strictEqual(mem.d.gw_ovr_7_gw_driver_page_mm, '61');
    global.__me.settings.showConfig = false; sp().applyStationForTest(global.__me);                      // el coordinador lo esconde
    driverPages.length = 0; await sp().printFor('1001', false, true);
    st = sp().stationState();
    assert.ok(!st.shown && st.bar.prefs && st.bar.queue && st.bar.connect, 'escondido: sin menú');
    assert.ok(Math.abs(driverPages[0].spec.pageWidthMm - 60) < 0.01, 'escondido: solo Parámetros, se ignora el cambio local: ' + driverPages[0].spec.pageWidthMm);
    console.log('station_show OK'); process.exit(0);
  }
  if (process.env.STATION) {                                            // puesto con el menú ESCONDIDO desde Parámetros (cualquier rol)
    const sp = () => GoldenSharedPrint; QLUsb.releaseNow = () => {};
    mem.d = { gw_print_mode: 'usb', ql_rotation: '270', ql_crop: '1', gw_driver_page_mm: '62' };      // lo que el navegador tenía guardado: el servidor GANA
    await new Promise((r) => setTimeout(r, 300));
    const st = sp().stationState();
    assert.ok(!st.isAdmin && st.isStation && st.cfg && st.cfg.mode === 'driver', 'lee su configuración del servidor');
    assert.ok(sp().driverOn(), 'el modo del servidor manda sobre el navegador');
    assert.ok(!st.shown && st.bar.prefs && st.bar.queue && st.bar.connect && st.bar.always && st.bar.guide, 'menú escondido: no se ve ⚙️, Cola, Conectar ni la guía: ' + JSON.stringify(st.bar));
    assert.ok(/^Imprime en: este puesto/.test(st.line), st.line);
    const f0 = global.fetch, tpl0 = { width_mm: 100, height_mm: 58.9, orientation: 'horizontal', background_type: 'color', background_value: '#fff', elements: [] };
    global.fetch = async (url, init = {}) => { const u = new URL(url, 'http://x'); if (u.pathname.includes('/badge-print-data')) return json(200, { id: '1001', first_name: 'Ana', last_name: 'Mora', has_photo: false }); return f0(url, init); };
    global.BadgeRender = { loadFonts: async () => {}, renderBadge() {}, fetchTemplate: async () => json(200, tpl0) };
    global.html2canvas = async () => ({ width: Math.round(100 * 300 / 25.4), height: Math.round(58.9 * 300 / 25.4), getContext: () => null });
    driverPages.length = 0;
    await sp().printFor('1001', false, true);
    const pg = driverPages[0].spec;
    assert.ok(Math.abs(pg.pageWidthMm - 60) < 0.01, 'ancho de página del servidor (60), no el del navegador (62): ' + pg.pageWidthMm);
    mem.d = {};                                                         // borrar el almacenamiento del navegador no cambia nada
    driverPages.length = 0; await sp().printFor('1001', false, true);
    assert.ok(Math.abs(driverPages[0].spec.pageWidthMm - 60) < 0.01 && sp().driverOn(), 'el puesto conserva su configuración tras borrar el navegador');
    console.log('station_config OK'); process.exit(0);
  }
  if (process.env.SHARED_OFF) {
    const sp = () => GoldenSharedPrint; QLUsb.releaseNow = () => {};                                         // evento SIN impresión compartida: el modo por controlador funciona igual y no se llama a ninguna ruta compartida
    sp().setPrintMode('driver'); await settle(); await new Promise((r) => setTimeout(r, 200));
    assert.ok(sp().driverOn() && sp().state().online, 'modo controlador activo y barra en línea');
    const f0 = global.fetch, tpl0 = { width_mm: 58.9, height_mm: 100, orientation: 'vertical', background_type: 'color', background_value: '#fff', elements: [] };
    global.fetch = async (url, init = {}) => { const u = new URL(url, 'http://x'); if (u.pathname.includes('/badge-print-data')) return json(200, { id: '1001', first_name: 'Ana', last_name: 'Mora', has_photo: false }); return f0(url, init); };
    global.BadgeRender = { loadFonts: async () => {}, renderBadge() {}, fetchTemplate: async () => json(200, tpl0) };
    global.html2canvas = async () => ({ width: Math.round(58.9 * 300 / 25.4), height: Math.round(100 * 300 / 25.4), getContext: () => null });
    driverPages.length = 0;
    await sp().printFor('1001', false, true);
    assert.strictEqual(driverPages.length, 1, 'imprime una página por el controlador'); assert.ok(driverPages[0].spec.pageWidthMm < 58.95 && driverPages[0].spec.pageCss.includes('margin: 0'));
    await sp().drvPrint(sp().testCompose(), QLUsb.resolvePrefs(null, {}).prefs); assert.strictEqual(driverPages.length, 2, '«Imprimir prueba» también');
    await sp().printFor('1999', false, true); assert.strictEqual(driverPages.length, 3, 'sin «registrado» compartido que consultar');
    assert.deepStrictEqual(sharedCalls, [], 'ninguna llamada a rutas de impresión compartida: ' + sharedCalls.join(','));
    console.log('shared_print_off OK'); process.exit(0);
  }

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
  // Y (este mismo código en el equipo con la impresora) con OTROS valores locales: del pedido, los físicos (corte, avance, espejo); la forma, la del equipo que imprime
  QLUsb.clearPrefs(mem); QLUsb.savePrefs(mem, { cut: true, feedMm: 1, mirror: false, rotation: 90 });
  let r = GoldenSharedPrint.prefsForJob({ prefs: sent.prefs });
  assert.strictEqual(r.prefs.cut, false); assert.strictEqual(r.prefs.feedMm, 4); assert.strictEqual(r.prefs.mirror, true); assert.strictEqual(r.prefs.rotation, 90, 'la FORMA (giro) es la del equipo que imprime, no la del que pidió'); assert.deepStrictEqual(r.diff, ['rotation']);
  assert.ok(/el equipo que la pidió/.test(QLUsb.describePrefs(r.prefs, r.source)), QLUsb.describePrefs(r.prefs, r.source));
  // pedido viejo en cola (sin parámetros): los del EVENTO, nunca los locales de Y
  r = GoldenSharedPrint.prefsForJob({ id: 1, user_id: '1001' });
  assert.strictEqual(r.prefs.feedMm, 1.5); assert.strictEqual(r.prefs.cut, true); assert.strictEqual(r.prefs.rotation, 'auto');
  assert.ok(!Object.values(r.source).includes('equipo'), 'no usa nada de este equipo');
  const src = fs.readFileSync(path.resolve(__dirname, '../../static/js/shared-print.js'), 'utf8');
  assert.ok(src.includes('printLabel(job.user_id, used)') && src.includes('const used = prefsForJob(job)'), 'Y imprime cada pedido con prefsForJob');
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
  assert.ok(beats.length && beats[beats.length - 1].printer_connected === null, 'la pestaña que imprime a través de otra NO pisa el estado del puesto (la dueña lo anuncia)');
  // «Conectar» con la impresora ya conectada: «Ya conectada», sin intentar abrirla otra vez
  let calls = 0; QLUsb.connect = async () => { calls++; throw busy; };
  toasts.length = 0; await GoldenSharedPrint.connectUsb(true);
  assert.strictEqual(calls, 0, 'no se vuelve a abrir'); assert.ok(toasts.some((t) => /ya está conectada/.test(t.m)), 'dice «ya está conectada»');
  // nadie la tiene y Chrome dice «Access denied»: mensaje claro, estado desconectado y reintento posible
  QLUsb.remoteOwner = async () => null;
  const denied = Object.assign(new Error("Failed to execute 'open' on 'USBDevice': Access denied."), { name: 'SecurityError' });
  QLUsb.connect = async () => { throw QLUsb.friendlyError(denied); };
  await GoldenSharedPrint.disconnectForTest();
  GoldenSharedPrint.setPrintMode('usb');                               // en «USB directo» el aviso sí se muestra (en «automático» pasa al controlador)
  toasts.length = 0; await GoldenSharedPrint.connectUsb(true);
  st = GoldenSharedPrint.state();
  assert.ok(!st.usb.ok && st.usb.code === 'denied' && /no puede usar la impresora por USB directo/.test(st.usb.lastError), st.usb.lastError);
  assert.ok(toasts.some((t) => t.t === 'error' && /Controlador de Windows/.test(t.m)), 'el aviso trae la acción a seguir');
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

  // ---- 7) IMPRESIÓN POR EL CONTROLADOR DE WINDOWS (25-oct-2026): un modo normal, sin aviso rojo; tamaño exacto; persistencia por equipo; trabajos de otros equipos
  const beats2 = [];
  const fPrev = global.fetch;
  global.fetch = async (url, init = {}) => { if (String(url).endsWith('/print-devices/heartbeat')) beats2.push(JSON.parse(init.body)); return fPrev(url, init); };
  QLUsb.releaseNow = () => {};
  mem.d = {};
  const sp = () => GoldenSharedPrint;
  // a) «Automático» + «Access denied» de Windows: pasa al controlador con UN solo aviso corto (nada de rojo) y la barra queda en modo controlador
  const denied2 = Object.assign(new Error("Failed to execute 'open' on 'USBDevice': Access denied."), { name: 'SecurityError' });
  QLUsb.connect = async () => { throw QLUsb.friendlyError(denied2); };
  QLUsb.remoteOwner = async () => null;
  toasts.length = 0;
  sp().setPrintMode('auto'); await settle();
  await sp().disconnectForTest(); await sp().connectUsb(false); await sp().connectUsb(false); await sp().connectUsb(true);
  assert.ok(sp().driverOn(), 'en automático, con acceso denegado se pasa al controlador');
  assert.ok(!toasts.some((t) => t.t === 'error'), 'ningún aviso rojo');
  assert.strictEqual(toasts.filter((t) => /controlador de Brother/.test(t.m)).length, 1, 'un mensaje corto, UNA sola vez');
  assert.ok(!/no se pudo conectar/i.test(toasts.map((t) => t.m).join(' ')));
  assert.ok(beats2.length && beats2[beats2.length - 1].printer_connected === false && /con cuadro/.test(beats2[beats2.length - 1].printer_name), 'en controlador CON cuadro anuncia que NO imprime sola');
  // b) imprimir en este modo: una página de tamaño exacto, con la misma etiqueta de «Imprimir prueba» y sin tocar WebUSB
  driverPages.length = 0; let usbTouched = 0; QLUsb.connect = async () => { usbTouched++; return null; };
  await sp().drvPrint(sp().testCompose(), QLUsb.resolvePrefs(null, {}).prefs);
  const pg = driverPages[0].spec;
  assert.ok(Math.abs(pg.imageWidthMm - 696 * 25.4 / 300) < 0.01 && pg.pageWidthMm < 58.95 && pg.pageCss.includes('margin: 0') && pg.pageCss.includes(`size: ${pg.pageWidthMm}mm ${pg.pageHeightMm}mm`), JSON.stringify(pg));
  assert.ok(Math.abs(pg.pageHeightMm - 1181 * 25.4 / 300) < 40, 'el largo sale de la etiqueta real');
  // c) el modo se guarda en ESTE equipo y se respeta: «Controlador de Windows» no intenta WebUSB ni muestra «Conectar»
  sp().setPrintMode('driver'); await settle();
  assert.strictEqual(mem.d.gw_print_mode, 'driver');
  toasts.length = 0; usbTouched = 0;
  await sp().connectUsb(true); await sp().connectUsb(false);
  assert.strictEqual(usbTouched, 0, 'no intenta WebUSB'); assert.ok(!toasts.length, 'ni un aviso');
  assert.ok(sp().driverOn() && !sp().state().usb.ok);
  // d) trabajos de OTROS equipos: sin lanzador (con cuadro de diálogo) quedan PENDIENTES hasta «Imprimir pendientes»; con lanzador (sin cuadro) se imprimen solos
  await new Promise((r) => setTimeout(r, 250));                       // que terminen los latidos en vuelo de los pasos anteriores (no pisan al nuevo)
  const results = [], claims = []; let queue = [{ id: 71, user_id: '1001', requested_by: 'x1', prefs: { rotation: 'auto', mirror: true } }, { id: 72, user_id: '1002', requested_by: 'x1' }];
  const tpl = { width_mm: 58.9, height_mm: 100, orientation: 'vertical', background_type: 'color', background_value: '#fff', elements: [] };
  const f2 = global.fetch;
  global.fetch = async (url, init = {}) => {
    const u = new URL(url, 'http://x');
    if (u.pathname.endsWith('/print-devices/heartbeat')) return json(200, { enabled: true, mode: 'self', printer_name: '', printer_ready: false, serving: 2, poll: true, waiting: queue.length, claimed: 0, holder: true });
    if (u.pathname.endsWith('/print-jobs-next')) { claims.push({ manual: u.searchParams.get('manual') === '1', device: u.searchParams.get('device_id') }); return json(200, { job: queue.shift() || null }); }
    if (/\/print-jobs\/\d+\/result$/.test(u.pathname)) { results.push(Object.assign({ id: Number(u.pathname.match(/(\d+)\/result/)[1]) }, JSON.parse(init.body))); return json(200, {}); }
    if (u.pathname.includes('/badge-print-data')) return json(200, { id: '1001', first_name: 'Ana', last_name: 'Mora', has_photo: false });
    return f2(url, init);
  };
  global.BadgeRender = { loadFonts: async () => {}, renderBadge() {}, fetchTemplate: async () => json(200, tpl) };
  global.html2canvas = async () => ({ width: Math.round(58.9 * 300 / 25.4), height: Math.round(100 * 300 / 25.4), getContext: () => null });
  const realCompose = QLUsb.prepareBitmap;
  for (const f of docListeners.bubble.visibilitychange || []) f(new Ev('visibilitychange'));
  await new Promise((r) => setTimeout(r, 160));
  assert.strictEqual(sp().state().route.serving, 2);
  assert.strictEqual(sp().state().pendingJobs, 2, 'con cuadro de diálogo, lo que llega de otros equipos espera EN EL SERVIDOR');
  assert.strictEqual(claims.length, 0, 'una ventana con cuadro de diálogo NUNCA reclama por sondeo: el trabajo no desaparece del servidor');
  assert.strictEqual(queue.length, 2, 'los dos trabajos siguen en la cola del servidor');
  assert.strictEqual(results.length, 0, 'nada se imprime solo sin el lanzador');
  driverPages.length = 0;
  await sp().printPending();
  assert.ok(claims.length >= 2 && claims.slice(0, 2).every((c) => c.manual && c.device === sp().state().deviceId), '«Imprimir pendientes» reclama al tocarlo, con el id del equipo');
  assert.deepStrictEqual(results.map((r) => [r.id, r.ok]), [[71, true], [72, true]], 'confirma cada trabajo como impreso');
  assert.strictEqual(driverPages.length, 2, 'cada uno, una página por el controlador');
  assert.ok(driverPages.every((p) => p.spec.pageCss.includes('margin: 0') && p.spec.pageWidthMm < 58.95 && p.spec.imageWidthMm > 58.9 && p.spec.imageWidthMm < 58.95), 'tamaño exacto');
  // con el lanzador (--kiosk-printing): los trabajos se imprimen solos, sin clic
  sp().setKioskForTest(true); results.length = 0; driverPages.length = 0; queue = [{ id: 81, user_id: '1003', requested_by: 'x2' }];
  for (const f of docListeners.bubble.visibilitychange || []) f(new Ev('visibilitychange'));
  await sp().connectUsb(false); await new Promise((r) => setTimeout(r, 1700));
  assert.ok(results.some((r) => r.id === 81 && r.ok === true), 'con el lanzador se imprime sin cuadro y sin pedir nada');
  assert.ok(claims.some((c) => !c.manual), 'con el lanzador SÍ reclama por sondeo');
  // si el controlador falla, el trabajo se confirma como fallido (no se pierde ni se repite solo)
  DriverPrint.printPage = async () => { throw new Error('La impresora de Windows no respondió.'); };
  results.length = 0; queue = [{ id: 91, user_id: '1004', requested_by: 'x2' }];
  await new Promise((r) => setTimeout(r, 1700));
  assert.ok(results.some((r) => r.id === 91 && r.ok === false && /Windows/.test(r.error)), 'confirma el fallo');
  // e) volver a «automático» y a «USB directo» se guarda y se respeta
  sp().setPrintMode('usb'); assert.strictEqual(mem.d.gw_print_mode, 'usb'); assert.ok(!sp().driverOn());
  sp().setPrintMode('auto'); assert.ok(!('gw_print_mode' in mem.d)); assert.ok(!sp().driverOn());
  // f) la forma de la etiqueta sale IGUAL desde cualquier equipo: un trabajo con las prefs de un celular (giro 0, sin recorte) se arma con la forma del equipo que imprime; solo viajan los parámetros físicos
  const phone = sp().prefsForJob({ prefs: { rotation: 0, crop: false, cropMarginMm: 9, tapeType: 'continuous', tapeWidth: 62, cut: false, feedMm: 4, mirror: true, invert: false } });
  assert.strictEqual(phone.prefs.rotation, 'auto'); assert.strictEqual(phone.prefs.crop, true); assert.strictEqual(phone.prefs.cropMarginMm, 3); assert.strictEqual(phone.prefs.cropMode, 'symmetric');
  assert.ok(phone.prefs.cut === false && phone.prefs.feedMm === 4 && phone.prefs.mirror === true, 'corte, margen de avance y espejo SÍ vienen de quien pidió');
  assert.deepStrictEqual(phone.diff.sort(), ['crop', 'cropMarginMm', 'rotation'], 'se avisa qué traía distinto');
  const lay = QLUsb.layout(phone.prefs, 100, 58.9); assert.strictEqual(lay.rotation, 90); assert.strictEqual(lay.scale, 1, 'la horizontal 100×58,9 no se encoge');
  const same = sp().prefsForJob({ prefs: { rotation: 'auto', crop: true } }); assert.deepStrictEqual(same.diff, []);
  global.fetch = f2;
  console.log('shared_print_rules_check OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
