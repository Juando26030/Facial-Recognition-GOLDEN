// P5: el paso «Identifícate» con textos editables; sin configurar, el HTML es EXACTAMENTE el de siempre. Correr: npm ci && node tests/js/form_identify_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const src = fs.readFileSync(path.join(root, 'templates/form_public.html'), 'utf8').split('\r\n').join('\n');   // en Windows el archivo puede traer CRLF
const fn = /function showIdentify\(st\) \{[\s\S]*?\n\}\n/.exec(src)[0];
const dom = new JSDOM('<!doctype html><body><div id="app"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js'].forEach((f) => w.eval(fs.readFileSync(path.join(root, f), 'utf8')));
w.eval(`
  const esc = (t) => String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  const assetUrl = (p) => '/asset/' + p; let token; const load = () => {}; const api = async () => ({});
  const app = document.getElementById('app'); function box(html) { app.innerHTML = '<div class="box">' + html + '</div>'; }
  ${fn}
  window.showIdentify = showIdentify;`);
const html = (st) => { w.showIdentify(st); return w.document.querySelector('.box').innerHTML; };

// sin configurar (o sin la llave, como en páginas viejas): lo de siempre
const REQ = '<h3 style="margin-top:0;">Identifícate</h3><p style="opacity:.8;">Escribe tu número de documento: debes estar en la lista de invitados.</p>\n    <input type="text" id="docid" inputmode="numeric" autocomplete="off" placeholder="Número de documento"><div class="msg" id="msg"></div><button id="go">Continuar</button>';
const OPT = REQ.replace('debes estar en la lista de invitados.', 'si ya estás en nuestra base, tus datos aparecerán listos.');
assert.strictEqual(html({ required: true }), REQ);
assert.strictEqual(html({ required: false }), OPT);
assert.strictEqual(html({ required: true, identify: { title: '', text: '', image: '', button: '' } }), REQ);

// editado: título, botón, imagen y texto con formato limpio
const h = html({ required: true, identify: { title: 'Bienvenido <3', button: 'Entrar', image: 'acme/logo.png', text: '<b>Tu documento</b><script>alert(1)</script> para <18' } });
assert.ok(h.startsWith('<img src="/asset/acme/logo.png"'), 'imagen arriba');
assert.ok(h.includes('<h3 style="margin-top:0;">Bienvenido &lt;3</h3>'), 'título plano escapado');
assert.ok(h.includes('<div class="rt" style="opacity:.8;"><b>Tu documento</b> para &lt;18</div>') && !h.includes('script'), 'texto con formato, limpio');
assert.ok(h.includes('<button id="go">Entrar</button>'));
// texto plano editado: igual que el de siempre (párrafo)
assert.ok(html({ required: true, identify: { text: 'Solo texto <18' } }).includes('<p style="opacity:.8;">Solo texto &lt;18</p>'));
console.log('form_identify_check OK');
