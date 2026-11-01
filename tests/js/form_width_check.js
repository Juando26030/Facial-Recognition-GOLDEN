// P4: ancho máximo de la tarjeta (theme.width). Correr: npm ci && node tests/js/form_width_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<!doctype html><body><div id="h"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(__dirname, '../..', f), 'utf8')));
const max = w.FormRender.cardMax;
assert.strictEqual(max({}), '760px', 'sin valor: como siempre');
assert.strictEqual(max(undefined), '760px');
assert.strictEqual(max({ width: 960 }), '960px');
assert.strictEqual(max({ width: '600' }), '600px');
assert.strictEqual(max({ width: 'full' }), 'none');
['abc', 100, 479, 1101, -5, null, true, {}].forEach((v) => assert.strictEqual(max({ width: v }), '760px', String(v)));

const card = (theme) => { const h = w.document.getElementById('h'); w.FormRender.render(h, { theme, fields: {}, rows: [] }, { previewOnly: true }); return h.firstChild; };
assert.ok(card({}).style.cssText.includes('max-width: 760px'));
assert.ok(card({ width: 1100 }).style.cssText.includes('max-width: 1100px'));
assert.ok(card({ width: 'full' }).style.cssText.includes('max-width: none'));
assert.ok(card({ width: 'full' }).style.cssText.includes('margin: 0px auto') || card({ width: 'full' }).style.cssText.includes('margin: 0 auto'), 'sigue centrada');
console.log('form_width_check OK');
