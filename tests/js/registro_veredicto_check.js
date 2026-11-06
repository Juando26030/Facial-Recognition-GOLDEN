// Veredicto del Registro (Fase 1.7, 1A): la banda muestra ícono + título + detalle, usa role=alert solo en rojo, se oculta al escribir y no falla si la página no la trae.
const assert = require('assert');
const mk = () => ({ hidden: true, className: '', attrs: {}, textContent: '', setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; } });
const els = { gwVerdict: mk(), gwVerdictIcon: mk(), gwVerdictTitle: mk(), gwVerdictText: mk() };
els.gwVerdictIcon.attrs.href = '/static/img/icons.svg#i-info';
let onInput = null;
global.window = global;
global.document = { getElementById: (id) => els[id] || null, addEventListener: (t, f) => { if (t === 'input') onInput = f; } };
const timers = []; global.setTimeout = (f) => { timers.push(f); return timers.length; }; global.clearTimeout = () => {};
require('../../static/js/registro-veredicto.js');

GWVerdict.show('ok', 'Acreditado(a)', 'Ana Pérez');
assert.strictEqual(els.gwVerdict.hidden, false); assert.strictEqual(els.gwVerdict.className, 'gw-verdict gw-verdict--ok');
assert.strictEqual(els.gwVerdict.attrs.role, 'status'); assert.strictEqual(els.gwVerdictIcon.attrs.href, '/static/img/icons.svg#i-check-lg');
assert.strictEqual(els.gwVerdictTitle.textContent, 'Acreditado(a)'); assert.strictEqual(els.gwVerdictText.textContent, 'Ana Pérez');
GWVerdict.show('err', 'No está en la lista');
assert.strictEqual(els.gwVerdict.attrs.role, 'alert'); assert.strictEqual(els.gwVerdict.className, 'gw-verdict gw-verdict--err'); assert.strictEqual(els.gwVerdictText.hidden, true);
GWVerdict.show('warn', 'Ya estaba registrado(a)', 'x'); assert.ok(/gw-verdict--warn/.test(els.gwVerdict.className));
GWVerdict.show('raro', 'T'); assert.strictEqual(els.gwVerdict.className, 'gw-verdict');
onInput({ target: { id: 'otro' } }); assert.strictEqual(els.gwVerdict.hidden, false, 'otro campo no la oculta');
onInput({ target: { id: 'searchCedula' } }); assert.strictEqual(els.gwVerdict.hidden, true, 'escribir en el buscador la oculta');
delete els.gwVerdict; GWVerdict.show('ok', 'x'); GWVerdict.hide();      // sin banda en la página: no falla
console.log('registro_veredicto_check: OK');
