// P1 formularios: una fila cuyos campos están TODOS ocultos por reglas se oculta entera (sin su margen de 14 px).
// Necesita jsdom (no es dependencia del repo): NODE_PATH=<carpeta con node_modules/jsdom> node tests/js/form_rows_hidden_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); } catch (e) { console.log('SKIP: jsdom no está instalado'); process.exit(0); }

const dom = new JSDOM('<div id="h"></div>', { runScripts: 'outside-only' });
dom.window.eval(fs.readFileSync(path.join(__dirname, '../../static/js/form-render.js'), 'utf8'));
const f = (id, v) => ({ id, type: 'paragraph', label: id, content: id, show_if: { field: 'c', op: 'equals', value: v } });
const design = {
  theme: {},
  fields: { c: { id: 'c', type: 'select', label: 'Ciudad', options: ['Bogotá', 'Apartadó'] }, a: f('a', 'Bogotá'), b: f('b', 'Apartadó'), d: f('d', 'Bogotá'), e: f('e', 'Apartadó') },
  rows: [{ items: ['c'] }, { items: ['a'] }, { items: ['b'] }, { items: ['d', 'e'] }],
};
dom.window.FormRender.render(dom.window.document.getElementById('h'), design, { previewOnly: true });
const rows = () => Array.from(dom.window.document.querySelectorAll('.fr-row')).map((r) => (r.style.display === 'none' ? 'x' : 'v')).join('');
const pick = (v) => { const s = dom.window.document.querySelector('select'); s.value = v; s.dispatchEvent(new dom.window.Event('input', { bubbles: true })); };

assert.strictEqual(rows(), 'vxxx', 'sin ciudad: solo la fila de la ciudad');
pick('Bogotá'); assert.strictEqual(rows(), 'vvxv', 'Bogotá: su fila y la mixta (basta un campo visible)');
pick('Apartadó'); assert.strictEqual(rows(), 'vxvv');
pick(''); assert.strictEqual(rows(), 'vxxx', 'vuelve a ocultarse');
console.log('form_rows_hidden_check OK');
