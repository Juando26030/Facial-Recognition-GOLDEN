// Categorías de evento del Calendario (Fase 10, C): static/js/calendar-cats.js. Correr: node tests/js/calendar_cats_check.js
const assert = require('assert');
const C = require('../../static/js/calendar-cats.js');
const evs = [
  { id: 1, status: 'en_proceso', event_type_id: 7, event_type_name: 'Feria', event_type_color: '#e8803a', state_name: 'Montaje' },
  { id: 2, status: 'creado', event_type_id: 7, event_type_name: 'Feria', event_type_color: '#e8803a' },
  { id: 3, status: 'creado', event_type_id: 2, event_type_name: 'Congreso', event_type_color: null },
  { id: 4, status: 'finalizado', event_type_id: null, event_type_name: null },
  { id: 5, status: 'creado' },
];
assert.deepStrictEqual(C.categoryOf(evs[0]), { key: 't7', label: 'Feria', color: '#e8803a' });
assert.deepStrictEqual(C.categoryOf(evs[3]), { key: 'none', label: 'Sin categoría', color: '' });
assert.strictEqual(C.categoryOf(evs[0]).label, 'Feria', 'ya NO es el estado: manda el tipo de evento');
let active = new Set();
let list = C.build(evs, active);
assert.deepStrictEqual(list.map((c) => [c.label, c.count, c.active]), [['Congreso', 1, false], ['Feria', 2, false], ['Sin categoría', 2, false]], 'alfabético y «Sin categoría» al final');
assert.ok(evs.every((e) => C.matches(e, active)), 'ninguna activa = se ven todas');
active = C.toggle(active, 't7');
assert.deepStrictEqual(evs.filter((e) => C.matches(e, active)).map((e) => e.id), [1, 2]);
active = C.toggle(active, 'none');                                        // varias a la vez
assert.deepStrictEqual(evs.filter((e) => C.matches(e, active)).map((e) => e.id), [1, 2, 4, 5]);
active = C.toggle(C.toggle(active, 't7'), 'none');
assert.strictEqual(active.size, 0); assert.ok(evs.every((e) => C.matches(e, active)));
// una activa que hoy no tiene eventos sigue visible, con el nombre que ya se conocía
const kept = C.build([evs[4]], new Set(['t9', 'none']), { t9: { label: 'Social', color: '#c2417c' } });
assert.ok(kept.some((c) => c.key === 't9' && c.label === 'Social' && c.active && c.count === 0) && kept.some((c) => c.key === 'none' && c.active && c.count === 1));
assert.deepStrictEqual(C.build([], new Set()), []);
console.log('calendar_cats_check OK');
