// Editar evento con los campos de la plantilla: qué campos personalizados se muestran, en qué orden, y qué viaja en el PATCH (solo lo que cambió).
const assert = require('assert');
const EF = require('../../static/js/event-field-render.js');
const F = (key, type, extra) => Object.assign({ key, type, title: key, required: false, retired: false, options: [], config: {} }, extra || {});

const tpl = {
  fields: [F('name', 'text_short'), F('c_b', 'text_short'), F('c_a', 'money'), F('c_retirado', 'text_short', { retired: true }), F('sw_facial_enabled', 'switch'), F('c_sw', 'switch'), F('c_suelto', 'select', { options: ['x'] }), F('client', 'client')],
  creation_layout: { sections: [{ id: 's1', keys: ['name', 'c_a', 'client'] }, { id: 's2', keys: ['c_b', 'sw_facial_enabled', 'c_retirado'] }] },
};
// 1) solo personalizados activos, en el orden de «Nuevo evento»; los que no están en el diseño van al final; sin base ni interruptores ni retirados
assert.deepStrictEqual(EF.customFields(tpl).map((f) => f.key), ['c_a', 'c_b', 'c_suelto']);
assert.deepStrictEqual(EF.customFields(null), []);

// 2) el PATCH lleva solo lo que cambió
const fields = EF.customFields(tpl);
const values = { c_a: '1500000', c_b: 'nuevo texto', c_suelto: null };
const read = (f) => (f.key in values ? values[f.key] : null);
let got = EF.diffExtra(fields, { c_a: 1500000, c_b: 'viejo' }, read);          // 1500000 (número guardado) == '1500000' (texto del control): no cambió
assert.deepStrictEqual(got, { extra: { c_b: 'nuevo texto' } });
// 3) vaciar un campo que tenía valor lo manda como null (el servidor lo borra)
values.c_b = null;
assert.deepStrictEqual(EF.diffExtra(fields, { c_a: 1500000, c_b: 'viejo' }, read), { extra: { c_b: null } });
// 4) nada cambió -> extra vacío (el modal no manda `extra`)
assert.deepStrictEqual(EF.diffExtra(fields, { c_a: 1500000, c_b: null }, read), { extra: {} });
assert.deepStrictEqual(EF.diffExtra(fields, null, () => null), { extra: {} });
// 5) un obligatorio que el evento viejo nunca tuvo NO bloquea; vaciarlo si tenía, sí
const req = [F('c_r', 'text_short', { required: true, title: 'Dato' })];
assert.deepStrictEqual(EF.diffExtra(req, {}, () => null), { extra: {} });
got = EF.diffExtra(req, { c_r: 'algo' }, () => null);
assert.strictEqual(got.key, 'c_r'); assert(/obligatorio/.test(got.error));
// 6) formato inválido se frena con el motivo
got = EF.diffExtra([F('c_a', 'money', { title: 'Valor' })], {}, () => 'abc');
assert.strictEqual(got.key, 'c_a'); assert(/número/.test(got.error));
// 7) valores compuestos (inventario, pañoletas): se comparan por contenido
const inv = [F('c_i', 'inventory')];
const line = [{ type: 'pc', qty: 2, ref: null }];
assert.deepStrictEqual(EF.diffExtra(inv, { c_i: line }, () => [{ type: 'pc', qty: 2, ref: null }]), { extra: {} });
assert.deepStrictEqual(EF.diffExtra(inv, { c_i: line }, () => [{ type: 'pc', qty: 3, ref: null }]).extra, { c_i: [{ type: 'pc', qty: 3, ref: null }] });
console.log('event_edit_extra_check OK');
