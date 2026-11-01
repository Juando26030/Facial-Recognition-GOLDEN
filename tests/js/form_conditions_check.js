// P9: condiciones en árbol Y/O (mismos casos que tests/test_form_variants.py, vía tests/cond_vectors.json). Correr: node tests/js/form_conditions_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { condTree, variantsOf, pickVariant } = require('../../static/js/form-render.js');

const V = JSON.parse(fs.readFileSync(path.join(__dirname, '../cond_vectors.json'), 'utf8'));
V.eval.forEach((c) => {
  const visible = c.visible ? new Set(c.visible) : new Set(['c', 't', 'e']);
  assert.strictEqual(condTree(c.tree, (id) => visible.has(id), c.values), c.expected, c.name);
});

// formato de P2: se lee como la propiedad content
const legacy = { variants: { by: 'c', items: [{ rule: { field: 'c', op: 'equals', value: 'Bogotá' }, content: 'Sede' }], default: 'd' } };
assert.deepStrictEqual(variantsOf(legacy), { content: { items: [{ when: { field: 'c', op: 'equals', value: 'Bogotá' }, value: 'Sede' }], default: 'd' } });
assert.strictEqual(pickVariant(legacy, 'content', { c: 'bogota' }, () => true), 'Sede');
assert.strictEqual(pickVariant(legacy, 'content', { c: 'Cali' }, () => true), 'd');

// selección: primera que se cumple, luego el valor por defecto; content/src sin nada = null; las demás propiedades, su valor propio
const r = (v) => ({ field: 'c', op: 'equals', value: v });
const f = { content: 'base', src: 'a/x.png', help: 'ayuda base', variants: {
  content: { items: [{ when: r('Bogotá'), value: '' }, { when: r('Bogotá'), value: 'otra' }, { when: r('Cali'), value: 'Cali!' }] },
  src: { items: [{ when: r('Bogotá'), value: 'a/b.png' }], default: 'a/d.png' },
  help: { items: [{ when: r('Cali'), value: 'ayuda Cali' }] } } };
const pick = (prop, c, vis) => pickVariant(f, prop, { c }, vis || (() => true));
assert.strictEqual(pick('content', 'Bogotá'), null, 'una variante que coincide con valor vacío oculta el elemento y gana la primera');
assert.strictEqual(pick('content', 'Cali'), 'Cali!');
assert.strictEqual(pick('content', 'Pasto'), null, 'sin variante ni por defecto: no ocupa espacio');
assert.strictEqual(pick('src', 'Bogotá'), 'a/b.png');
assert.strictEqual(pick('src', 'Pasto'), 'a/d.png');
assert.strictEqual(pick('help', 'Cali'), 'ayuda Cali');
assert.strictEqual(pick('help', 'Pasto'), 'ayuda base', 'la ayuda cae a su valor propio');
assert.strictEqual(pick('help', 'Cali', () => false), 'ayuda base', 'campo que decide oculto: la hoja no cuenta');
assert.strictEqual(pickVariant({ content: 'Hola' }, 'content', {}, () => true), 'Hola', 'sin variantes: su valor');
console.log('form_conditions_check OK');
