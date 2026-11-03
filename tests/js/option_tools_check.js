// P7: funciones puras del editor de opciones (static/js/option-tools.js). Correr: node tests/js/option_tools_check.js
const assert = require('assert');
const T = require('../../static/js/option-tools.js');

assert.deepStrictEqual(T.list(' A \n\nB\r\n'), ['A', 'B']);
assert.deepStrictEqual(T.dedupe(['Bogotá', 'bogota ', 'Cali', 'CALI', 'Apartadó']), ['Bogotá', 'Cali', 'Apartadó'], 'repetidas ignorando tildes, mayúsculas y espacios; queda la primera');
assert.deepStrictEqual(T.sortAZ(['Zipaquirá', 'Álvaro', 'bogotá', 'Cali']), ['Álvaro', 'bogotá', 'Cali', 'Zipaquirá'], 'A–Z sin que la tilde ni la mayúscula cambien el orden');
assert.deepStrictEqual(T.move(['a', 'b', 'c'], 1, -1), ['b', 'a', 'c']);
assert.deepStrictEqual(T.move(['a', 'b', 'c'], 0, -1), ['a', 'b', 'c'], 'no sale por arriba');
assert.deepStrictEqual(T.move(['a', 'b', 'c'], 2, 1), ['a', 'b', 'c'], 'ni por abajo');

const groups = [
  { suggested: 'Apartadó', count: 3, values: [{ value: 'Apartadó', count: 3 }] },
  { suggested: 'Bogotá', count: 8, values: [{ value: 'Bogotá', count: 5 }, { value: 'Bogota', count: 3 }] },
  { suggested: 'Cali', count: 1, values: [{ value: 'Cali', count: 1 }] },
];
// primera vez: todo marcado, se usa la variante sugerida
let rows = T.plan(groups, [], false);
assert.ok(rows.every((r) => r.checked && !r.isNew));
assert.deepStrictEqual(T.result(rows, []), ['Apartadó', 'Bogotá', 'Cali']);
// primera vez con algo escrito a mano que la base no tiene: se conserva al final
assert.deepStrictEqual(T.result(T.plan(groups, ['Otro'], false), ['Otro']), ['Apartadó', 'Bogotá', 'Cali', 'Otro']);
// elegir la otra variante
rows[1].chosen = 'Bogota';
assert.deepStrictEqual(T.result(rows, []), ['Apartadó', 'Bogota', 'Cali']);
// actualizar: lo que ya estaba queda marcado con SU texto; lo nuevo, sin marcar y avisado; no se actualiza solo
rows = T.plan(groups, ['Bogota', 'Medellín'], true);
assert.deepStrictEqual(rows.map((r) => [r.checked, r.isNew, r.chosen]), [[false, true, 'Apartadó'], [true, false, 'Bogota'], [false, true, 'Cali']]);
assert.deepStrictEqual(T.result(rows, ['Bogota', 'Medellín']), ['Bogota', 'Medellín'], 'lo escrito a mano que la base no tiene se conserva; lo nuevo no entra sin marcarlo');
rows[0].checked = true;
assert.deepStrictEqual(T.result(rows, ['Bogota', 'Medellín']), ['Apartadó', 'Bogota', 'Medellín']);
// campos que identifican personas: el botón no se ofrece
['id', 'first_name', 'last_name', 'email', 'phone', 'birth_date'].forEach((k) => assert.ok(T.BLOCKED.includes(k), k));
console.log('option_tools_check OK');
