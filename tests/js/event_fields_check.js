/* Renderizador compartido de campos de la plantilla (static/js/event-field-render.js): HTML escapado, lectura de controles, validación espejo del servidor, formato y contrato del calendario. Sin DOM real. */
const assert = require('assert');
const EF = require('../../static/js/event-field-render.js');

const F = (type, extra) => Object.assign({ key: 'c_x', type, title: 'Campo', required: false, options: [], config: {}, help: '', retired: false }, extra || {});

// 1) Todo texto del administrador sale ESCAPADO (título, ayuda, opciones, valor)
const evil = '<img src=x onerror=alert(1)>"\'&';
let html = EF.renderField(F('select', { title: evil, help: evil, options: [evil, 'B'] }), { value: evil });
assert.ok(!/<img/i.test(html) && !/onerror=alert/.test(html.replace(/&lt;img[^]*?&gt;/g, '')), html);
assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;&quot;&#39;&amp;'));
html = EF.renderField(F('text_short', { title: evil, required: true }), { value: evil });
assert.ok(!/<img/i.test(html) && html.includes('aria-required="true"') && html.includes('gw-req'));
html = EF.renderField(F('contact', { title: evil }), { value: { name: evil, phone: evil } });
assert.ok(!/<img/i.test(html));
html = EF.renderField(F('inventory', { config: { inventory_types: [{ key: 'a', label: evil, refs: [evil] }] } }), { value: [{ type: 'a', qty: 3, ref: evil }] });
assert.ok(!/<img/i.test(html), 'inventario escapado');
assert.ok(!/<img/i.test(EF.renderField(F('commercial'), { ctx: { people: { commercial: [{ id: 1, name: evil }] } } })));

// 2) Ocultos y solo lectura
assert.strictEqual(EF.renderField(F('text_short'), { ctx: { hidden: { c_x: true } } }), '');
assert.ok(EF.renderField(F('text_short'), { ctx: { readonly: { c_x: true } } }).includes(' readonly'));

// 3) Cada tipo pinta un control con data-evf-key
['text_short', 'text_long', 'select', 'money', 'number', 'commercial', 'coordinator', 'date', 'time', 'datetime', 'country', 'city', 'address_map', 'contact', 'bandana_colors', 'inventory', 'switch', 'super_event', 'client'].forEach((t) => {
  const h = EF.renderField(F(t, t === 'switch' ? { config: { switch: 'facial_enabled' } } : {}));
  assert.ok(h.includes('data-evf-key="') || (t === 'inventory' && h.includes('data-evf-act="inv-add"')), t + ' sin control');          // el inventario nace sin líneas: solo el botón «Agregar línea»
  assert.ok(h.includes('data-evf-type="' + t + '"'));
});

// 4) Lectura con controles falsos (misma interfaz mínima que el DOM: querySelectorAll + dataset + value/checked)
const el = (part, value, extra) => Object.assign({ dataset: { evfPart: part }, value: value == null ? '' : value }, extra || {});
const root = (key, els) => ({ querySelectorAll: (sel) => (sel === '[data-evf-key="' + key + '"]' ? els.map((e) => Object.assign(e, { dataset: Object.assign({ evfKey: key }, e.dataset) })) : []) });
assert.strictEqual(EF.readField(F('text_short'), root('c_x', [el('v', '  hola ')])), 'hola');
assert.strictEqual(EF.readField(F('text_short'), root('c_x', [el('v', '  ')])), null);
assert.strictEqual(EF.readField(F('switch'), root('c_x', [el('v', 'on', { checked: true })])), true);
assert.strictEqual(EF.readField(F('switch'), root('c_x', [el('v', 'on', { checked: false })])), false);
assert.strictEqual(EF.readField(F('commercial'), root('c_x', [el('v', '7')])), 7);
assert.strictEqual(EF.readField(F('commercial'), root('c_x', [el('v', '')])), null);
assert.strictEqual(EF.readField(F('datetime'), root('c_x', [el('date', '2026-11-07'), el('time', '08:30')])), '2026-11-07T08:30');
assert.strictEqual(EF.readField(F('datetime'), root('c_x', [el('date', ''), el('time', '')])), null);
assert.deepStrictEqual(EF.readField(F('address_map'), root('c_x', [el('text', 'Cl 1'), el('lat', '4.7'), el('lng', '-74.07')])), { text: 'Cl 1', lat: 4.7, lng: -74.07 });
assert.strictEqual(EF.readField(F('address_map'), root('c_x', [el('text', ''), el('lat', ''), el('lng', '')])), null);
assert.deepStrictEqual(EF.readField(F('contact'), root('c_x', [el('name', 'Ana'), el('phone', '300')])), { name: 'Ana', phone: '300' });
assert.deepStrictEqual(EF.readField(F('bandana_colors'), root('c_x', [el('hex', '#c0392b'), el('name', 'Rojo')])), [{ name: 'Rojo', hex: '#c0392b' }]);
assert.deepStrictEqual(EF.readField(F('bandana_colors', { config: { max: 2 } }), root('c_x', [el('use', 'on', { checked: true }), el('hex', '#111111'), el('name', 'A'), el('use', 'on', { checked: false }), el('hex', '#222222'), el('name', 'B')])), [{ name: 'A', hex: '#111111' }]);
assert.deepStrictEqual(EF.readField(F('inventory'), root('c_x', [el('type', 'pa'), el('qty', '5'), el('ref', 'Roja'), el('type', 'cu'), el('qty', ''), el('ref', '')])), [{ type: 'pa', qty: 5, ref: 'Roja' }, { type: 'cu', qty: null, ref: null }]);

// 5) Validación (espejo)
const v = (f, x) => EF.validateValue(f, x);
assert.strictEqual(v(F('text_short', { required: true }), ''), '«Campo» es obligatorio');
assert.strictEqual(v(F('text_short'), ''), null);
assert.ok(v(F('text_short'), '<b>'));
assert.ok(v(F('select', { options: ['a'] }), 'b'));
assert.strictEqual(v(F('select', { options: ['a'] }), 'a'), null);
assert.ok(v(F('money'), 'abc')); assert.ok(v(F('money'), '-5')); assert.strictEqual(v(F('money'), '1500000'), null);
assert.ok(v(F('number', { config: { min: 0, max: 10, decimals: 0 } }), '11')); assert.ok(v(F('number', { config: { decimals: 0 } }), '1.5')); assert.strictEqual(v(F('number', { config: { decimals: 1 } }), '1,5'), null);
assert.ok(v(F('date'), '2026-13')); assert.strictEqual(v(F('date'), '2026-11-07'), null);
assert.ok(v(F('time'), '25:00')); assert.strictEqual(v(F('time'), '8:05'), null);
assert.ok(v(F('datetime'), '2026-11-07T')); assert.strictEqual(v(F('datetime'), '2026-11-07T08:00'), null);
assert.ok(v(F('contact'), { name: 'A', phone: '12' })); assert.strictEqual(v(F('contact'), { name: 'A', phone: '3001234567' }), null);
assert.ok(v(F('address_map'), { text: 'x', lat: 1, lng: null }));
assert.ok(v(F('bandana_colors'), [{ hex: 'rojo' }]));
assert.ok(v(F('inventory'), [{ type: 'a', qty: -1 }]));
assert.strictEqual(v(F('switch', { required: true }), false), null);

// 6) Formato y valores de un evento
assert.strictEqual(EF.formatValue(F('money', { config: { currency: 'COP' } }), 1500000), '$ 1.500.000');
assert.strictEqual(EF.formatValue(F('money', { config: { currency: 'USD' } }), 99.5), 'US$ 99,50');
assert.strictEqual(EF.formatValue(F('date'), '2026-11-07'), '07/11/2026');
assert.strictEqual(EF.formatValue(F('datetime'), '2026-11-07T08:30'), '07/11/2026 08:30');
assert.strictEqual(EF.formatValue(F('switch'), true), 'Sí');
assert.strictEqual(EF.formatValue(F('commercial'), 3, { people: { commercial: [{ id: 3, name: 'Ana' }] } }), 'Ana');
assert.strictEqual(EF.formatValue(F('contact'), { name: 'Ana', phone: '300' }), 'Ana · 300');
assert.strictEqual(EF.formatValue(F('bandana_colors'), [{ name: 'Rojo', hex: '#fff000' }, { name: '', hex: '#000000' }]), 'Rojo, #000000');
assert.strictEqual(EF.formatValue(F('inventory', { config: { inventory_types: [{ key: 'pa', label: 'Pañoletas', refs: ['Roja'] }] } }), [{ type: 'pa', qty: 10, ref: 'Roja' }]), '10 Pañoletas (Roja)');
assert.strictEqual(EF.formatValue(F('text_short'), ''), '');

// 7) Contrato del calendario: layout + evento sin valores extra (eventos viejos) y con ellos
const tpl = {
  version: 4, people: { commercial: [{ id: 9, name: 'Luz' }], coordinator: [] },
  fields: [F('text_short', { key: 'name', title: 'Nombre del evento' }), F('select', { key: 'c_tipo', title: 'Tipo', options: ['Feria'] }), F('money', { key: 'c_valor', title: 'Valor' }), F('switch', { key: 'sw_facial_enabled', title: 'Rostro', config: { switch: 'facial_enabled' } }),
    F('commercial', { key: 'commercial_staff_id', title: 'Comercial' }), F('text_short', { key: 'c_viejo', title: 'Viejo', retired: true }), F('date', { key: 'start_date', title: 'Inicio' })],
  calendar_layout: { zones: { top: [{ key: 'name', label: false }], left: [{ key: 'start_date', label: true }, { key: 'c_tipo', label: true }], right: [{ key: 'c_valor', label: true }, { key: 'sw_facial_enabled', label: true }], bottom: [{ key: 'commercial_staff_id', label: true }, { key: 'c_viejo', label: true }, { key: 'no_existe', label: true }] } },
};
const layout = EF.calendarLayout(tpl);
assert.strictEqual(layout.version, 4);
const oldEvent = { id: 1, name: 'Feria', start_date: '2026-11-01', commercial_name: 'Luz', switches: { facial_enabled: false } };          // sin `extra`
let model = EF.cardModel(oldEvent, layout);
assert.deepStrictEqual(model.top.map((x) => x.text), ['Feria']);
assert.deepStrictEqual(model.left.map((x) => x.key), ['start_date']);                       // sin tipo: el campo sin valor no sale
assert.deepStrictEqual(model.right.map((x) => [x.key, x.text]), [['sw_facial_enabled', 'No']]);
assert.deepStrictEqual(model.bottom.map((x) => x.text), ['Luz']);                          // el retirado y el inexistente no salen
const newEvent = Object.assign({}, oldEvent, { extra: { c_tipo: 'Feria', c_valor: 2000000, c_viejo: 'dato antiguo' }, switches: { facial_enabled: true } });
model = EF.cardModel(newEvent, layout);
assert.deepStrictEqual(model.left.map((x) => x.text), ['01/11/2026', 'Feria']);
assert.deepStrictEqual(model.right.map((x) => x.text), ['$ 2.000.000', 'Sí']);
assert.ok(model.left.every((x) => x.label === true && x.title));
assert.strictEqual(EF.valueOf(tpl.fields[0], null), null);

console.log('event_fields_check: ok');
