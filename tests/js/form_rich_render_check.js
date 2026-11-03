// P3: el renderizador pinta texto con formato limpio y los textos viejos EXACTAMENTE como antes. Correr: npm ci && node tests/js/form_rich_render_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const dom = new JSDOM('<!doctype html><body><div id="h"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(root, f), 'utf8')));

const design = {
  theme: {},
  fields: {
    old: { id: 'old', type: 'paragraph', content: 'menores de <18 años\nsegunda línea' },
    rich: { id: 'rich', type: 'paragraph', content: '<b>Negrilla</b><script>alert(1)</script><span style="color:#d4af37">oro</span>' },
    ttl: { id: 'ttl', type: 'heading', content: 'Título viejo' },
    ttl2: { id: 'ttl2', type: 'heading', content: '<i onclick="x()">Título nuevo</i>' },
    n: { id: 'n', type: 'text_short', label: 'Nombre', help: '<b>ojo</b><img src=x onerror=alert(1)> con <18' },
    n2: { id: 'n2', type: 'text_short', label: 'Edad', help: 'Solo texto <18' },
  },
  rows: ['old', 'rich', 'ttl', 'ttl2', 'n', 'n2'].map((i) => ({ items: [i] })),
};
w.FormRender.render(w.document.getElementById('h'), design, { previewOnly: true });
const item = (id) => w.document.querySelector(`[data-fid="${id}"]`);

assert.strictEqual(item('old').innerHTML, '<p style="margin:0; white-space:pre-wrap; opacity:.85;">menores de &lt;18 años\nsegunda línea</p>', 'texto viejo: el mismo HTML de siempre');
assert.strictEqual(item('ttl').innerHTML, '<h3 style="margin:8px 0 2px;">Título viejo</h3>', 'título viejo igual que antes');
assert.ok(item('rich').innerHTML.includes('<b>Negrilla</b>') && item('rich').innerHTML.includes('color:#d4af37') && !item('rich').innerHTML.includes('script'));
assert.ok(item('ttl2').innerHTML.includes('<i>Título nuevo</i>') && !item('ttl2').innerHTML.includes('onclick'));
assert.ok(item('n').innerHTML.includes('<b>ojo</b>') && !item('n').innerHTML.includes('<img') && !item('n').innerHTML.includes('onerror'));
assert.ok(item('n2').innerHTML.includes('Solo texto &lt;18'), 'ayuda vieja igual');
assert.strictEqual(w.document.querySelectorAll('script').length, 0);
console.log('form_rich_render_check OK');
