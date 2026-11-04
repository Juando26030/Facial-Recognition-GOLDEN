// Mensaje del cupo lleno (espejo de formlib.quota_full_message) y limpieza del error de un campo al corregirlo. Correr: npm ci && node tests/js/form_quota_message_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<!doctype html><body><div id="h"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(__dirname, '../..', f), 'utf8')));
w.HTMLElement.prototype.scrollIntoView = function () {};   // jsdom no lo implementa (validate() salta al primer error)
const { quotaFullMessage } = w.FormRender;
assert.strictEqual(quotaFullMessage('Se acabó {cupo} ({cupo})', 'VIP'), 'Se acabó VIP (VIP)');
assert.strictEqual(quotaFullMessage('', 'VIP'), 'Ya se llenaron los cupos de VIP. Elige otra opción para poder inscribirte.');
assert.strictEqual(quotaFullMessage(null, 'VIP'), quotaFullMessage('   ', 'VIP'));
// Máximo 0 = cerrado temporalmente: texto por defecto distinto; el mensaje propio de la regla sigue mandando
assert.strictEqual(quotaFullMessage('', 'Popayán', true), 'Por ahora no estamos recibiendo inscripciones de Popayán. Elige otra opción.');
assert.strictEqual(quotaFullMessage(null, 'Popayán', true), quotaFullMessage('   ', 'Popayán', true));
assert.strictEqual(quotaFullMessage('Vuelve pronto: {cupo}', 'Popayán', true), 'Vuelve pronto: Popayán');
assert.strictEqual(quotaFullMessage('', 'Popayán', false), 'Ya se llenaron los cupos de Popayán. Elige otra opción para poder inscribirte.');

const design = {
  theme: {},
  fields: {
    c: { id: 'c', type: 'select', label: 'Categoría', options: ['VIP', 'General'] },
    ok: { id: 'ok', type: 'checkbox', label: 'Acepto', required: true },
    n: { id: 'n', type: 'text_short', label: 'Nombre', required: true },
  },
  rows: ['c', 'ok', 'n'].map((i) => ({ items: [i] })),
};
const quota = { full: [
  { label: 'VIP', message: 'Ya no hay {cupo}.', match: 'all', conds: [{ field: 'c', op: 'equals', value: 'VIP' }] },
  { label: 'General', message: '', match: 'all', conds: [{ field: 'c', op: 'equals', value: 'General' }] }] };
const f = w.FormRender.render(w.document.getElementById('h'), design, { previewOnly: true, quota });
const doc = w.document, wrap = (id) => doc.querySelector(`[data-fid="${id}"]`);
const warn = doc.querySelector('.fr-quota-warn');
const pick = (v) => { const s = doc.querySelector('select[name=c]'); s.value = v; s.dispatchEvent(new w.Event('input', { bubbles: true })); };

assert.strictEqual(warn.style.display, 'none');
pick('VIP');
assert.strictEqual(warn.style.display, 'flex'); assert.ok(warn.textContent.includes('Ya no hay VIP.'));
assert.ok(parseFloat(warn.style.fontSize) >= 1.1 && warn.style.fontWeight === '700', 'aviso grande y en negrita');
pick('General');
assert.ok(warn.textContent.includes('Ya se llenaron los cupos de General.'));
assert.strictEqual(f.validate(), false, 'con el cupo lleno no se envía');

// errores: se limpia SOLO el del campo corregido
f.validate();
assert.ok(wrap('ok').classList.contains('has-err') && wrap('n').classList.contains('has-err'));
const cb = doc.querySelector('input[name=ok]'); cb.checked = true; cb.dispatchEvent(new w.Event('change', { bubbles: true }));
assert.ok(!wrap('ok').classList.contains('has-err') && wrap('ok').querySelector('.fr-err').textContent === '', 'la casilla marcada ya no muestra error');
assert.ok(wrap('n').classList.contains('has-err'), 'el otro campo conserva su error');
const nm = doc.querySelector('input[name=n]'); nm.value = ''; nm.dispatchEvent(new w.Event('input', { bubbles: true }));
assert.ok(wrap('n').classList.contains('has-err'), 'sigue inválido: el error se queda');
nm.value = 'Ana'; nm.dispatchEvent(new w.Event('input', { bubbles: true }));
assert.ok(!wrap('n').classList.contains('has-err'));
console.log('form_quota_message_check OK');
