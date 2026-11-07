// P2/P9: variantes en el renderizador (jsdom): textos, imágenes, nombre, ayuda y texto de ejemplo; lo que la persona escribió no se pierde. Correr: npm ci && node tests/js/form_variants_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<!doctype html><body><div id="h"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(__dirname, '../..', f), 'utf8')));
const r = (v, op) => ({ field: 'c', op: op || 'equals', value: v });
const design = {
  theme: {},
  fields: {
    c: { id: 'c', type: 'select', label: 'Ciudad', options: ['Bogotá', 'Apartadó', 'Necoclí'] },
    t: { id: 't', type: 'paragraph', content: 'fijo', variants: { content: { items: [{ when: r('Bogotá'), value: 'Sede Bogotá' }, { when: r(['Apartadó', 'Necoclí'], 'in'), value: '<b>Sede Urabá</b>' }] } } },
    old: { id: 'old', type: 'paragraph', content: 'x', variants: { by: 'c', items: [{ rule: r('Bogotá'), content: 'formato P2' }] } },
    img: { id: 'img', type: 'image', src: 'acme/base.png', variants: { src: { items: [{ when: r('Bogotá'), value: 'acme/bogota.png' }] } } },
    n: { id: 'n', type: 'text_short', label: 'Nombre', required: true, help: 'ayuda base', placeholder: 'ej.', variants: {
      display_label: { items: [{ when: r('Bogotá'), value: '<b>Tu nombre en Bogotá</b>' }] },
      help: { items: [{ when: r('Bogotá'), value: '<i>ayuda Bogotá</i>' }] },
      placeholder: { items: [{ when: r('Bogotá'), value: 'Ana de Bogotá' }] } } },
    m: { id: 'm', type: 'text_short', label: 'Sin ayuda', variants: { help: { items: [{ when: r('Apartadó'), value: 'solo en Apartadó' }] } } },
    cb: { id: 'cb', type: 'checkbox', label: 'Acepto', variants: { display_label: { items: [{ when: r('Bogotá'), value: '<u>Acepto (Bogotá)</u>' }] } } },
  },
  rows: ['c', 't', 'old', 'img', 'n', 'm', 'cb'].map((i) => ({ items: [i] })),
};
w.FormRender.render(w.document.getElementById('h'), design, { previewOnly: true });
const doc = w.document, q = (id) => doc.querySelector(`[data-fid="${id}"]`), row = (id) => q(id).parentNode;
const pick = (v) => { const s = doc.querySelector('select[name=c]'); s.value = v; s.dispatchEvent(new w.Event('input', { bubbles: true })); };

// sin ciudad: lo que no tiene variante que aplique no ocupa espacio; los campos usan lo suyo
assert.strictEqual(row('t').style.display, 'none'); assert.strictEqual(row('old').style.display, 'none'); assert.strictEqual(row('img').style.display, 'none');
assert.ok(q('n').innerHTML.includes('Nombre') && q('n').innerHTML.includes('ayuda base') && q('n').querySelector('input').placeholder === 'ej.');
assert.strictEqual(q('m').querySelector('[data-hv]').style.display, 'none', 'ayuda solo de variante: oculta mientras no aplique');

q('n').querySelector('input').value = 'Lo que ya escribí';
pick('Bogotá');
assert.ok(row('t').textContent.includes('Sede Bogotá')); assert.ok(row('old').textContent.includes('formato P2'));
assert.ok(q('img').innerHTML.includes('acme/bogota.png') && row('img').style.display === '');
const lab = q('n').querySelector('[data-ttl]');
assert.ok(lab.innerHTML.includes('<b>Tu nombre en Bogotá</b>') && !lab.innerHTML.includes('*'), 'nombre con formato y sin asterisco (cara al público no hay asteriscos, 6-nov-2026)');
assert.ok(q('n').querySelector('[data-hv]').innerHTML.includes('<i>ayuda Bogotá</i>'));
assert.strictEqual(q('n').querySelector('input').placeholder, 'Ana de Bogotá');
assert.strictEqual(q('n').querySelector('input').value, 'Lo que ya escribí', 'cambiar de variante no borra lo escrito');
assert.ok(q('cb').querySelector('[data-ttl]').innerHTML.includes('<u>Acepto (Bogotá)</u>'));

pick('Necoclí');
assert.ok(row('t').textContent.includes('Sede Urabá') && q('t').querySelector('b'));
assert.strictEqual(row('old').style.display, 'none'); assert.strictEqual(row('img').style.display, 'none', 'sin variante de imagen ni por defecto: no ocupa espacio');
assert.ok(lab.innerHTML.includes('Nombre') && !lab.innerHTML.includes('Bogotá'), 'vuelve al nombre propio');
assert.strictEqual(q('n').querySelector('input').placeholder, 'ej.');
assert.strictEqual(q('n').querySelector('input').value, 'Lo que ya escribí');
pick('Apartadó');
assert.ok(q('m').querySelector('[data-hv]').innerHTML.includes('solo en Apartadó') && q('m').querySelector('[data-hv]').style.display === '');
console.log('form_variants_check OK');
