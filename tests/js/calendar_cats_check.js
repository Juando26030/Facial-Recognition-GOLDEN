// Categorías de evento del Calendario (Fase 10, C): static/js/calendar-cats.js. Correr: node tests/js/calendar_cats_check.js
const assert = require('assert');
const C = require('../../static/js/calendar-cats.js');
const evs = [
  { id: 1, status: 'en_proceso', state_id: 7, state_name: 'Montaje', state_color: '#ff8800' },
  { id: 2, status: 'en_proceso', state_id: 7, state_name: 'Montaje', state_color: '#ff8800' },
  { id: 3, status: 'creado', state_id: null, state_name: null },
  { id: 4, status: 'finalizado' },
];
assert.deepStrictEqual(C.categoryOf(evs[0]), { key: 's7', label: 'Montaje', color: '#ff8800' });
assert.deepStrictEqual(C.categoryOf(evs[2]), { key: 'st:creado', label: 'Creado', color: '' });
let active = new Set();
let list = C.build(evs, active);
assert.deepStrictEqual(list.map((c) => [c.label, c.count, c.active]), [['Creado', 1, false], ['Finalizado', 1, false], ['Montaje', 2, false]]);
assert.ok(evs.every((e) => C.matches(e, active)), 'ninguna activa = se ven todas');
active = C.toggle(active, 's7');
assert.deepStrictEqual(evs.filter((e) => C.matches(e, active)).map((e) => e.id), [1, 2]);
active = C.toggle(active, 'st:creado');                                   // varias a la vez
assert.deepStrictEqual(evs.filter((e) => C.matches(e, active)).map((e) => e.id), [1, 2, 3]);
active = C.toggle(C.toggle(active, 's7'), 'st:creado');                    // quitar las dos: vuelven todas
assert.strictEqual(active.size, 0); assert.ok(evs.every((e) => C.matches(e, active)));
// una activa que ya no tiene eventos en el periodo sigue visible (para poder quitarla)
const kept = C.build([evs[3]], new Set(['s9', 'st:creado']));
assert.ok(kept.some((c) => c.key === 's9' && c.active && c.count === 0) && kept.some((c) => c.key === 'st:creado' && c.label === 'Creado' && c.active));
assert.deepStrictEqual(C.build([], new Set()), []);
console.log('calendar_cats_check OK');
