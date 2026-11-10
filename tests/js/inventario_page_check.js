// Fase 10 (A): funciones puras de la pantalla /inventario (calendario y catálogo) y de Parámetros (permanencia). Sin jsdom: se cargan en un contexto vacío.
const assert = require('assert');
const same = (a, b) => assert.strictEqual(JSON.stringify(a), JSON.stringify(b));          // los objetos vienen de otro contexto de vm
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function load(file) {
  const ctx = vm.createContext({ globalThis: null });
  ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', file), 'utf8'), ctx);
  return ctx;
}

const P = load('inventario-page.js').GWInvPage;
assert.ok(P, 'GWInvPage expuesto');
assert.strictEqual(P.addDays('2026-11-30', 1), '2026-12-01');
assert.strictEqual(P.addDays('2026-03-01', -1), '2026-02-28');
assert.strictEqual(P.mondayOf('2026-11-10'), '2026-11-09');          // martes -> lunes
assert.strictEqual(P.mondayOf('2026-11-15'), '2026-11-09');          // domingo -> lunes anterior
assert.strictEqual(P.monthStart('2026-11-10'), '2026-11-01');
assert.strictEqual(P.addMonths('2026-01-31', 1), '2026-02-01');
assert.strictEqual(P.addMonths('2026-12-15', 1), '2027-01-01');
const m = P.rangeFor('month', '2026-11-10');
assert.strictEqual(m.start, '2026-10-26'); assert.strictEqual(m.end, '2026-12-06');
assert.strictEqual(P.gridDays('month', '2026-11-10').length, 42);
same(P.rangeFor('week', '2026-11-10'), { start: '2026-11-09', end: '2026-11-15' });
assert.strictEqual(P.titleFor('month', '2026-11-10'), 'noviembre de 2026');
assert.strictEqual(P.titleFor('day', '2026-11-10'), 'martes 10 de noviembre de 2026');

const ev = [
  { id: 1, start: '2026-11-08', end: '2026-11-12', lines: [{ product_id: 7, assigned: 3 }] },
  { id: 2, start: '2026-11-12', end: '2026-11-13', lines: [{ product_id: 8, assigned: 1 }] },
];
same(P.eventsOn(ev, '2026-11-12', 0).map((e) => e.id), [1, 2]);
same(P.eventsOn(ev, '2026-11-12', 8).map((e) => e.id), [2]);
same(P.eventsOn(ev, '2026-11-14', 0), []);
const daily = { '2026-11-12': { 7: 3, 8: 1 } };
assert.strictEqual(P.usedOn(daily, '2026-11-12', 7), 3);
assert.strictEqual(P.usedOn(daily, '2026-11-13', 7), 0);
assert.strictEqual(P.availOn(10, 3), 7);
assert.strictEqual(P.availOn(null, 3), null);
same(P.shortOn(daily, '2026-11-12', [{ id: 7, stock: 2 }, { id: 8, stock: 5 }, { id: 9, stock: null }]).map((p) => p.id), [7]);

const cat = { categories: [{ id: 1, name: 'Audio' }, { id: 2, name: 'Luces' }], products: [
  { id: 7, name: 'Parlante', sku: 'P-1', category_id: 1 }, { id: 8, name: 'Foco', sku: null, category_id: 2 }, { id: 9, name: 'Cable', sku: null, category_id: null }] };
same(P.groupCatalog(cat, '', '').map((g) => g.name), ['Audio', 'Luces', 'Sin categorizar']);
same(P.groupCatalog(cat, 'par', '').map((g) => g.name), ['Audio']);
same(P.groupCatalog(cat, 'p-1', '').map((g) => g.name), ['Audio']);
same(P.groupCatalog(cat, '', '2').map((g) => g.name), ['Luces']);

const D = load('dwell-params.js').GWDwell;
assert.ok(D);
assert.strictEqual(D.toMinutes(24, 0), 1440);
assert.strictEqual(D.toMinutes('', ''), null);
assert.strictEqual(D.toMinutes(1, 30), 90);
same(D.splitMinutes(90), { h: 1, m: 30 });
assert.strictEqual(D.fmtMinutes(1440), '24 h');
assert.strictEqual(D.fmtMinutes(125), '2 h 05 min');
assert.strictEqual(D.fmtMinutes(45), '45 min');
console.log('inventario_page_check: OK');
