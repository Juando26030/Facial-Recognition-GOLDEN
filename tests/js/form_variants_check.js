// P2: texto con variantes en el renderizador (jsdom). Mismos casos que tests/test_form_variants.py. Correr: npm ci && node tests/js/form_variants_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const { pickVariant } = require('../../static/js/form-render.js');

const items = [
  { rule: { field: 'c', op: 'equals', value: 'Bogotá' }, content: 'Sede Bogotá' },
  { rule: { field: 'c', op: 'in', value: ['Apartadó', 'Necoclí'] }, content: 'Sede Urabá' },
];
const t = { id: 't', type: 'paragraph', content: 'fijo', variants: { by: 'c', items, default: 'Sede por confirmar' } };
const pick = (c, vis) => pickVariant(t, { c }, vis);
assert.strictEqual(pick('Bogotá'), 'Sede Bogotá');
assert.strictEqual(pick('bogota'), 'Sede Bogotá');
assert.strictEqual(pick('Apartado'), 'Sede Urabá');
assert.strictEqual(pick('Cali'), 'Sede por confirmar');
assert.strictEqual(pick('Bogotá', () => false), 'Sede por confirmar', 'campo que decide oculto: no cuenta');
assert.strictEqual(pickVariant({ ...t, variants: { items } }, { c: 'Cali' }), null, 'sin variante ni por defecto: nada');
assert.strictEqual(pickVariant({ content: 'Hola' }, {}), 'Hola', 'sin variantes: su texto');
assert.strictEqual(pickVariant({ variants: { items: [{ rule: { field: 'c', op: 'contains', value: 'a' }, content: 'uno' }, { rule: { field: 'c', op: 'equals', value: 'Bogotá' }, content: 'dos' }] } }, { c: 'Bogotá' }), 'uno', 'gana la primera');

// render real: lo que ve cada persona y el hueco
const dom = new JSDOM('<div id="h"></div>', { runScripts: 'outside-only' });
dom.window.eval(fs.readFileSync(path.join(__dirname, '../../static/js/form-render.js'), 'utf8'));
const design = {
  theme: {},
  fields: {
    c: { id: 'c', type: 'select', label: 'Ciudad', options: ['Bogotá', 'Apartadó', 'Necoclí'] },
    t: { ...t, variants: { by: 'c', items } },      // sin por defecto
    h: { id: 'h', type: 'heading', content: 'Fijo', show_if: null },
  },
  rows: [{ items: ['c'] }, { items: ['t'] }, { items: ['h'] }],
};
dom.window.FormRender.render(dom.window.document.getElementById('h'), design, { previewOnly: true });
const doc = dom.window.document;
const sel = doc.querySelector('select');
const pick2 = (v) => { sel.value = v; sel.dispatchEvent(new dom.window.Event('input', { bubbles: true })); };
const tRow = () => doc.querySelectorAll('.fr-row')[1];
assert.strictEqual(tRow().style.display, 'none', 'sin ciudad y sin texto por defecto: la fila no ocupa espacio');
pick2('Bogotá'); assert.strictEqual(tRow().style.display, ''); assert.ok(tRow().textContent.includes('Sede Bogotá'));
pick2('Necoclí'); assert.ok(tRow().textContent.includes('Sede Urabá') && !tRow().textContent.includes('Bogotá'));
pick2('Apartadó'); assert.ok(tRow().textContent.includes('Sede Urabá'));
pick2(''); assert.strictEqual(tRow().style.display, 'none');
assert.ok(doc.querySelectorAll('.fr-row')[2].textContent.includes('Fijo'), 'un título normal sigue igual');
console.log('form_variants_check OK');
