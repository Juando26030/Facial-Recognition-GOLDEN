// P6: las reglas comparan sin tildes, mayúsculas ni espacios de más (navegador); y FormSync (opciones de la regla, sincronizar con Parámetros).
// Los mismos casos de comparación están en tests/test_forms.py (servidor). Correr: node tests/js/form_rules_norm_check.js
const assert = require('assert');
const { conditionMet } = require('../../static/js/form-render.js');
const S = require('../../static/js/form-sync.js');

const rule = (op, value) => ({ field: 'c', op, value });
const met = (op, value, have) => conditionMet(rule(op, value), { c: have });
assert.ok(met('equals', 'Bogotá', 'Bogota'), 'tilde');
assert.ok(met('equals', 'Bogota', ' BOGOTÁ  '), 'mayúsculas y espacios');
assert.ok(met('equals', 'Apartado', 'apartadó'));
assert.ok(met('equals', 'San  Andrés', 'san andres'), 'espacios internos');
assert.ok(!met('equals', 'Bogotá', 'Medellín'));
assert.ok(met('equals', 'Bogotá', 'Bogotá'), 'valor exacto sigue igual');
assert.ok(met('not_equals', 'Bogotá', 'Cali') && !met('not_equals', 'Bogotá', 'bogota'));
assert.ok(met('contains', 'necocli', 'Necoclí - Antioquia'));
assert.ok(met('in', ['Bogotá', 'Apartadó'], 'apartado') && !met('in', ['Bogotá'], 'Cali'));
assert.ok(met('in', ['Bogotá'], ['Cali', 'bogota']), 'lista de respuestas (multiselect)');
assert.ok(met('filled', '', 'x') && !met('filled', '', ''));
assert.ok(!met('equals', 'Ñandú', 'Nandu') === false, 'ñ se trata como n (igual que el servidor)');

// FormSync
const ev = [{ key: 'opcional_1', label: 'Ciudad', type: 'select', options: ['Bogotá', 'Apartadó'] }, { key: 'phone', label: 'Teléfono', type: 'phone', options: [] }];
assert.deepStrictEqual(S.optionsOf({ type: 'text_short', key: 'opcional_1' }, ev), ['Bogotá', 'Apartadó'], 'opciones del campo del evento');
assert.deepStrictEqual(S.optionsOf({ type: 'select', key: 'opcional_1', options: ['A'] }, ev), ['A'], 'las propias mandan');
assert.strictEqual(S.optionsOf({ type: 'text_short', key: 'phone' }, ev), null);
assert.strictEqual(S.optionsOf({ type: 'text_short' }, ev), null);
assert.strictEqual(S.findOption(['Bogotá'], 'bogota'), 'Bogotá');
assert.strictEqual(S.findOption(['Bogotá'], 'Cali'), undefined);

const design = { fields: {
  a: { id: 'a', type: 'text_short', label: 'Ciudad', key: 'opcional_1' },
  b: { id: 'b', type: 'radio', label: 'Ciudad 2', key: 'opcional_1', options: ['Bogotá'] },
  c: { id: 'c', type: 'select', label: 'Ciudad 3', key: 'opcional_1', options: ['Bogotá', 'Apartadó'] },
  d: { id: 'd', type: 'text_short', label: 'Tel', key: 'phone' },
  e: { id: 'e', type: 'text_short', label: 'Libre' } } };
const snapshot = JSON.stringify(design);
const plan = S.plan(design, ev);
assert.strictEqual(JSON.stringify(design), snapshot, 'plan no cambia nada');
assert.deepStrictEqual(plan.map((p) => p.id), ['a', 'b'], 'c ya está al día; d y e no cambian');
assert.strictEqual(plan[0].type, 'select'); assert.deepStrictEqual(plan[0].options, ['Bogotá', 'Apartadó']);
assert.strictEqual(plan[1].type, undefined, 'una opción única sigue siendo opción única'); assert.deepStrictEqual(plan[1].options, ['Bogotá', 'Apartadó']);
S.apply(design, plan);
assert.strictEqual(design.fields.a.type, 'select'); assert.deepStrictEqual(design.fields.a.options, ['Bogotá', 'Apartadó']);
assert.strictEqual(design.fields.b.type, 'radio');
assert.deepStrictEqual(S.plan(design, ev), [], 'tras sincronizar no queda nada');
console.log('form_rules_norm_check OK');
