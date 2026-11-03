// P8: nombre de PRESENTACIÓN con formato en todos los tipos de campo; sin él se ve el nombre plano de siempre. Correr: npm ci && node tests/js/form_display_label_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<!doctype html><body><div id="h"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(__dirname, '../..', f), 'utf8')));

const RICH = '<b>Tu <span style="color:#d4af37">ciudad</span></b><script>alert(1)</script>';
const types = ['text_short', 'text_long', 'email', 'phone', 'number', 'date', 'checkbox', 'select', 'radio', 'multiselect', 'file'];
const fields = {};
types.forEach((t) => { fields[t] = { id: t, type: t, label: 'Plano ' + t, display_label: RICH, help: '<i>ayuda</i><ul><li>uno</li></ul>', options: ['A', 'B'], accept: ['pdf'], max_mb: 5 }; });
fields.old = { id: 'old', type: 'text_short', label: 'Nombre <18', help: 'ayuda <18' };
fields.pay = { id: 'pay', type: 'payment', label: 'Pago plano', display_label: '<u>Tu pago</u>', help: '<b>sobre el pago</b>', pay: { mode: 'fixed', amount: 1000, discounts: [], rules: [] } };
fields.comp = { id: 'comp', type: 'companions', label: 'Acompañantes plano', display_label: '<i>Con quién vienes</i>', max: 2, min: 0, person_fields: [{ id: 'nombre', label: 'Nombre', type: 'text_short' }] };
const design = { theme: {}, fields, rows: Object.keys(fields).map((i) => ({ items: [i] })) };
w.FormRender.render(w.document.getElementById('h'), design, { previewOnly: true });
const html = (id) => w.document.querySelector(`[data-fid="${id}"]`).innerHTML;

types.forEach((t) => {
  const h = html(t);
  assert.ok(h.includes('<b>Tu <span style="color:#d4af37">ciudad</span></b>'), `${t}: nombre de presentación con formato`);
  assert.ok(!h.includes('Plano ' + t) || t === 'checkbox' && false, `${t}: ya no muestra el nombre plano`);
  assert.ok(!h.includes('<script') && !h.includes('alert('), `${t}: limpio: ${h}`);
  assert.ok(h.includes('<ul><li>uno</li></ul>'), `${t}: ayuda con formato completo (listas)`);
});
assert.ok(html('pay').includes('<u>Tu pago</u>') && html('pay').includes('<b>sobre el pago</b>'));
assert.ok(html('comp').includes('<i>Con quién vienes</i>'));
// sin nombre de presentación: EXACTAMENTE el de siempre (escapado), y la ayuda vieja igual
assert.ok(html('old').includes('>Nombre &lt;18</label>') && html('old').includes('<div class="fr-help">ayuda &lt;18</div>'));
// el nombre plano sigue siendo el dato: la lógica del formulario lo usa tal cual
assert.strictEqual(design.fields.text_short.label, 'Plano text_short');
console.log('form_display_label_check OK');
