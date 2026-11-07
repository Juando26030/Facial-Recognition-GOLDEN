// Prueba de la lógica pura de static/js/gw-combobox.js (sin DOM). Correr: node tests/js/gw_combobox_check.js
const assert = require('assert');
const cb = require('../../static/js/gw-combobox.js');

const opts = [
  { value: 1, label: 'Éxito S.A.' }, { value: 2, label: 'Banco de Occidente' }, { value: 3, label: 'Corferias' },
  { value: 4, label: 'Cámara de Comercio de Bogotá', hint: '900123' }, { value: 5, label: 'Alcaldía de Medellín' },
];

assert.strictEqual(cb.normalize('  CÁMARA   de  Comercio '), 'camara de comercio');
assert.strictEqual(cb.normalize(null), '');

// Sin texto: todo, en el orden original.
assert.deepStrictEqual(cb.filterOptions(opts, '').map(o => o.value), [1, 2, 3, 4, 5]);
// Sin tildes ni mayúsculas.
assert.deepStrictEqual(cb.filterOptions(opts, 'exito').map(o => o.value), [1]);
assert.deepStrictEqual(cb.filterOptions(opts, 'CAMARA').map(o => o.value), [4]);
// Todas las palabras, en cualquier orden.
assert.deepStrictEqual(cb.filterOptions(opts, 'bogota camara').map(o => o.value), [4]);
// Mejor primero: empieza igual (0) antes que palabra (1) antes que contiene (2).
const r = cb.filterOptions([{ value: 'a', label: 'Hotel Cor' }, { value: 'b', label: 'Escorial' }, { value: 'c', label: 'Corferias' }], 'cor').map(o => o.value);
assert.deepStrictEqual(r, ['c', 'a', 'b']);
// La pista (hint) también se busca.
assert.deepStrictEqual(cb.filterOptions(opts, '900123').map(o => o.value), [4]);
// Sin coincidencias y límite.
assert.deepStrictEqual(cb.filterOptions(opts, 'zzz'), []);
assert.strictEqual(cb.filterOptions(opts, '', 2).length, 2);
assert.deepStrictEqual(cb.filterOptions(undefined, 'a'), []);

// Flechas: dan la vuelta y arrancan en el extremo correcto.
assert.strictEqual(cb.moveIndex(-1, 1, 3), 0);
assert.strictEqual(cb.moveIndex(-1, -1, 3), 2);
assert.strictEqual(cb.moveIndex(2, 1, 3), 0);
assert.strictEqual(cb.moveIndex(0, -1, 3), 2);
assert.strictEqual(cb.moveIndex(0, 1, 0), -1);

// Resolver lo escrito: exacto (sin tildes) / texto libre / nada.
assert.deepStrictEqual(cb.resolveText(opts, 'exito s.a.', false), { value: 1, label: 'Éxito S.A.', free: false });
assert.strictEqual(cb.resolveText(opts, 'Exi', false), null);
assert.deepStrictEqual(cb.resolveText(opts, ' Soacha ', true), { value: 'Soacha', label: 'Soacha', free: true });
assert.strictEqual(cb.resolveText(opts, '   ', true), null);
assert.strictEqual(cb.resolveText(opts, 'Corferias', true).free, false);

console.log('gw_combobox_check OK');
