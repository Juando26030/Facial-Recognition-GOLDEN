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
  EVENT_ID: 7, EVENT_AUTO_PRINT: true, STAFF_ROLE: 'digitador', localStorage: mem, SHARED_PRINT_ENABLED: !process.env.SHARED_OFF,
  __me: process.env.STATION ? { admin: false, station: true, settings: Object.assign({ readerOnly: false, mode: 'driver', pageWidthMm: 60, rotation: 90 }, process.env.STATION === 'show' ? {} : { showConfig: false }) } : null,
  showToast: (m, t) => { toasts.push({ m, t }); }, showConfirm: async () => true,
  BadgePrint: { openPrintWindow: (id) => { original.open.push(id); }, maybeAutoPrint: (id) => { original.auto.push(id); } },
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
eval(fs.readFileSync(path.resolve(__dirname, '../../static/js/shared-print.js'), 'utf8'));
const settle = () => new Promise((r) => setTimeout(r, 30));
const lastToast = () => (toasts[toasts.length - 1] || {});

(async () => {
  await settle();
  const BP = window.BadgePrint;

  /* ---------------------------------------------------------------- 27-oct-2026: lo que se conserva sobre la impresión del domingo */
  if (process.env.SHARED_OFF) {                                         // compartida APAGADA
    await new Promise((r) => setTimeout(r, 200));
    if (process.env.NOWEBUSB) {                                          // sin WebUSB: se comporta como antes (la ventana de siempre, sin «Conectar»)
      await BP.openPrintWindow('1999'); BP.maybeAutoPrint('1998'); await settle();
      assert.deepStrictEqual(original.open, ['1999'], 'el botón abre la ventana de siempre'); assert.deepStrictEqual(original.auto, ['1998'], 'la autoimpresión es la de siempre');
      assert.deepStrictEqual(sharedCalls, [], 'ninguna llamada a rutas de impresión compartida: ' + sharedCalls.join(','));
      const st = GoldenSharedPrint.stationState();
      assert.ok(st.shown && !st.bar.prefs && st.bar.connect && st.bar.queue && st.bar.pending, 'menú visible; sin Conectar (no hay WebUSB), Cola ni pendientes: ' + JSON.stringify(st.bar));
      assert.ok(/^Sin impresora: se usa la ventana de impresión del navegador\./.test(st.line) && !/compartida/i.test(st.line), st.line);
      console.log('shared_print_off OK'); process.exit(0);
    }
    // con WebUSB simulado: aparece «Conectar impresora», se conecta y se imprime por USB, SIN llamar a ninguna ruta compartida
    assert.ok(!GoldenSharedPrint.stationState().bar.connect, '«Conectar impresora» visible con la compartida apagada');
    assert.ok(/^Sin impresora: se usa la ventana de impresión del navegador\./.test(GoldenSharedPrint.stationState().line));
    const sent = []; QLUsb.connect = async () => ({ productName: 'QL-800' }); QLUsb.info = () => ({ name: 'QL-800' }); QLUsb.sendJob = async (j) => { sent.push(j.length); };
    await GoldenSharedPrint.connectForTest(true); await settle();
    assert.ok(GoldenSharedPrint.state().usb.ok && /^Impresora conectada \(QL-800\)\.$/.test(GoldenSharedPrint.stationState().line) && GoldenSharedPrint.stationState().bar.connect, GoldenSharedPrint.stationState().line);
    const f0 = global.fetch, tpl0 = { width_mm: 62, height_mm: 100, orientation: 'vertical', background_type: 'color', background_value: '#fff', elements: [] };
    global.fetch = async (url, init = {}) => { const u = new URL(url, 'http://x'); if (u.pathname.includes('/badge-print-data')) return json(200, { id: '1001', first_name: 'Ana', last_name: 'Mora', has_photo: false }); return f0(url, init); };
    global.BadgeRender = { loadFonts: async () => {}, renderBadge() {}, fetchTemplate: async () => json(200, tpl0) };
    global.html2canvas = async () => ({ width: Math.round(62 * 300 / 25.4), height: Math.round(100 * 300 / 25.4), getContext: () => null });
    original.open.length = 0;
    await BP.openPrintWindow('1001'); await settle();
    assert.strictEqual(sent.length, 1, 'imprime por USB con el mismo flujo de siempre: ' + JSON.stringify(toasts.slice(-3))); assert.deepStrictEqual(original.open, [], 'sin abrir la ventana del navegador');
    assert.deepStrictEqual(sharedCalls, [], 'ninguna ruta compartida (latido, sondeo, Cola, reclamo): ' + sharedCalls.join(','));
    QLUsb.connect = async () => null; QLUsb.info = () => null; await GoldenSharedPrint.disconnectForTest(); await GoldenSharedPrint.connectForTest(false);   // sin impresora: cae a la ventana normal
    await BP.openPrintWindow('1002'); await settle(); assert.deepStrictEqual(original.open, ['1002'], 'sin impresora, cae a la ventana normal');
    console.log('shared_print_off_usb OK'); process.exit(0);
  }
  if (process.env.HOSTMODE) {                                           // 29-oct-2026, problema B: estado explícito de impresión (usb / dialog / none) y los avisos que dependen de él
    await new Promise((r) => setTimeout(r, 200));
    const beat = async (hb) => { global.__hb = hb; beats.length = 0; await GoldenSharedPrint.connectForTest(false); await settle(); return { b: beats[beats.length - 1] || {}, bar: GoldenSharedPrint.barState() }; };
    // 1) sin impresora ni declaración, atendiendo a 2 equipos: «none»; el aviso dice lo que pasa y NO que la impresora está «DESCONECTADA»
    let r = await beat({ serving: 2, waiting: 0, my_mode: 'none' });
    assert.strictEqual(r.b.print_mode, 'none', 'sin impresora: print_mode none (' + JSON.stringify(r.b) + ')');
    assert.ok(/2 equipo\(s\) imprimen aquí y no tienes impresora/.test(r.bar.text) && !/DESCONECTADA/.test(r.bar.text) && r.bar.kind === 'bad', r.bar.text);
    assert.ok(!r.bar.dialogHidden && /Este equipo imprime con la ventana de Chrome/.test(r.bar.dialogText), 'el control para declararlo está a la vista');
    // 2) la persona lo declara: el latido manda dialog, el aviso desaparece y con pendientes dice qué hacer
    GoldenSharedPrint.declareDialogForTest(true);
    r = await beat({ serving: 2, waiting: 0, my_mode: 'dialog' });
    assert.strictEqual(r.b.print_mode, 'dialog', 'declarado: print_mode dialog');
    assert.ok(/imprime con la ventana de Chrome/.test(r.bar.text) && !/no tienes impresora|DESCONECTADA/.test(r.bar.text) && r.bar.kind === 'ok', r.bar.text);
    assert.ok(/quitar/.test(r.bar.dialogText), 'el control muestra que está activo');
    r = await beat({ serving: 2, waiting: 3, my_mode: 'dialog' });
    assert.ok(/3 escarapela\(s\) de otros equipos esperan: toca «Imprimir pendientes»/.test(r.bar.text) && !/DESCONECTADA/.test(r.bar.text), r.bar.text);
    assert.ok(!r.bar.pendingHidden, '«Imprimir pendientes» visible');
    // 3) quien pide: el aviso depende del modo del anfitrión
    mode = 'shared';
    GoldenSharedPrint.declareDialogForTest(false);
    r = await beat({ printer_ready: false, printer_mode: 'dialog', printer_online: true, printer_name: 'Ana' });
    assert.ok(/Imprime en el equipo de Ana con la ventana de Chrome: sale cuando ese equipo toque «Imprimir pendientes»/.test(r.bar.text) && r.bar.kind === 'ok', r.bar.text);
    r = await beat({ printer_ready: false, printer_mode: 'none', printer_online: true, printer_name: 'Ana' });
    assert.ok(/El equipo de Ana no tiene impresora ahora: tus escarapelas quedan en cola/.test(r.bar.text) && r.bar.kind === 'bad', r.bar.text);
    r = await beat({ printer_ready: true, printer_mode: 'usb', printer_online: true, printer_name: 'Ana' });
    assert.ok(/^Imprime en el equipo de Ana\.$/.test(r.bar.text), r.bar.text);
    // 4) conectar la impresora USB: el aviso desaparece y el latido manda usb
    mode = 'self';
    QLUsb.connect = async () => ({ productName: 'QL-800' }); QLUsb.info = () => ({ name: 'QL-800' });
    await GoldenSharedPrint.connectForTest(true);
    r = await beat({ serving: 2, my_mode: 'usb' });
    assert.strictEqual(r.b.print_mode, 'usb');
    assert.ok(/Impresora conectada \(QL-800\)\. Imprime también para 2 equipo\(s\)\./.test(r.bar.text) && r.bar.kind === 'ok' && r.bar.dialogHidden, r.bar.text);
    console.log('host_mode OK'); process.exit(0);
  }
  if (process.env.DENIED) {                                             // Windows: «Access denied» → aviso claro UNA vez, sin reintentos en bucle ni «dueño de la impresora»
    await new Promise((r) => setTimeout(r, 200));
    let calls = 0; const denied = Object.assign(new Error("Failed to execute 'open' on 'USBDevice': Access denied."), { name: 'SecurityError' });
    QLUsb.connect = async () => { calls++; throw denied; };
    toasts.length = 0; beats.length = 0;
    await GoldenSharedPrint.connectForTest(false); await GoldenSharedPrint.connectForTest(false); await GoldenSharedPrint.connectForTest(false);
    for (const f of (docListeners.bubble.visibilitychange || [])) f({ type: 'visibilitychange' });
    await settle();
    assert.strictEqual(calls, 1, 'un solo intento: no reintenta en bucle (' + calls + ')');
    const notices = toasts.filter((t) => /Windows usa su propio controlador/.test(t.m));
    assert.strictEqual(notices.length, 1, 'el aviso sale UNA vez'); assert.ok(notices[0].t !== 'error' && /Para recibir trabajos de otros equipos, usa un celular o tablet Android conectado a la impresora, o toca «Imprimir pendientes» y confirma en el cuadro de Chrome\./.test(notices[0].m), notices[0].m);
    assert.ok(!toasts.some((t) => t.t === 'error'), 'ningún aviso rojo');
    await GoldenSharedPrint.connectForTest(true); await settle();                                  // la persona toca «Conectar»: un intento y el aviso se muestra otra vez (nunca «no pasa nada»)
    assert.strictEqual(toasts.filter((t) => /Windows usa su propio controlador/.test(t.m)).length, 2, 'al tocar Conectar se explica de nuevo');
    const bst = GoldenSharedPrint.stationState(); assert.ok(bst.bar.connect, 'el botón inútil se oculta');
    assert.ok(!GoldenSharedPrint.state().usb.ok && GoldenSharedPrint.state().usb.denied, 'no queda como dueño de la impresora');
    assert.ok(beats.every((b) => b.printer_connected !== true), 'el latido nunca lo anuncia con impresora: ' + JSON.stringify(beats.map((b) => b.printer_connected)));
    console.log('denied_notice OK'); process.exit(0);
  }
  if (process.env.MOBILE) {                                             // celular / tablet: nunca «controlador» ni «cuadro de diálogo»
    await new Promise((r) => setTimeout(r, 200));
    const txt = GoldenSharedPrint.stationState().line + ' ' + toasts.map((t) => t.m).join(' ');
    assert.ok(!/controlador|Windows|cuadro de di|lanzador/i.test(txt), txt);
    assert.ok(/Sin impresora/.test(GoldenSharedPrint.stationState().line), GoldenSharedPrint.stationState().line);
    console.log('mobile_bar OK'); process.exit(0);
  }
  if (process.env.STATION) {                                            // puesto: Mostrar / Esconder (cualquier rol) y lo viejo guardado (modo, ancho, giro) se IGNORA
    await new Promise((r) => setTimeout(r, 200));
    let st = GoldenSharedPrint.stationState();
    assert.ok(!st.isAdmin, 'cuenta digitador');
    if (process.env.STATION === 'show') {
      assert.ok(st.shown && !st.bar.prefs && !st.bar.queue, 'digitador con el menú visible: ' + JSON.stringify(st.bar));
      global.__me.settings.showConfig = false; GoldenSharedPrint.applyStationForTest(global.__me); st = GoldenSharedPrint.stationState();
    }
    assert.ok(!st.shown && st.bar.prefs && st.bar.queue && st.bar.connect, 'menú escondido: ' + JSON.stringify(st.bar));
    assert.ok(/^Imprime en: este puesto/.test(st.line), st.line);
    const r = QLUsb.resolvePrefs(mem, {});
    assert.strictEqual(r.prefs.rotation, 'auto', 'el giro guardado en el puesto se ignora (como el domingo)');
    console.log(process.env.STATION === 'show' ? 'station_show OK' : 'station_config OK'); process.exit(0);
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

  console.log('shared_print_rules_check OK');

  // ---- 6) trabajos de OTROS equipos (4797531): SOLO reclama por sondeo la dueña de la impresora USB; sin USB esperan en el servidor y «Imprimir pendientes» los reclama al tocarlo,
  //         los imprime con la ventana de siempre y los confirma. Ninguno se pierde ni se reimprime solo.
  {
    const results = [], claims = []; let queue = [{ id: 71, user_id: '1001', requested_by: 'x1' }, { id: 72, user_id: '1002', requested_by: 'x1' }];
    const f2 = global.fetch;
    global.fetch = async (url, init = {}) => {
      const u = new URL(url, 'http://x');
      if (u.pathname.endsWith('/print-devices/heartbeat')) return json(200, { enabled: true, mode: 'self', printer_name: '', printer_ready: false, serving: 2, poll: true, waiting: queue.length, claimed: 0, holder: true });
      if (u.pathname.endsWith('/print-jobs-next')) { claims.push({ manual: u.searchParams.get('manual') === '1', device: u.searchParams.get('device_id') }); return json(200, { job: queue.shift() || null }); }
      if (/\/print-jobs\/\d+\/result$/.test(u.pathname)) { results.push(Object.assign({ id: Number(u.pathname.match(/(\d+)\/result/)[1]) }, JSON.parse(init.body))); return json(200, {}); }
      return f2(url, init);
    };
    original.open.length = 0;
    QLUsb.connect = async () => null; await GoldenSharedPrint.connectForTest(); await new Promise((r) => setTimeout(r, 200));
    assert.strictEqual(claims.length, 0, 'sin impresora USB nadie reclama por sondeo: el trabajo no desaparece del servidor');
    assert.strictEqual(GoldenSharedPrint.state().pendingJobs, 2, 'se ven los 2 que esperan');
    await GoldenSharedPrint.printPending();
    assert.ok(claims.slice(0, 2).every((c) => c.manual && c.device === GoldenSharedPrint.state().deviceId), '«Imprimir pendientes» reclama al tocarlo');
    assert.deepStrictEqual(original.open, ['1001', '1002'], 'cada uno con la ventana de impresión de siempre');
    assert.deepStrictEqual(results.map((r) => [r.id, r.ok]), [[71, true], [72, true]], 'y se confirman');
    // con la impresora USB conectada en ESTA ventana: reclama por sondeo, sin que nadie toque nada
    queue = [{ id: 81, user_id: '1001', requested_by: 'x2' }]; claims.length = 0;
    QLUsb.connect = async () => ({ productName: 'QL-800' }); QLUsb.info = () => ({ name: 'QL-800' }); QLUsb.sendJob = async () => {};
    await GoldenSharedPrint.connectForTest(true); await new Promise((r) => setTimeout(r, 400));
    assert.ok(claims.some((c) => !c.manual), 'la dueña de la impresora USB reclama sola');
    assert.ok(results.some((r) => r.id === 81), 'y confirma el resultado (no se pierde)');
    global.fetch = f2;
  }
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
