// C1/C2 (Fase 3): showConfirm no ejecuta HTML que escribió una persona. DOM mínimo (sin jsdom). Correr: node tests/js/confirm_escape_check.js
const fs = require('fs');
const path = require('path');
const assert = require('assert');

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.style = {}; this.parts = {}; this.textContent = ''; this.innerHTML = ''; this.className = ''; this.listeners = {}; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, f) { this.listeners[t] = f; }
  appendChild(c) { this.children.push(c); return c; }
  remove() {}
  focus() {}
  querySelector(sel) {
    if (!this.parts[sel]) this.parts[sel] = new El(sel);
    return this.parts[sel];
  }
  querySelectorAll() { return []; }
  contains() { return false; }
}
const body = new El('body');
global.window = {};
global.document = { body, activeElement: null, createElement: (t) => new El(t), addEventListener() {}, removeEventListener() {}, contains: () => false, head: new El('head') };
global.requestAnimationFrame = (f) => f();
global.setTimeout = () => 0;
eval(fs.readFileSync('static/js/toast.js', 'utf8'));

function bodyHtmlOf() {
  const backdrop = body.children[body.children.length - 1];
  const dlg = backdrop.children[0];
  return dlg.parts['.gw-modal__body'].innerHTML;
}

const EVIL = '<img src=x onerror=import(1)>';
window.showConfirm('', { text: EVIL });
let html = bodyHtmlOf();
assert.ok(html.includes('&lt;img'), 'opts.text se escapa: ' + html);
assert.ok(!html.includes('<img'), 'no queda ninguna etiqueta <img> viva: ' + html);

// el mensaje HTML propio de la app sigue funcionando (compatibilidad)
window.showConfirm('¿Seguro? <b>sí</b>');
assert.ok(bodyHtmlOf().includes('<b>sí</b>'), 'message sigue siendo HTML para textos propios');

// y escapeHtml neutraliza lo que las pantallas le pasan
assert.strictEqual(window.escapeHtml(EVIL).includes('<'), false);

// chequeo estático: los showConfirm que interpolan datos de personas pasan por escapeHtml/esc
const files = [
  ['static/js/color-library.js', /showConfirm\(`[^`]*\$\{(?!esc\()/],
  ['templates/badge_editor.html', /showConfirm\('[^']*' \+ (?!window\.escapeHtml\()/],
  ['templates/kiosk_formulario_editor.html', /Quitar el acceso de \$\{(?!window\.escapeHtml\()/],
  ['templates/kiosk_parametros.html', /solicitud ' \+ (?!window\.escapeHtml\()|msg\.replace\('\{id\}', (?!window\.escapeHtml\()/],
];
for (const [f, bad] of files) {
  const src = fs.readFileSync(path.join(process.cwd(), f), 'utf8');
  assert.ok(!bad.test(src), f + ': hay un showConfirm que interpola sin escapar');
}
console.log('showConfirm: texto de personas escapado OK');
