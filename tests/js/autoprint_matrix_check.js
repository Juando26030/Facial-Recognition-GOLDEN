// Matriz de autoimpresión × autorregistro de la pantalla de Registro, con directory.js, badge-render.js y el submitManualRegister de app.js REALES (DOM, red y ventanas falsos).
// Correr: node tests/js/autoprint_matrix_check.js
//  Ingreso:  lector (código de barras) · Enter con la cédula escrita · clic en el resultado de la búsqueda · clic en «✅ Acreditar» de la lista.
//  Guardar:  editar y guardar con estado «Registrado» (coordinador y digitador) · «Registrar nuevo» (formulario).
//  Para cada caso, con la bandera cambiada EN VIVO con la pantalla abierta (llega por el sondeo y se avisa gw:flags) y con ella YA ACTIVA:
//    autoimpresión + autorregistro encendidos → exactamente 1 impresión y 1 registro, sin pulsar nada más y sin ventanas en blanco;
//    autoimpresión apagada (aunque el autorregistro esté encendido) → 1 registro y NINGUNA impresión.
//  Además: Enter con un NOMBRE (buscador único) no acredita ni imprime; y «Editar» / «🖨️ Imprimir» de cada fila siguen presentes y funcionando con ambos modos activos.
const fs = require('fs');
const assert = require('assert');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.parentNode = null; this._html = ''; this.offsetParent = {}; this.value = ''; this.attrs = {}; this.innerText = ''; this.textContent = ''; this.className = ''; this.placeholder = ''; this.disabled = false; this.hidden = false; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) { c.parentNode = this; const i = ref ? this.children.indexOf(ref) : -1; if (i >= 0) this.children.splice(i, 0, c); else if (ref === null) this.children.push(c); else this.children.unshift(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
  addEventListener(k, f) { this.listeners[k] = f; }
  set innerHTML(v) { this._html = v; this.children = []; }
  get innerHTML() { return this._html; }
  closest() { return table; }
  setAttribute(k, v) { this.attrs[k] = v; }
  focus() { this.focused = true; }
  querySelector() { return null; }
  querySelectorAll(sel) {
    if (sel !== '.gw-reason') return [];
    const out = []; const walk = (n) => n.children.forEach((c) => { if ((c.className || '').includes('gw-reason')) out.push(c); walk(c); }); walk(this); return out;
  }
  replaceChildren(...c) { c.forEach((x) => { x.parentNode = this; }); this.children = c; this._html = ''; }
}
// El cuadro de «Editar persona»: los controles que arma con innerHTML se piden por selector; cada selector da siempre el mismo control de mentira.
class Modal extends El {
  constructor() { super('div'); this.stubs = {}; }
  querySelector(sel) {
    if (sel === '#editModalCedulaField') return null;                    // la cédula solo la edita el admin
    if (!this.stubs[sel]) {
      const s = new El('x'); s.reportValidity = () => true; s.click = () => {};
      if (sel === '#editModalStatus') s.value = 'registrado';           // «Registrado» viene preseleccionado
      this.stubs[sel] = s;
    }
    return this.stubs[sel];
  }
}
const container = new El('div');
const table = container.appendChild(new El('table'));
let els = {};
const fresh = () => { els = { tbody: new El('tbody'), cedula: new El('input'), hint: new El('p') }; };
fresh();

const events = [];                                                       // línea de tiempo: ventanas y llamadas de red, en orden
const wins = [];
const pageEvents = [];
global.window = {
  EVENT_ID: 1, STAFF_ROLE: 'coordinador', OPTIONAL_VARIABLES: [], FIELD_CONFIGS: [], EVENT_AUTO_PRINT: false, EVENT_AUTO_REGISTER: false,
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
  dispatchEvent(ev) { pageEvents.push(ev); return true; },
  FieldRender: { watchEmail() {}, watchEmailDeliverable() {}, initSignatures() {}, saveSignatures: async () => {} },
  open(url, name, features) {
    events.push('open:' + url);
    const w = { url, name, features, closed: false, close() { this.closed = true; events.push('close'); }, _href: '' };
    Object.defineProperty(w, 'location', { value: { set href(v) { w._href = v; events.push('nav:' + v); } } });
    wins.push(w);
    return w;
  },
};
const body = new El('body');
global.document = { getElementById: (id) => (id === 'gwSearchHint' ? els.hint : els[id] || null), createElement: (t) => (t === 'div' ? new Modal() : new El(t)), visibilityState: 'visible', head: new El('head'), body, addEventListener() {} };
global.FormData = class { constructor() { this.m = {}; } append(k, v) { this.m[k] = v; } get(k) { return this.m[k]; } entries() { return Object.entries(this.m); } };
global.setInterval = () => 1;
let now = 9_000_000, timers = [];
global.setTimeout = (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; };
global.clearTimeout = (t) => { timers = timers.filter((x) => x !== t); };
const { settle: flush } = require('./settle');
const advance = async (ms) => { now += ms; const due = timers.filter((t) => t.at <= now); timers = timers.filter((t) => t.at > now); due.forEach((t) => t.f()); await flush(); };
const toasts = []; global.showToast = (m, t, o) => { toasts.push({ m, t, o }); return { close() {} }; };
global.showConfirm = async () => true;
global.CSS = { escape: (x) => x };
global.confirmDuplicateRegistration = async () => false;

// ---- el servidor de mentira: las banderas viven AQUÍ y viajan en cada respuesta, igual que app/routers/api.py (event_flags)
const json = (status, data, headers = {}) => ({ ok: status >= 200 && status < 300, status, headers: { get: (k) => headers[k] ?? null }, json: async () => data });
const SERVER = [];
for (let i = 1; i <= 40; i++) SERVER.push({ id: String(3000 + i), first_name: 'Persona' + i, last_name: 'Prueba', entity: 'ACME', status: 'No registrado' });
SERVER.push({ id: '4001', first_name: 'Carlos', last_name: 'Mejía', entity: 'Zeta', status: 'No registrado' });
let flags = { auto_print: false, auto_register: false };
const registrations = [];                                                // una entrada por registro real hecho por el servidor
const checkinCalls = [];
global.fetch = async (url, init = {}) => {
  const u = new URL(url, 'http://x');
  events.push('fetch:' + u.pathname);
  const F = { auto_print: flags.auto_print, auto_register: flags.auto_register };
  if (u.pathname === '/api/checkin-cedula') {
    const m = init.body.m; checkinCalls.push(m.cedula);
    const p = SERVER.find((x) => x.id === m.cedula) || { id: m.cedula, first_name: 'Ana', last_name: 'Pérez' };
    if (!flags.auto_register && !m.confirm) return json(200, { result: 'FOUND_PENDING', data: { id: p.id, first_name: p.first_name, last_name: p.last_name }, ...F });
    registrations.push(p.id);
    return json(200, { result: 'SÍ', data: { id: p.id, first_name: p.first_name, last_name: p.last_name }, ...F });
  }
  let mm = u.pathname.match(/\/users\/([^/]+)\/status$/);
  if (mm) { const b = JSON.parse(init.body); if (b.status === 'registrado') registrations.push(decodeURIComponent(mm[1])); return json(200, { message: 'Estado de registro actualizado', status: b.status, ...F }); }
  if (u.pathname === '/api/register') { registrations.push(init.body.get('id')); return json(200, { message: 'Usuario registrado exitosamente como Nuevo.', ...F }); }
  if (/print-log$/.test(u.pathname) || u.pathname === '/health' || u.pathname === '/api/ping-auth') return json(200, {});
  if (u.pathname === '/api/users/changes') return json(200, { cursor: '1:1', total: SERVER.length, users: [], flags: F });
  if (u.pathname === '/api/users') return json(200, SERVER, { 'X-Total-Count': String(SERVER.length) });
  throw new Error('ruta inesperada ' + u.pathname);
};
require('../../static/js/badge-render.js'); global.BadgePrint = window.BadgePrint;        // el despachador REAL
window.SearchCore = require('../../static/js/search-core.js');
const dirSrc = fs.readFileSync('static/js/directory.js', 'utf8');
const loadDir = (role) => { window.STAFF_ROLE = role; eval(dirSrc); return window.GoldenDirectory; };      // el rol se lee al cargar el archivo
// «Registrar nuevo»: el submitManualRegister REAL de app.js (se extrae del archivo; vive dentro del cierre de la pantalla)
const appSrc = fs.readFileSync('static/js/app.js', 'utf8');
const regSrc = appSrc.slice(appSrc.indexOf('async function submitManualRegister'), appSrc.indexOf('regForm.onsubmit = async'));
assert.ok(regSrc.includes('maybeAutoPrint(registeredId'), 'se extrajo submitManualRegister');
const regForm = { reset() {}, querySelectorAll: () => [] };
const submitManualRegister = new Function('regForm', 'showPrint', regSrc + '\nreturn submitManualRegister;')(regForm, () => {});

const printUrl = (id) => `/kiosk/1/escarapela/imprimir/${id}`;
const printsOf = (id) => events.filter((e) => e === 'nav:' + printUrl(id) || e === 'open:' + printUrl(id)).length;
const anyPrint = () => events.filter((e) => /\/escarapela\/imprimir\//.test(e) && /^(nav|open):/.test(e)).length;
const blankLeft = () => wins.filter((w) => !w.closed && !w._href && w.url === 'about:blank').length;
const rows = () => els.tbody.children.filter((tr) => !/directory-(local-note|more)/.test(tr.className));
const rowOf = (id) => rows().find((tr) => tr.dataset.userId === id);
const btnOf = (tr, f) => tr.children[0].children.find(f);
const accBtn = (tr) => btnOf(tr, (b) => /btn-accredit-row/.test(b.className));
const printBtn = (tr) => btnOf(tr, (b) => b.title === 'Imprimir escarapela');          // Plan 8 (corrección): Acreditar, Imprimir y Editar siempre a la vista en la fila
const editBtn = (tr) => btnOf(tr, (b) => b.innerText === 'Editar');
const typeIn = async (text) => { els.cedula.value = text; els.cedula.listeners.input(); await advance(250); };
const enter = (text) => { els.cedula.value = text; return els.cedula.listeners.keydown({ key: 'Enter', preventDefault() {}, stopPropagation() {} }); };

let d = null, seq = 0;
const nextId = () => String(3001 + seq++);
const reset = () => { events.length = 0; wins.length = 0; registrations.length = 0; checkinCalls.length = 0; pageEvents.length = 0; };

// Deja la pantalla abierta con las banderas VIEJAS (apagadas) y pone las del servidor según el caso.
//  timing 'vivo': el coordinador las cambia con la pantalla abierta; el sondeo las trae (gw:flags) ANTES de que se registre a nadie.
//  timing 'activa': ya estaban encendidas desde que se abrió la pantalla.
async function prepare(timing, ap, ar) {
  if (timing === 'vivo') {
    window.EVENT_AUTO_PRINT = !ap; window.EVENT_AUTO_REGISTER = !ar;          // lo que la página creía al abrirse: lo contrario (así el sondeo SIEMPRE cambia algo)
    flags = { auto_print: ap, auto_register: ar };
    reset();
    await d.reload(); await advance(10);
    assert.ok(pageEvents.some((e) => e.type === 'gw:flags'), 'el sondeo avisó gw:flags');
  } else {
    window.EVENT_AUTO_PRINT = ap; window.EVENT_AUTO_REGISTER = ar; flags = { auto_print: ap, auto_register: ar };
    reset();
    await d.reload(); await advance(10);
  }
  assert.strictEqual(window.EVENT_AUTO_PRINT, ap, 'la página quedó con la autoimpresión del servidor');
  assert.strictEqual(window.EVENT_AUTO_REGISTER, ar, 'la página quedó con el autorregistro del servidor');
  reset();
}

const openEditAndSave = async (id) => {
  const user = SERVER.find((x) => x.id === id);
  d.openEditFor(user);
  const overlay = body.children[body.children.length - 1], box = overlay.children[0];
  await box.querySelector('#editModalSave').listeners.click();
  overlay.remove();
};

const ENTRIES = {
  'lector (código de barras)': async (id) => { await d.submitScannedCedula(id, null); },
  'Enter con la cédula escrita': async (id) => { await typeIn(id); enter(id); await advance(10); },
  'clic en el resultado de la búsqueda': async (id) => { await typeIn(id); assert.strictEqual(rows().length >= 1, true, 'la búsqueda muestra a la persona'); await accBtn(rowOf(id)).listeners.click(); },
  'clic en «✅ Acreditar» de la lista': async (id) => { await typeIn(''); await accBtn(rowOf(id)).listeners.click(); },
  'editar y guardar con estado «Registrado»': async (id) => { await openEditAndSave(id); },
  '«Registrar nuevo»': async (id) => {
    const fd = new FormData(); fd.append('id', id); fd.append('first_name', 'Nuevo'); fd.append('last_name', 'Persona');
    await submitManualRegister(fd, null);
  },
};

(async () => {
  const G = loadDir('coordinador');
  d = G.mountSearch({ tbodyId: 'tbody', unified: true, fastCheckin: true, searchIds: { cedula: 'cedula', nombre: 'searchNombre', entidad: 'searchEntidad' } });
  d.openEditFor = G.openEdit;
  await d.reload(); await advance(10);
  assert.strictEqual(els.cedula.focused, true, 'buscador único montado');

  let cases = 0;
  for (const timing of ['vivo', 'activa']) {
    for (const [name, run] of Object.entries(ENTRIES)) {
      // --- autoimpresión + autorregistro: exactamente 1 impresión y 1 registro
      await prepare(timing, true, true);
      let id = nextId(); await run(id); await advance(10);
      const tag = `[${timing}] ${name}`;
      assert.strictEqual(registrations.filter((x) => x === id).length, 1, tag + ': exactamente 1 registro: ' + registrations.join(',') + ' | ' + events.join(' | '));
      assert.strictEqual(printsOf(id), 1, tag + ': exactamente 1 impresión: ' + events.join(' | '));
      assert.strictEqual(anyPrint(), 1, tag + ': y ninguna otra ventana de impresión: ' + events.join(' | '));
      assert.strictEqual(blankLeft(), 0, tag + ': sin ventanas en blanco abiertas');
      const w = wins.find((x) => x._href === printUrl(id) || x.url === printUrl(id)); assert.ok(w && w.name === 'goldenweb_print' && w.features === 'width=480,height=720', tag + ': ventana goldenweb_print 480×720: ' + JSON.stringify(w && [w.name, w.features]));
      // --- autoimpresión apagada (autorregistro encendido): 1 registro y NINGUNA impresión
      await prepare(timing, false, true);
      id = nextId(); await run(id); await advance(10);
      assert.strictEqual(registrations.filter((x) => x === id).length, 1, tag + ' (autoimpresión apagada): 1 registro: ' + events.join(' | '));
      assert.strictEqual(anyPrint(), 0, tag + ' (autoimpresión apagada): ninguna impresión: ' + events.join(' | '));
      assert.strictEqual(blankLeft(), 0, tag + ' (autoimpresión apagada): sin ventanas en blanco');
      cases += 2;
    }
  }

  // ---- el digitador (sin selector de estado): editar y guardar a alguien que no llegó lo deja Registrado y también imprime una vez
  const Gd = loadDir('digitador');
  els.tbody = new El('tbody'); els.cedula = new El('input'); els.hint = new El('p');
  d = Gd.mountSearch({ tbodyId: 'tbody', unified: true, fastCheckin: true, searchIds: { cedula: 'cedula', nombre: 'searchNombre', entidad: 'searchEntidad' } });
  d.openEditFor = Gd.openEdit;
  await d.reload(); await advance(10);
  for (const timing of ['vivo', 'activa']) {
    await prepare(timing, true, true);
    let id = nextId(); await openEditAndSave(id); await advance(10);
    assert.strictEqual(registrations.filter((x) => x === id).length, 1, `[${timing}] digitador editar: 1 registro: ` + events.join(' | '));
    assert.strictEqual(printsOf(id), 1, `[${timing}] digitador editar: 1 impresión: ` + events.join(' | '));
    assert.strictEqual(anyPrint(), 1); assert.strictEqual(blankLeft(), 0);
    await prepare(timing, false, true);
    id = nextId(); await openEditAndSave(id); await advance(10);
    assert.strictEqual(registrations.filter((x) => x === id).length, 1, `[${timing}] digitador editar (sin autoimpresión): 1 registro`);
    assert.strictEqual(anyPrint(), 0, `[${timing}] digitador editar (sin autoimpresión): ninguna impresión: ` + events.join(' | '));
    assert.strictEqual(blankLeft(), 0);
    cases += 2;
  }

  // ---- Enter con un NOMBRE (buscador único): solo busca; no acredita ni imprime (con ambos modos activos)
  const G2 = loadDir('coordinador');
  els.tbody = new El('tbody'); els.cedula = new El('input'); els.hint = new El('p');
  d = G2.mountSearch({ tbodyId: 'tbody', unified: true, fastCheckin: true, searchIds: { cedula: 'cedula', nombre: 'searchNombre', entidad: 'searchEntidad' } });
  await d.reload(); await advance(10);
  await prepare('activa', true, true);
  els.cedula.value = 'carlos'; enter('carlos'); await advance(10);
  assert.strictEqual(checkinCalls.length, 0, 'Enter con un nombre no llama a checkin-cedula: ' + events.join(' | '));
  assert.strictEqual(registrations.length, 0, 'y no registra a nadie');
  assert.strictEqual(anyPrint(), 0, 'y no imprime: ' + events.join(' | '));
  assert.strictEqual(wins.length, 0, 'ni siquiera prepara una ventana');
  assert.strictEqual(els.cedula.value, 'carlos', 'y deja el texto para seguir buscando');
  assert.deepStrictEqual(rows().map((tr) => tr.dataset.userId), ['4001'], 'la búsqueda por nombre filtró la lista');
  enter('Carlos Mejía'); await advance(10);                           // nombre completo con espacios: tampoco
  assert.strictEqual(checkinCalls.length, 0); assert.strictEqual(anyPrint(), 0);

  // ---- «Editar» y «🖨️ Imprimir» de cada fila siguen ahí y funcionando con autoimpresión + autorregistro activos
  els.cedula.value = ''; await typeIn('');
  await prepare('activa', true, true);
  assert.ok(rows().length >= 10, 'hay filas');
  for (const tr of rows()) {
    assert.ok(accBtn(tr), 'botón Acreditar presente');
    const pb = printBtn(tr), eb = editBtn(tr);
    assert.ok(pb && eb, 'la fila ' + tr.dataset.userId + ' conserva «Imprimir» y «Editar» a la vista');
    assert.strictEqual(pb.innerText, 'Imprimir'); assert.strictEqual(pb.disabled, false); assert.notStrictEqual(pb.style.display, 'none');
    assert.strictEqual(eb.disabled, false); assert.notStrictEqual(eb.style.display, 'none');
  }
  const tr0 = rows()[0], id0 = tr0.dataset.userId;
  reset(); printBtn(tr0).listeners.click(); await advance(10);                       // el botón manual sigue abriendo la ventana de impresión de siempre
  assert.strictEqual(anyPrint(), 1, 'el botón «Imprimir» imprime: ' + events.join(' | '));
  assert.ok(events.includes('open:' + printUrl(id0)) || events.includes('nav:' + printUrl(id0)));
  assert.strictEqual(wins[0].name, 'goldenweb_print'); assert.strictEqual(wins[0].features, 'width=480,height=720');
  const before = body.children.length; editBtn(rows()[1]).listeners.click();
  assert.strictEqual(body.children.length, before + 1, 'el botón «Editar» abre el cuadro de edición');
  body.children[body.children.length - 1].remove();
  console.log(`autoprint_matrix OK (${cases} casos de la matriz)`);
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
