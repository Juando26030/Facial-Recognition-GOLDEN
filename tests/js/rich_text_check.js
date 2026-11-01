// P3: texto con formato en el navegador (jsdom): mismos casos que tests/test_richtext.py (tests/rich_vectors.json), pegado y editor.
// Correr: npm ci && node tests/js/rich_text_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const V = JSON.parse(fs.readFileSync(path.join(__dirname, '../rich_vectors.json'), 'utf8'));
const dom = new JSDOM('<!doctype html><body><div id="h"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
w.eval(fs.readFileSync(path.join(__dirname, '../../static/js/fonts-propias.js'), 'utf8'));
w.eval(fs.readFileSync(path.join(__dirname, '../../static/js/rich-text.js'), 'utf8'));
const R = w.RichText;

// textos viejos: no son «con formato», se ven igual (escapados)
V.plain.forEach((t) => { assert.ok(!R.hasFormat(t), 'plano: ' + t); assert.strictEqual(R.html(t).rich, false); assert.strictEqual(R.html(t).html, t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')); });
assert.strictEqual(R.html('menores de <18 años').html, 'menores de &lt;18 años');
assert.strictEqual(R.html('a < b').html, 'a &lt; b');

V.clean.forEach(([src, out]) => { assert.ok(R.hasFormat(src), src); assert.strictEqual(R.clean(src), out, src); assert.strictEqual(R.clean(out), out, 'idempotente: ' + out); });
V.basic.forEach(([src, out]) => assert.strictEqual(R.clean(src, true), out, src));
V.attacks.forEach((src) => {
  if (!R.hasFormat(src)) return;
  const out = R.clean(src).toLowerCase();
  V.forbidden.forEach((bad) => assert.ok(!out.includes(bad), `${src} -> ${out} contiene ${bad}`));
});
V.plain_out.forEach(([src, out]) => assert.strictEqual(R.toPlain(src), out, src));

// colores solo hex/rgb; letras solo las alojadas
['red', 'url(x)', 'var(--x)', 'hsl(1,2%,3%)', 'currentColor', '#ggg', 'rgb(1,2)'].forEach((c) => assert.strictEqual(R.cleanStyle('color:' + c, true), '', c));
assert.strictEqual(R.cleanStyle("font-family:Arial", true), '');
assert.strictEqual(R.cleanStyle("font-family:'Open Sans'", true), "font-family:'Open Sans'");

// editor: pegar entra como texto plano (sin la basura de Word / Google Docs) y lo escrito se limpia
const host = w.document.getElementById('h');
let got = null;
const ed = R.mount(host, { value: 'Hola', label: 'Texto', onChange: (v) => { got = v; } });
assert.strictEqual(ed.getValue(), 'Hola', 'un texto plano abre y vuelve como plano');
const inserted = [];
w.document.execCommand = (cmd, _ui, val) => { if (cmd === 'insertText') { inserted.push(val); ed.el.append(w.document.createTextNode(val)); return true; } return true; };
const ev = new w.Event('paste', { bubbles: true, cancelable: true });
ev.clipboardData = { getData: (t) => (t === 'text/html' ? '<span style="mso-bidi:1" onclick="x()"><b>Word</b></span><script>1</script>' : 'texto pegado') };
ed.el.dispatchEvent(ev);
assert.ok(ev.defaultPrevented, 'el pegado normal se cancela');
assert.deepStrictEqual(inserted, ['texto pegado'], 'solo se usa el text/plain, nunca el HTML del portapapeles');
assert.ok(!ed.el.innerHTML.includes('mso-') && !ed.el.innerHTML.includes('<script'), 'sin basura');
assert.strictEqual(got, 'Holatexto pegado');
// lo que el usuario deja en el editor se limpia al leerlo
ed.el.innerHTML = '<b onclick="x()">N</b><script>1</script><span style="color:red;color:#fff">c</span> y <18';
assert.strictEqual(ed.getValue(), '<b>N</b><span style="color:#fff">c</span> y &lt;18');
ed.setValue('<ul><li>a</li></ul><img src=x onerror=alert(1)>');
assert.strictEqual(ed.el.innerHTML, '<ul><li>a</li></ul>');
// barra: básica solo trae lo básico
const host2 = w.document.createElement('div'); w.document.body.append(host2);
R.mount(host2, { basic: true, value: '' });
assert.ok(!host2.querySelector('select') && host2.querySelectorAll('button').length < host.querySelectorAll('button').length, 'ayudas: formato básico');
['Negrilla', 'Cursiva', 'Subrayado', 'Tamaño', 'Letra', 'Justificar', 'Lista con viñetas', 'Lista numerada', 'Color del texto'].forEach((t) => assert.ok(host.querySelector(`[title="${t}"]`), 'falta ' + t));
assert.strictEqual(host.querySelector('[title="Letra"]').options.length - 1, w.GoldenFonts.choices.length, 'solo las tipografías alojadas');
console.log('rich_text_check OK');
