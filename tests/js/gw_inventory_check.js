/* Widget de inventario (static/js/gw-inventory.js): lógica pura + comportamiento con un DOM mínimo simulado. */
const assert = require('assert');
const I = require('../../static/js/gw-inventory.js');
const D = require('../../static/js/event-template-designer.js').model;
const fx = require('./event_template_default.json');

const def = { key: 'c_inv', title: 'Inventario', config: { inventory_types: [
  { key: 'comp', label: 'Computadores', refs: ['Dell', 'HP'] },
  { key: 'impr', label: 'Impresoras', refs: [] },
  { key: 'dig', label: 'Digitadores', refs: ['Ana', 'Luis', 'Marta'] }] } };

// parse / serialize
assert.deepStrictEqual(I.parse(null), { lines: [] });
assert.deepStrictEqual(I.parse('[{"type":"comp","qty":"2","ref":" Dell "}]'), { lines: [{ type: 'comp', qty: 2, ref: 'Dell' }] });
assert.deepStrictEqual(I.parse('no es json'), { lines: [] });
assert.deepStrictEqual(I.parse([null, 3, { type: 5 }, { type: 'impr', qty: 'x', ref: '' }]), { lines: [{ type: 'impr', qty: null, ref: null }] });
assert.strictEqual(I.serialize({ lines: [] }), null);
assert.strictEqual(I.serialize({ lines: [{ type: 'impr', qty: null, ref: null }, { type: 'impr', qty: 0, ref: null }] }), null, 'sin cantidad válida no es dato');
assert.deepStrictEqual(I.serialize({ lines: [{ type: 'impr', qty: '3', ref: '  ' }, { type: 'comp', qty: 2, ref: 'Dell' }] }), [{ type: 'impr', qty: 3, ref: null }, { type: 'comp', qty: 2, ref: 'Dell' }]);
const stored = [{ type: 'comp', qty: 2, ref: 'Dell' }, { type: 'impr', qty: 3, ref: 'Brother QL-800' }];
assert.deepStrictEqual(I.serialize(I.parse(stored)), stored, 'ida y vuelta');

// resumen (mismo texto que app/event_inventory.summary)
assert.strictEqual(I.summary(stored, def), 'Computadores ×2 — Dell; Impresoras ×3 — Brother QL-800');
assert.strictEqual(I.summary([{ type: 'impr', qty: 3, ref: null }], def.config), 'Impresoras ×3');
assert.strictEqual(I.summary([{ type: 'viejo', qty: 1 }], def), 'viejo ×1');
assert.strictEqual(I.summary(null, def), '');

// validar
assert.deepStrictEqual(I.validate(stored, def), []);
const v = (l) => I.validate(l, def);
assert.ok(v([{ type: 'zz', qty: 1 }])[0].includes('ya no existe'));
assert.ok(v([{ type: 'impr', qty: 0 }])[0].includes('mínima'));
assert.ok(v([{ type: 'impr', qty: -2 }])[0].includes('mínima'));
assert.ok(v([{ type: 'impr', qty: 2.5 }])[0].includes('cantidad'), 'decimal');
assert.ok(v([{ type: 'impr', qty: 100001 }])[0].includes('máxima'));
assert.ok(v([{ type: 'comp', qty: 1, ref: null }])[0].includes('Elige la referencia'));
assert.ok(v([{ type: 'comp', qty: 1, ref: 'Mac' }])[0].includes('ya no está'));
assert.ok(v([{ type: 'impr', qty: 1, ref: 'x'.repeat(81) }])[0].includes('80'));
assert.ok(v([{ type: 'impr', qty: 1, ref: '<b>' }])[0].includes('«<»'));
assert.ok(v([{ type: 'impr', qty: 1, ref: 'Epson' }, { type: 'impr', qty: 2, ref: 'epson' }])[0].includes('repetido'));
assert.strictEqual(v(Array.from({ length: 101 }, (_, i) => ({ type: 'impr', qty: 1, ref: 'r' + i })))[0], 'Se admiten hasta 100 líneas');
assert.deepStrictEqual(I.lineErrors([{ type: 'impr', qty: 1 }, { type: 'impr', qty: null }], def), ['', 'Escribe la cantidad (un número entero)']);

// agregar / quitar / ordenar
let r = I.addLine([], def, 'comp'); assert.deepStrictEqual(r, { lines: [{ type: 'comp', qty: 1, ref: null }], index: 0 });
assert.strictEqual(I.addLine([{ type: 'dig', qty: 1, ref: 'Ana' }, { type: 'dig', qty: 1, ref: 'Luis' }, { type: 'dig', qty: 1, ref: 'Marta' }], def, 'dig'), null, 'ya se usaron todas las referencias');
assert.ok(I.addLine([{ type: 'impr', qty: 1, ref: 'a' }], def, 'impr'), 'texto libre admite más líneas');
assert.strictEqual(I.addLine([], def, 'inexistente'), null);
assert.strictEqual(I.addLine(Array.from({ length: 100 }, (_, i) => ({ type: 'impr', qty: 1, ref: 'r' + i })), def, 'impr'), null, 'tope de líneas');
const mix = [{ type: 'dig', qty: 1, ref: 'Ana' }, { type: 'comp', qty: 1, ref: 'HP' }, { type: 'dig', qty: 2, ref: 'Luis' }];
assert.deepStrictEqual(I.sortLines(mix, def).map((l) => l.type + (l.ref || '')), ['compHP', 'digAna', 'digLuis']);
assert.deepStrictEqual(I.removeLine(mix, 1).map((l) => l.type), ['dig', 'dig']);
assert.deepStrictEqual(I.removeType(mix, 'dig').map((l) => l.type), ['comp']);
assert.deepStrictEqual(I.grouped(mix, def).map((g) => g.type.key + ':' + g.items.map((i) => i.index).join(',')), ['comp:1', 'dig:0,2']);
assert.strictEqual(I.grouped([{ type: 'viejo', qty: 1 }], def)[0].type.label, 'Tipo que ya no existe');

// compatibilidad con lo que guarda la plantilla (diseñador): tipos con refs
const seq = (n) => { let x = (n * 2654435761 + 12345) % 2147483647; return () => { x = (x * 48271) % 2147483647; return x / 2147483647; }; };
const m = D.fromServer(JSON.parse(JSON.stringify(fx)));
const k = D.addField(m, 'inventory', m.sections[0].id, seq(7));
assert.strictEqual(D.addInventoryTypesFromText(m, k, 'Computadores\n\n Impresoras \ncomputadores\nDigitadores ñandú\n'), 3, 'reemplaza el tipo de ejemplo, ignora vacíos y repetidos');
const ts = D.field(m, k).config.inventory_types;
assert.deepStrictEqual(ts.map((t) => t.label), ['Computadores', 'Impresoras', 'Digitadores ñandú']);
assert.deepStrictEqual(ts.map((t) => t.key), ['computadores', 'impresoras', 'digitadores_nandu']);
assert.ok(ts.every((t) => /^[a-z][a-z0-9_]{0,23}$/.test(t.key)) && ts.every((t) => Array.isArray(t.refs)));
assert.strictEqual(D.addInventoryTypesFromText(m, k, 'Impresoras'), 0);
assert.strictEqual(D.addInventoryTypesFromText(m, k, 'Impresoras 2\nCámaras 4K\n3D'), 3);
assert.ok(D.field(m, k).config.inventory_types.every((t, i, a) => a.findIndex((x) => x.key === t.key) === i), 'claves únicas');
assert.deepStrictEqual(D.validate(m), []);
D.field(m, k).config.inventory_types[0].refs = ['<b>'];
assert.ok(D.validate(m).some((x) => x.includes('«<»')));
D.field(m, k).config.inventory_types[0].refs = [];
D.field(m, k).config.inventory_types[1].label = 'computadores';
assert.ok(D.validate(m).some((x) => x.includes('repetido')));
const big = D.addField(m, 'inventory', m.sections[0].id, seq(7));
D.addInventoryTypesFromText(m, big, Array.from({ length: 30 }, (_, i) => 'T' + i).join('\n'));
assert.strictEqual(D.field(m, big).config.inventory_types.length, 20, 'tope de tipos');

// comportamiento con DOM mínimo
class El {
  constructor() { this.dataset = {}; this.l = {}; this._html = ''; this.children = []; }
  addEventListener(t, f) { (this.l[t] = this.l[t] || []).push(f); }
  dispatchEvent(ev) { (this.l[ev.type] || []).forEach((f) => f(ev)); (this.events = this.events || []).push(ev); return true; }
  querySelector() { return null; } querySelectorAll() { return []; } contains() { return true; }
  set innerHTML(v) { this._html = v; } get innerHTML() { return this._html; }
}
global.CustomEvent = class { constructor(type, o) { this.type = type; this.detail = o && o.detail; } };
const box = new El(); box.querySelector = (sel) => (sel.includes('data-evf-for') ? { getAttribute: (a) => (a === 'data-evf-for' ? 'c_inv' : null) } : null);
const ctl = I.enhance(box, { field: def, value: stored });
assert.ok(ctl && box.dataset.gwiReady === '1');
const html = box.innerHTML;
assert.ok(html.includes('aria-pressed="true"') && html.includes('data-evf-part="qty"') && html.includes('data-evf-part="ref"') && html.includes('data-evf-part="type"'));
assert.ok(html.includes('Resumen:</strong> ') === false, 'el resumen se pinta por separado');
assert.strictEqual(ctl.summary(), 'Computadores ×2 — Dell; Impresoras ×3 — Brother QL-800');
assert.strictEqual(I.enhance(box, { field: def }), ctl, 'idempotente');
ctl.setValue([{ type: 'impr', qty: 2, ref: 'Epson' }]);
assert.deepStrictEqual(ctl.getValue(), [{ type: 'impr', qty: 2, ref: 'Epson' }]);
assert.strictEqual(box.events[box.events.length - 1].type, 'gw:inventory-change');
assert.strictEqual(box.events[box.events.length - 1].detail.summary, 'Impresoras ×2 — Epson');
assert.deepStrictEqual(ctl.validate(), []);
ctl.setValue([{ type: 'comp', qty: 1, ref: null }]);
assert.strictEqual(ctl.validate().length, 1);
assert.ok(box.innerHTML.includes('data-gwi-act="add"'));

// escapado de lo que escribe el administrador
const evil = '<img src=x onerror=alert(1)>"\'&';
const b2 = new El(); I.enhance(b2, { field: { key: 'c_i', title: evil, config: { inventory_types: [{ key: 'a', label: evil, refs: [evil, 'ok'] }] } }, value: [{ type: 'a', qty: 3, ref: evil }] });
assert.ok(!/<img/i.test(b2.innerHTML) && b2.innerHTML.includes('&lt;img'), 'inventario escapado');
// sin tipos: aviso, no se rompe
const b3 = new El(); assert.ok(I.enhance(b3, { field: { key: 'c_z', config: { inventory_types: [] } } }) && b3.innerHTML.includes('todavía no tiene tipos'));
assert.strictEqual(I.enhance(new El(), {}), null, 'sin definición no hace nada');
console.log('gw_inventory_check OK');
