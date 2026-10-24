// Matriz de caminos de impresión SIN duplicados (orden B, 23-oct-2026). Se corre con: node tests/js/print_dispatch_matrix_check.js
// «Dos pestañas» = dos copias de static/js/badge-render.js (cada una con su propia memoria) que comparten el MISMO navigator.locks y el mismo localStorage, como dos pestañas de un equipo.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const code = fs.readFileSync(path.resolve(__dirname, '../../static/js/badge-render.js'), 'utf8');
const held = new Set();
const sharedLocks = {                               // Web Locks: un candado con nombre lo tiene UNA sola pestaña a la vez (ifAvailable)
  request(name, opts, cb) {
    if (held.has(name)) return Promise.resolve(cb(null));
    held.add(name);
    return Promise.resolve(cb({ name })).finally(() => held.delete(name));
  },
};

function tab(name, { locks = sharedLocks, clock } = {}) {
  const log = { opened: [], logged: [], counts: 0 };
  const win = {
    EVENT_ID: 7, EVENT_AUTO_PRINT: true, STAFF_ROLE: 'digitador',
    open: (url) => { log.opened.push(url); },
    showConfirm: async () => true,
    navigator: { locks },
    fetch: async (url, init = {}) => {
      if (/print-log/.test(url)) { log.logged.push(url); return { ok: true, json: async () => ({}) }; }
      if (/print-count/.test(url)) { log.counts++; return { ok: true, json: async () => ({ times_printed: 0 }) }; }
      return { ok: true, json: async () => ({}) };
    },
    setTimeout: (f, ms) => { const t = setTimeout(f, ms); t.unref && t.unref(); return t; },
  };
  win.window = win;
  const ctx = vm.createContext(Object.assign(win, { document: {}, console, Date: clock || Date, Map, Set, Promise, encodeURIComponent, setTimeout: win.setTimeout }));
  vm.runInContext(code, ctx);
  return { name, BP: win.window.BadgePrint, win, log };
}
const settle = () => new Promise((r) => setTimeout(r, 25));

(async () => {
  // 1) misma pestaña: tres llamadas casi a la vez (doble clic en «Acreditar», lector repetido, refresco) → UNA impresión
  let a = tab('A');
  a.BP.maybeAutoPrint('1001'); a.BP.maybeAutoPrint('1001'); a.BP.maybeAutoPrint('1001');
  await settle();
  assert.strictEqual(a.log.opened.length, 1, 'tres llamadas, una impresión');
  assert.strictEqual(a.log.logged.length, 1, 'y una sola anotación en el historial');

  // 2) otra persona en la misma pestaña sí imprime
  a.BP.maybeAutoPrint('1002'); await settle();
  assert.strictEqual(a.log.opened.length, 2);

  // 3) dos pestañas del mismo equipo (comparten candados): la misma persona → solo UNA de las dos imprime
  held.clear();
  const t1 = tab('T1'), t2 = tab('T2');
  t1.BP.maybeAutoPrint('2001'); t2.BP.maybeAutoPrint('2001');
  await settle();
  assert.strictEqual(t1.log.opened.length + t2.log.opened.length, 1, 'dos pestañas, una impresión');

  // 4) auto-impresión apagada: nada
  const off = tab('OFF'); off.win.EVENT_AUTO_PRINT = false;
  off.BP.maybeAutoPrint('3001'); await settle();
  assert.strictEqual(off.log.opened.length, 0);

  // 5) botón «Imprimir» manual: doble toque rápido = UNA ventana; pasados 3 s, otra (es una reimpresión consciente, con su aviso de «ya se imprimió»)
  const m = tab('M');
  await Promise.all([m.BP.openPrintWindow('4001'), m.BP.openPrintWindow('4001')]);
  assert.strictEqual(m.log.opened.length, 1, 'doble toque en el botón, una impresión');
  assert.strictEqual(m.log.counts, 1, 'y una sola consulta de cuántas veces se imprimió');

  // 6) el botón y la auto-impresión son caminos distintos: la auto-impresión de una persona NO bloquea que el botón imprima (reimpresión explícita), y no se duplica la auto
  const x = tab('X');
  x.BP.maybeAutoPrint('5001'); await settle();
  await x.BP.openPrintWindow('5001');
  assert.strictEqual(x.log.opened.length, 2, 'auto + botón explícito = dos (el botón avisa «ya se imprimió» antes en la pantalla real)');
  x.BP.maybeAutoPrint('5001'); await settle();
  assert.strictEqual(x.log.opened.length, 2, 'otra auto-impresión de la misma persona dentro de la ventana no imprime');

  // 7) pasada la ventana (30 s) la misma persona puede volver a imprimirse sola (otro evento de registro legítimo)
  let now = 1_000_000;
  const clock = class extends Date { static now() { return now; } };
  held.clear();
  const w = tab('W', { clock });
  w.BP.maybeAutoPrint('6001'); await settle();
  assert.strictEqual(w.log.opened.length, 1);
  now += 31_000; held.clear();                                       // pasó la ventana y el candado se soltó
  w.BP.maybeAutoPrint('6001'); await settle();
  assert.strictEqual(w.log.opened.length, 2, 'pasada la ventana, se vuelve a permitir');

  // 8) sin Web Locks (navegador viejo): sigue la protección en memoria de la pestaña
  const nl = tab('NL', { locks: undefined });
  nl.BP.maybeAutoPrint('7001'); nl.BP.maybeAutoPrint('7001'); await settle();
  assert.strictEqual(nl.log.opened.length, 1);

  // 9) printNow (el repliegue del despachador cuando falla el USB) imprime sin pedir otro permiso
  const pn = tab('PN');
  await pn.BP.printNow('8001');
  assert.strictEqual(pn.log.opened.length, 1);
  console.log('print_dispatch_matrix_check OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
