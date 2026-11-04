// Formulario de persona (Fase 1A, pieza 5) con jsdom: static/js/person-form.js (disposición, obligatorios, texto al escribir, condiciones) y el diseñador (static/js/person-form-designer.js).
// Correr: npm ci && node tests/js/person_form_dom_check.js
// Comprueba: los campos YA existentes se MUEVEN a grupos y filas (mismos nodos, mismos `name`, nada se pierde; uno desconocido va al final); cédula y nombres obligatorios, apellidos nunca; un grupo
// con un obligatorio queda abierto y uno cerrado se abre solo si tiene un campo inválido; «Texto al escribir» al teclear y con applyAll (solo los campos marcados, nunca cédula/teléfono/correo);
// `show_if` oculta y deshabilita (no viaja ni se exige); una definición más nueva se re-dibuja con los mismos nodos; campos no editables sin red con su motivo; el diseñador carga, edita y guarda.
const assert = require('assert');
const { JSDOM } = require('jsdom');

globalThis.FormRender = require('../../static/js/form-render.js');          // motor de condiciones del formulario web (computeVisible)
const PF = require('../../static/js/person-form.js');
const D = require('../../static/js/person-form-designer.js');

const field = (key, label, extra) => `<div class="badge-input-group" data-field-key="${key}"><label>${label}</label>${extra || `<input type="text" name="${key}">`}</div>`;
const page = () => new JSDOM(`<!doctype html><body><form id="f"><div id="c">
  ${field('id', 'Cédula *', '<input type="text" name="id" id="manualIdField" required>')}
  ${field('first_name', 'Nombres *', '<input type="text" name="first_name" required>')}
  ${field('last_name', 'Apellidos *', '<input type="text" name="last_name" required>')}
  ${field('role', 'Cargo')}${field('entity', 'Entidad')}${field('phone', 'Teléfono')}
  ${field('email', 'Correo', '<input type="email" name="email">')}${field('opcional_1', 'Ciudad')}${field('opcional_9', 'Campo nuevo del evento')}
</div></form></body>`, { runScripts: 'outside-only' });

const def = (patch) => ({
  enabled: true, form_version: 2, form_sig: 's2',
  sheets: [{ id: 'datos', title: 'Datos principales', open: true }, { id: 'mas', title: 'Más datos', open: false }],
  rows: [{ sheet: 'datos', items: ['id'] }, { sheet: 'datos', items: ['first_name', 'last_name'] }, { sheet: 'mas', items: ['role', 'entity'] }, { sheet: 'mas', items: ['phone', 'email', 'opcional_1'] }],
  fields: { id: { required: true }, first_name: { required: true, text_case: 'upper' }, last_name: { required: true, text_case: 'upper' }, role: { required: false }, entity: { required: false, text_case: 'lower' },
    phone: { required: false, text_case: 'upper' }, email: { required: false }, opcional_1: { required: false, text_case: 'upper' } },
  ...(patch || {}),
});
const fire = (w, el, type) => el.dispatchEvent(new w.Event(type, { bubbles: true }));
const type = (w, el, value) => { el.value = value; fire(w, el, 'input'); };
const keysIn = (node) => Array.from(node.querySelectorAll('[data-field-key]')).map((n) => n.getAttribute('data-field-key'));

(async () => {
  // ---- disposición
  let dom = page(), w = dom.window, c = w.document.getElementById('c');
  const nodesBefore = {}; c.querySelectorAll('[data-field-key]').forEach((n) => { nodesBefore[n.getAttribute('data-field-key')] = n; });
  let ctl = PF.mount(c, def());
  const groups = c.querySelectorAll('details.gw-form-group');
  assert.strictEqual(groups.length, 2); assert.strictEqual(groups[0].open, true); assert.strictEqual(groups[1].open, false, 'el grupo «Más datos» empieza cerrado');
  assert.strictEqual(groups[0].querySelector('summary.gw-form-group__summary').textContent, 'Datos principales');
  assert.deepStrictEqual(keysIn(c), ['id', 'first_name', 'last_name', 'role', 'entity', 'phone', 'email', 'opcional_1', 'opcional_9'], 'orden de la definición; el campo que no conoce va al final');
  assert.strictEqual(groups[0].querySelectorAll('.gw-fields-row--2').length, 1, 'nombres y apellidos en dos columnas');
  assert.strictEqual(groups[1].querySelectorAll('.gw-fields-row--3').length, 1);
  assert.strictEqual(c.querySelector('[data-field-key="opcional_9"]').closest('details'), groups[1], 'el campo desconocido queda en el último grupo');
  for (const k of Object.keys(nodesBefore)) assert.strictEqual(c.querySelector(`[data-field-key="${k}"]`), nodesBefore[k], `el nodo de «${k}» es el mismo (no se perdió ningún oyente ni id)`);
  assert.ok(w.document.getElementById('manualIdField'), 'los ids que usan otros scripts siguen');

  // ---- obligatorios
  const req = (k) => c.querySelector(`[name="${k}"]`).hasAttribute('required');
  assert.ok(req('id') && req('first_name')); assert.strictEqual(req('last_name'), false, 'los apellidos nunca se exigen');
  assert.strictEqual(c.querySelector('[data-field-key="last_name"] label').textContent, 'Apellidos'); assert.strictEqual(c.querySelector('[data-field-key="id"] label').textContent, 'Cédula *');
  assert.strictEqual(c.querySelector('[data-field-key="role"] label').textContent, 'Cargo');

  // ---- texto al escribir
  type(w, c.querySelector('[name="first_name"]'), 'ana maría'); assert.strictEqual(c.querySelector('[name="first_name"]').value, 'ANA MARÍA');
  type(w, c.querySelector('[name="entity"]'), 'ACME SAS'); assert.strictEqual(c.querySelector('[name="entity"]').value, 'acme sas');
  type(w, c.querySelector('[name="phone"]'), '300abc'); assert.strictEqual(c.querySelector('[name="phone"]').value, '300abc', 'el teléfono nunca se convierte, aunque alguien lo marcara');
  type(w, c.querySelector('[name="id"]'), 'ab12'); assert.strictEqual(c.querySelector('[name="id"]').value, 'ab12', 'la cédula nunca');
  type(w, c.querySelector('[name="email"]'), 'Ana@X.CO'); assert.strictEqual(c.querySelector('[name="email"]').value, 'Ana@X.CO', 'el correo se pasa a minúsculas en el servidor');
  type(w, c.querySelector('[name="role"]'), 'Jefe de Área'); assert.strictEqual(c.querySelector('[name="role"]').value, 'Jefe de Área', 'sin regla: como lo escriban');
  c.querySelector('[name="last_name"]').value = 'pérez';          // lo llenó un lector o la foto de la cédula: no hubo tecleo
  c.querySelector('[name="opcional_1"]').value = 'bogotá';
  ctl.applyAll(); assert.strictEqual(c.querySelector('[name="last_name"]').value, 'PÉREZ'); assert.strictEqual(c.querySelector('[name="opcional_1"]').value, 'BOGOTÁ');

  // ---- grupo cerrado con un campo inválido se abre solo; un grupo con un obligatorio nace abierto
  groups[1].open = false;
  c.querySelector('[name="role"]').dispatchEvent(new w.Event('invalid'));
  assert.strictEqual(groups[1].open, true, 'un campo inválido en un grupo cerrado lo abre');
  ctl.relayout(def({ form_version: 3, fields: { ...def().fields, role: { required: true } } }));
  assert.strictEqual(c.querySelectorAll('details.gw-form-group')[1].open, true, 'un grupo con un obligatorio queda abierto'); assert.ok(req('role')); assert.strictEqual(c.querySelector('[data-field-key="role"] label').textContent, 'Cargo *');
  assert.strictEqual(c.querySelector('[name="first_name"]').value, 'ANA MARÍA', 'volver a dibujar no borra lo escrito');

  // ---- una definición más nueva re-dibuja con los mismos nodos
  ctl.relayout(def({ form_version: 4, sheets: [{ id: 'solo', title: '', open: true }], rows: [{ sheet: 'solo', items: ['opcional_1', 'id'] }, { sheet: 'solo', items: ['first_name'] }] }));
  assert.strictEqual(c.querySelectorAll('details.gw-form-group').length, 1); assert.strictEqual(c.querySelector('summary'), null, 'un grupo sin título no lleva encabezado');
  assert.deepStrictEqual(keysIn(c).slice(0, 3), ['opcional_1', 'id', 'first_name']); assert.strictEqual(c.querySelector(`[data-field-key="id"]`), nodesBefore.id);
  ctl.destroy();

  // ---- show_if: oculta y deshabilita (no viaja ni se exige); vuelve al cumplirse
  dom = page(); w = dom.window; c = w.document.getElementById('c');
  c.querySelector('[name="entity"]').setAttribute('required', '');
  ctl = PF.mount(c, def({ fields: { ...def().fields, entity: { required: false, show_if: { field: 'role', op: 'filled' } } } }));
  const entityNode = c.querySelector('[data-field-key="entity"]'), entityInput = c.querySelector('[name="entity"]');
  assert.strictEqual(entityNode.hidden, true); assert.strictEqual(entityInput.disabled, true, 'oculto = deshabilitado: no viaja en el formulario');
  assert.ok(!new w.FormData(w.document.getElementById('f')).has('entity'));
  type(w, c.querySelector('[name="role"]'), 'Jefe');
  assert.strictEqual(entityNode.hidden, false); assert.strictEqual(entityInput.disabled, false);
  type(w, c.querySelector('[name="role"]'), '');
  assert.strictEqual(entityNode.hidden, true); ctl.destroy();

  // ---- campos que no se editan sin red: deshabilitados, con su motivo
  dom = page(); w = dom.window; c = w.document.getElementById('c');
  ctl = PF.mount(c, def(), { disableKeys: ['id', 'opcional_9'], disabledHint: 'Requiere conexión' });
  assert.strictEqual(c.querySelector('[name="id"]').disabled, true); assert.strictEqual(c.querySelector('[data-field-key="id"] .gw-hint').textContent, 'Requiere conexión');
  assert.strictEqual(c.querySelector('[name="first_name"]').disabled, false); ctl.destroy();

  // ---- diseñador: carga, edita y guarda
  const cfgs = [['id', 'Cédula'], ['first_name', 'Nombres'], ['last_name', 'Apellidos'], ['role', 'Cargo'], ['phone', 'Teléfono'], ['opcional_1', 'Ciudad']].map(([key, label]) => ({ key, label, field_type: 'text_short', required: false }));
  let view = { env_enabled: true, enabled: false, definition: { ...def(), enabled: false, rows: [{ sheet: 'datos', items: ['id'] }, { sheet: 'datos', items: ['first_name', 'last_name'] }, { sheet: 'mas', items: ['role', 'phone', 'opcional_1'] }] }, fields: cfgs };
  const puts = [], toasts = [];
  const fetchFake = async (url, opts) => {
    if (opts && opts.method === 'PUT') { const b = JSON.parse(opts.body); puts.push(b); view = { ...view, enabled: b.enabled, definition: { ...view.definition, form_version: 3, enabled: b.enabled, rows: b.rows, sheets: b.sheets, fields: { ...view.definition.fields, ...b.fields } } }; }
    return { ok: true, status: 200, json: async () => view };
  };
  dom = new JSDOM('<!doctype html><body><div id="ed"></div></body>'); w = dom.window;
  const ed = w.document.getElementById('ed');
  D.mount(ed, { eventId: 7, fetch: fetchFake, toast: (m, k) => toasts.push([m, k]) });
  await new Promise((r) => setTimeout(r, 30));
  assert.strictEqual(ed.querySelectorAll('tbody tr').length, 6, 'una fila por cada campo del evento');
  assert.ok(ed.querySelector('select[aria-label^="Texto al escribir de Nombres"]'), 'Nombres admite «Texto al escribir»'); assert.strictEqual(ed.querySelector('select[aria-label^="Texto al escribir de Teléfono"]'), null, 'Teléfono no');
  assert.strictEqual(ed.querySelector('input[aria-label="Cédula obligatorio"]').disabled, true, 'la cédula siempre es obligatoria'); assert.strictEqual(ed.querySelector('input[aria-label="Apellidos obligatorio"]').disabled, true);
  const roleReq = ed.querySelector('input[aria-label="Cargo obligatorio"]'); roleReq.checked = true; fire(w, roleReq, 'change');
  const caseSel = ed.querySelector('select[aria-label^="Texto al escribir de Nombres"]'); caseSel.value = 'upper'; fire(w, caseSel, 'change');
  ed.querySelector('#pfEnabled').checked = true; fire(w, ed.querySelector('#pfEnabled'), 'change');
  ed.querySelector('#pfSave').click();
  await new Promise((r) => setTimeout(r, 30));
  assert.strictEqual(puts.length, 1); assert.strictEqual(puts[0].enabled, true);
  assert.strictEqual(puts[0].fields.role.required, true); assert.strictEqual(puts[0].fields.first_name.text_case, 'upper'); assert.strictEqual(puts[0].fields.id.required, undefined, 'lo que no se puede cambiar no se manda');
  assert.deepStrictEqual(puts[0].rows[1].items, ['first_name', 'last_name']);
  assert.ok(toasts.some(([m, k]) => k === 'success' && /versión 3/.test(m)), 'avisa con toast, nunca alert');
  assert.ok(/Versión del diseño: 3/.test(ed.textContent));
  console.log('person_form_dom_check: OK');
})().catch((e) => { console.error(e); process.exit(1); });
