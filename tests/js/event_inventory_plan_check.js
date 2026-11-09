// Bloque de inventario del evento: qué líneas viajan al guardar (solo las que cambiaron; en borrador solo las que tienen algo).
const assert = require('assert');
const { rowsToPayload } = require('../../static/js/event-inventory-plan.js');

const loaded = [{ product_id: 1, assigned: 5, out: 0, returned: 0, consumed: 0, notes: '', attrs: {} }, { product_id: 2, assigned: 0, out: 0, returned: 0, consumed: 0, notes: '', attrs: {} }];

// sin cambios no viaja nada
assert.deepStrictEqual(rowsToPayload(loaded.map((l) => ({ ...l })), loaded), []);
// cambiar lo que salió: viaja la línea con «out» (y la asignada tal cual)
let got = rowsToPayload([{ ...loaded[0], out: 5 }, loaded[1]], loaded);
assert.strictEqual(got.length, 1);
assert.deepStrictEqual({ id: got[0].product_id, assigned: got[0].assigned, out: got[0].out, returned: got[0].returned }, { id: 1, assigned: 5, out: 5, returned: undefined });
// un número raro se vuelve 0 y no rompe
got = rowsToPayload([{ ...loaded[0], assigned: 'abc' }, loaded[1]], loaded);
assert.strictEqual(got[0].assigned, 0);
// campos propios y notas cuentan como cambio
got = rowsToPayload([loaded[0], { ...loaded[1], attrs: { marca: 'Dell' }, notes: 'nuevo' }], loaded);
assert.strictEqual(got.length, 1);
assert.deepStrictEqual(got[0].attrs, { marca: 'Dell' });
// borrador: solo las que tienen algo, y nunca manda salió/volvió/consumido
got = rowsToPayload([{ product_id: 7, assigned: 3, out: 9, returned: 0, consumed: 0, notes: '', attrs: {} }, { product_id: 8, assigned: 0, out: 0, returned: 0, consumed: 0, notes: '', attrs: {} }], [], { draft: true });
assert.strictEqual(got.length, 1);
assert.strictEqual(got[0].product_id, 7);
assert.ok(!('out' in got[0]));
console.log('event_inventory_plan_check ok');
