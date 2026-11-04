// Formulario de persona (Fase 1A, pieza 5): lógica pura de static/js/person-form.js y del diseñador (static/js/person-form-designer.js), sin DOM. Correr: node tests/js/person_form_check.js
// Comprueba: «Texto al escribir» igual que el servidor (solo los campos marcados; correo SIEMPRE en minúsculas; nunca cédula ni teléfono), elección de la definición más nueva (página vs. copia del
// dispositivo), sincronía con la copia local, y el ida y vuelta del diseñador (grupos, filas «junto al anterior» máx. 4, obligatorio solo donde se puede, condición simple y avanzada que se conserva).
const assert = require('assert');
global.window = undefined;
const PF = require('../../static/js/person-form.js');
const D = require('../../static/js/person-form-designer.js');

const def = (extra) => ({
  enabled: true, form_version: 3, form_sig: 'abc',
  sheets: [{ id: 'datos', title: 'Datos', open: true }, { id: 'mas', title: 'Más', open: false }],
  rows: [{ sheet: 'datos', items: ['id'] }, { sheet: 'datos', items: ['first_name', 'last_name'] }, { sheet: 'mas', items: ['role', 'entity', 'phone', 'email'] }, { sheet: 'mas', items: ['opcional_1', 'opcional_2'] }],
  fields: { id: { required: true, text_case: '' }, first_name: { required: true, text_case: 'upper' }, last_name: { required: false, text_case: 'upper' }, role: { required: false, text_case: '' },
    entity: { required: false, text_case: 'lower' }, phone: { required: false, text_case: '' }, email: { required: false, text_case: '' },
    opcional_1: { required: false, text_case: 'upper' }, opcional_2: { required: false, text_case: '' } },
  ...(extra || {}),
});

// ---- «Texto al escribir»: mismas reglas que app/personform.py::apply_case
assert.strictEqual(PF.convert('ana maría', 'upper'), 'ANA MARÍA');
assert.strictEqual(PF.convert('ACME SAS', 'lower'), 'acme sas');
assert.strictEqual(PF.convert('Tal Cual', ''), 'Tal Cual', 'sin modo: como lo escriban');
assert.strictEqual(PF.convert(12, 'upper'), 12, 'no texto: se devuelve igual');
assert.deepStrictEqual(PF.rulesOf(def()), { first_name: 'upper', last_name: 'upper', entity: 'lower', opcional_1: 'upper' });
const person = { id: 'ab12', first_name: 'ana maría', last_name: 'pérez', phone: '300 abc', entity: 'ACME', email: ' Ana@Mail.CO ', extra_fields: { opcional_1: 'bogotá', opcional_2: 'Mm' } };
PF.applyCase(person, def());
assert.deepStrictEqual(person, { id: 'ab12', first_name: 'ANA MARÍA', last_name: 'PÉREZ', phone: '300 abc', entity: 'acme', email: 'ana@mail.co', extra_fields: { opcional_1: 'BOGOTÁ', opcional_2: 'Mm' } },
  'cédula y teléfono intactos; opcional sin regla intacto; correo en minúsculas');
const untouched = { first_name: 'ana', email: 'A@B.CO' };
assert.deepStrictEqual(PF.applyCase(untouched, null), { first_name: 'ana', email: 'A@B.CO' }, 'sin definición no se toca nada');

// ---- obligatorios: cédula y nombres siempre; apellidos nunca; el resto, lo que diga la definición
const d = def({ fields: { ...def().fields, last_name: { required: true }, role: { required: true }, id: { required: false } } });
assert.strictEqual(PF.requiredOf(d, 'id'), true); assert.strictEqual(PF.requiredOf(d, 'first_name'), true);
assert.strictEqual(PF.requiredOf(d, 'last_name'), false, 'los apellidos no se exigen');
assert.strictEqual(PF.requiredOf(d, 'role'), true); assert.strictEqual(PF.requiredOf(d, 'entity'), false);

// ---- la definición más nueva gana (página en caché vs. copia del dispositivo)
const v2 = def({ form_version: 2 }), v5 = def({ form_version: 5 });
assert.strictEqual(PF.pick(v2, v5), v5, 'la guardada es más nueva'); assert.strictEqual(PF.pick(v5, v2), v5, 'la de la página es más nueva');
assert.strictEqual(PF.pick(v5, def({ form_version: 5 })), v5, 'a igual versión, la de la página'); assert.strictEqual(PF.pick(null, v2), v2); assert.strictEqual(PF.pick(v2, null), v2);
assert.strictEqual(PF.pick(null, null), null);

(async () => {
  // ---- sync con la copia local (contingency.js): guarda la de la página si es más nueva o no hay; usa la guardada si es más nueva
  let stored = null, saved = [];
  const GC = { personForm: async () => stored, savePersonForm: async (x) => { saved.push(x); stored = x; } };
  assert.strictEqual(await PF.sync(GC, v2), v2); assert.deepStrictEqual(saved, [v2], 'sin copia: se guarda la de la página');
  saved = []; assert.strictEqual(await PF.sync(GC, v2), v2); assert.deepStrictEqual(saved, [], 'misma versión: no se reescribe');
  assert.strictEqual(await PF.sync(GC, v5), v5); assert.deepStrictEqual(saved, [v5], 'la de la página es más nueva: se actualiza la copia');
  saved = []; assert.strictEqual(await PF.sync(GC, v2).then((x) => x.form_version), 5, 'sin red con la página vieja en caché: manda la copia guardada'); assert.deepStrictEqual(saved, []);
  assert.strictEqual(await PF.sync(null, v2), v2, 'sin almacenamiento: la de la página');
  assert.strictEqual(await PF.sync({ personForm: async () => { throw new Error('idb'); }, savePersonForm: async () => { throw new Error('idb'); } }, v2), v2, 'un fallo del almacenamiento nunca rompe');

  // ---- diseñador: ida y vuelta
  const cfgs = [['id', 'Cédula', 'text_short'], ['first_name', 'Nombres', 'text_short'], ['last_name', 'Apellidos', 'text_short'], ['role', 'Cargo', 'text_short'], ['entity', 'Entidad', 'text_short'],
    ['phone', 'Teléfono', 'text_short'], ['email', 'Correo', 'email'], ['opcional_1', 'Ciudad', 'text_short'], ['opcional_2', 'Talla', 'select']].map(([key, label, field_type]) => ({ key, label, field_type, required: false }));
  const view = { env_enabled: true, enabled: true, definition: def(), fields: cfgs };
  const model = D.toModel(view);
  assert.strictEqual(model.items.length, 9, 'todos los campos del evento'); assert.deepStrictEqual(model.sheets.map((s) => s.id), ['datos', 'mas']);
  const byKey = Object.fromEntries(model.items.map((i) => [i.key, i]));
  assert.strictEqual(byKey.last_name.joined, true, 'apellidos va junto a nombres'); assert.strictEqual(byKey.first_name.joined, false);
  assert.strictEqual(byKey.id.required, true); assert.strictEqual(byKey.id.canRequire, false, 'la cédula siempre es obligatoria: no se cambia');
  assert.strictEqual(byKey.last_name.canRequire, false, 'los apellidos nunca se exigen');
  assert.strictEqual(byKey.phone.canCase, false, 'teléfono: sin «Texto al escribir»'); assert.strictEqual(byKey.email.canCase, false); assert.strictEqual(byKey.opcional_2.canCase, false, 'lista: sin «Texto al escribir»');
  assert.strictEqual(byKey.opcional_1.canCase, true); assert.strictEqual(byKey.first_name.text_case, 'upper');
  const body = D.fromModel(model);
  assert.deepStrictEqual(body.rows, def().rows, 'sin tocar nada, las filas son las mismas');
  assert.strictEqual(body.fields.id.required, undefined, 'no se manda lo que no se puede cambiar'); assert.strictEqual(body.fields.first_name.text_case, 'upper');
  assert.strictEqual(body.enabled, true);

  // mover, agrupar, unir filas (máx. 4), obligatorio, condición simple
  assert.strictEqual(D.move(model, 'phone', -1), true); assert.deepStrictEqual(model.items.filter((i) => i.sheet === 'mas').map((i) => i.key).slice(0, 4), ['role', 'phone', 'entity', 'email']);
  assert.strictEqual(D.move(model, 'id', -1), false, 'el primero de su grupo no sube más');
  model.items.forEach((i) => { if (i.sheet === 'mas') i.joined = true; });
  model.items.find((i) => i.key === 'role').joined = false;
  const rows = D.fromModel(model).rows.filter((r) => r.sheet === 'mas');
  assert.ok(rows.every((r) => r.items.length <= 4), 'una fila admite hasta 4'); assert.deepStrictEqual(rows.map((r) => r.items.length), [4, 2]);
  const ent = model.items.find((i) => i.key === 'entity'); ent.required = true; ent.showField = 'phone'; ent.showValue = ' 300 ';
  const out = D.fromModel(model).fields;
  assert.strictEqual(out.entity.required, true); assert.deepStrictEqual(out.entity.show_if, { field: 'phone', op: 'equals', value: '300' });
  ent.showValue = ''; assert.strictEqual(D.fromModel(model).fields.entity.show_if, undefined, 'sin valor no hay condición');
  // una condición avanzada hecha en otra parte se conserva tal cual
  const adv = { match: 'any', rules: [{ field: 'phone', op: 'filled' }, { field: 'role', op: 'contains', value: 'x' }] };
  const m2 = D.toModel({ ...view, definition: def({ fields: { ...def().fields, opcional_2: { required: false, show_if: adv } } }) });
  assert.deepStrictEqual(D.fromModel(m2).fields.opcional_2.show_if, adv);
  // grupos
  const g = D.addSheet(model, 'Extras'); assert.strictEqual(model.sheets.length, 3); assert.ok(/^[A-Za-z0-9_]{1,40}$/.test(g.id));
  model.items.find((i) => i.key === 'opcional_1').sheet = g.id;
  assert.strictEqual(D.removeSheet(model, g.id), true); assert.strictEqual(model.items.find((i) => i.key === 'opcional_1').sheet, 'datos', 'al quitar un grupo sus campos pasan a otro: no se pierde ninguno');
  const solo = { sheets: [{ id: 'a', title: 'A', open: true }], items: [] }; assert.strictEqual(D.removeSheet(solo, 'a'), false, 'siempre queda al menos un grupo');
  console.log('person_form_check: OK');
})().catch((e) => { console.error(e); process.exit(1); });
