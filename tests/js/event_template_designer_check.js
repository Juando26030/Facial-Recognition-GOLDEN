/* Modelo del diseñador de la plantilla de evento (static/js/event-template-designer.js): mover, agregar, quitar, retirar, obligatoriedad, calendario y las mismas reglas del servidor. Sin DOM. */
const assert = require('assert');
const D = require('../../static/js/event-template-designer.js').model;
const fx = require('./event_template_default.json');

const fresh = () => D.fromServer(JSON.parse(JSON.stringify(fx)));
const seq = (n) => { let x = (n * 2654435761 + 12345) % 2147483647; return () => { x = (x * 48271) % 2147483647; return x / 2147483647; }; };          // generador determinista con sucesión larga
const keysOf = (m, i) => m.sections[i].keys;

// 1) Carga y round-trip: lo que sale es lo que entró
let m = fresh();
assert.strictEqual(m.sections.length, 4);
assert.deepStrictEqual(D.validate(m), []);
const p = D.toPayload(m);
assert.strictEqual(p.version, 0);
assert.deepStrictEqual(p.creation_layout.sections, fx.creation_layout.sections);
assert.deepStrictEqual(p.calendar_layout.zones, fx.calendar_layout.zones);
assert.deepStrictEqual(p.fields, fx.fields);
p.fields[0].title = 'x';
assert.notStrictEqual(m.fields[0].title, 'x', 'toPayload debe copiar');

// 2) Disponibles: los interruptores y nada más de fábrica
assert.deepStrictEqual(D.unplaced(m).map((f) => f.type), ['workday', ...Array(10).fill('switch')]);          // la jornada (calculada) es opcional: de fábrica no está en ninguna vista
assert.strictEqual(D.calUnplaced(m).length, m.fields.length - 10);          // 10 campos ya salen en la tarjeta de fábrica

// 3) Agregar un campo de cada tipo creable: clave segura, título por defecto, configuración válida
const creatable = fx.catalog.types.filter((t) => t.creatable).map((t) => t.type);
assert.strictEqual(creatable.length, 16);
creatable.forEach((t, i) => {
  const k = D.addField(m, t, 'datos', seq(i));
  assert.ok(/^c_[a-z0-9]{8}$/.test(k), k);
  const f = D.field(m, k);
  assert.strictEqual(f.type, t); assert.ok(f.title); assert.strictEqual(f.required, false); assert.strictEqual(D.sectionIndexOf(m, k), 0);
});
assert.deepStrictEqual(D.validate(m), []);
assert.deepStrictEqual(D.field(m, keysOf(m, 0)[keysOf(m, 0).length - 1]).config, { inventory_types: [{ key: 'tipo1', label: 'Tipo 1', refs: [] }] });
const cityKey = keysOf(m, 0).find((k) => D.field(m, k).type === 'city' && D.isCustom(k));
assert.strictEqual(D.field(m, cityKey).config.country_key, D.active(m).find((f) => f.type === 'country').key);
const keyDup = new Set(m.fields.map((f) => f.key)); assert.strictEqual(keyDup.size, m.fields.length);
// tope de campos activos
const full = fresh();
while (D.addField(full, 'text_short', 'datos', seq(3)) !== null) { /* hasta el tope */ }
assert.strictEqual(D.active(full).length, D.LIMITS.active);

// 4) Mover: dentro del paso, entre pasos (arrastrar) y con subir/bajar en el borde
m = fresh();
assert.strictEqual(D.place(m, 'notes', 'datos', 0), true);
assert.strictEqual(keysOf(m, 0)[0], 'notes'); assert.ok(!keysOf(m, 3).includes('notes'));
assert.strictEqual(D.moveBy(m, 'notes', 1), true); assert.strictEqual(keysOf(m, 0)[1], 'notes');
const last0 = keysOf(m, 0)[keysOf(m, 0).length - 1];
assert.strictEqual(D.moveBy(m, last0, 1), true);                       // baja al paso siguiente
assert.strictEqual(keysOf(m, 1)[0], last0);
assert.strictEqual(D.moveBy(m, keysOf(m, 0)[0], -1), false);           // el primero de todos no sube más
assert.strictEqual(D.place(m, 'no_existe', 'datos'), false);
assert.strictEqual(D.place(m, 'name', 'paso_raro'), false);
assert.strictEqual(new Set(m.sections.flatMap((s) => s.keys)).size, m.sections.flatMap((s) => s.keys).length, 'un campo nunca queda duplicado');

// 5) Quitar de la vista: obligatorio pasa a opcional; los fijos no se pueden quitar
m = fresh();
let r = D.unplace(m, 'event_code'); assert.strictEqual(r.ok, false);
r = D.unplace(m, 'client'); assert.strictEqual(r.ok, false);
r = D.unplace(m, 'address'); assert.strictEqual(r.ok, true); assert.ok(r.note.includes('opcional'));
assert.strictEqual(D.field(m, 'address').required, false);
assert.strictEqual(D.sectionIndexOf(m, 'address'), -1);
assert.deepStrictEqual(D.validate(m), []);
assert.ok(D.unplaced(m).some((f) => f.key === 'address'));
r = D.unplace(m, 'notes'); assert.strictEqual(r.ok, true); assert.strictEqual(r.note, '');          // ya era opcional

// 6) Obligatoriedad
m = fresh();
assert.strictEqual(D.setRequired(m, 'name', false), false);             // fijo
assert.strictEqual(D.setRequired(m, 'sw_facial_enabled', true), false); // interruptor
assert.strictEqual(D.setRequired(m, 'notes', true), true); assert.strictEqual(D.field(m, 'notes').required, true);
D.unplace(m, 'super_event_id');
assert.strictEqual(D.setRequired(m, 'super_event_id', true), true); assert.ok(D.sectionIndexOf(m, 'super_event_id') >= 0, 'un obligatorio entra a la vista');
m.sections[0].keys = m.sections[0].keys.filter((k) => k !== 'country'); assert.ok(D.validate(m).some((x) => x.includes('«País» es obligatorio')));

// 7) Pasos
m = fresh();
const id = D.addSection(m, 'Extras', seq(5));
assert.ok(id && m.sections.length === 5);
assert.ok(D.validate(m).some((x) => x.includes('está vacío')));
D.place(m, 'notes', id);
assert.deepStrictEqual(D.validate(m), []);
for (let i = 0; i < 5; i++) D.addSection(m, 'x', seq(i + 9));
assert.strictEqual(m.sections.length, D.LIMITS.sections);
assert.strictEqual(D.addSection(m, 'más', seq(1)), null);
m = fresh();
assert.strictEqual(D.moveSection(m, 'revisa', -1), true); assert.strictEqual(m.sections[2].id, 'revisa');
assert.strictEqual(D.moveSection(m, 'datos', -1), false);
const before = m.sections.flatMap((s) => s.keys).length;
r = D.removeSection(m, 'fechas'); assert.strictEqual(r.ok, true);
assert.strictEqual(m.sections.flatMap((s) => s.keys).length, before, 'los campos del paso quitado pasan al vecino');
assert.deepStrictEqual(D.validate(m), []);
m.sections = m.sections.slice(0, 1); assert.strictEqual(D.removeSection(m, m.sections[0].id).ok, false);

// 8) Retirar un campo personalizado: sale de las dos vistas pero no se pierde; los del sistema no se retiran
m = fresh();
const kk = D.addField(m, 'select', 'datos', seq(2));
D.setRequired(m, kk, true); D.calPlace(m, kk, 'left');
assert.strictEqual(D.retire(m, 'name'), false);
assert.strictEqual(D.retire(m, kk), true);
assert.ok(D.field(m, kk).retired && !D.field(m, kk).required);
assert.strictEqual(D.sectionIndexOf(m, kk), -1); assert.strictEqual(D.zoneOf(m, kk), null);
assert.ok(!D.active(m).some((f) => f.key === kk) && D.retired(m).some((f) => f.key === kk));
assert.ok(D.toPayload(m).fields.some((f) => f.key === kk && f.retired === true), 'el retirado viaja para conservar su definición');
assert.strictEqual(D.place(m, kk, 'datos'), false, 'un retirado no se puede poner');
assert.strictEqual(D.restore(m, kk), true); assert.strictEqual(D.active(m).some((f) => f.key === kk), true);

// 9) Calendario: poner, mover entre zonas, nombre del campo, tope por zona, quitar
m = fresh();
assert.strictEqual(D.calPlace(m, 'notes', 'bottom', 0), true);
assert.strictEqual(m.zones.bottom[0].key, 'notes'); assert.strictEqual(D.zoneOf(m, 'notes'), 'bottom');
assert.strictEqual(D.calPlace(m, 'notes', 'left'), true); assert.strictEqual(D.zoneOf(m, 'notes'), 'left'); assert.ok(!m.zones.bottom.some((i) => i.key === 'notes'));
assert.strictEqual(D.calPlace(m, 'notes', 'centro'), false);
assert.strictEqual(D.calSetLabel(m, 'notes', false), true); assert.strictEqual(m.zones.left.find((i) => i.key === 'notes').label, false);
assert.strictEqual(D.calMoveBy(m, 'notes', -1), true); assert.strictEqual(m.zones.left[m.zones.left.length - 2].key, 'notes');
D.calUnplace(m, 'notes'); assert.strictEqual(D.zoneOf(m, 'notes'), null);
const noteZ = fresh();
let n = 0;
D.active(noteZ).filter((f) => !D.zoneOf(noteZ, f.key)).forEach((f) => { if (D.calPlace(noteZ, f.key, 'bottom')) n++; });
assert.strictEqual(noteZ.zones.bottom.length, D.LIMITS.zoneItems);
const keepZone = D.zoneOf(noteZ, 'name');
assert.strictEqual(D.calPlace(noteZ, 'name', 'bottom'), false); assert.strictEqual(D.zoneOf(noteZ, 'name'), keepZone, 'si la zona está llena el campo no se pierde');
assert.deepStrictEqual(D.validate(m), []);

// 10) Propiedades: opciones, inventario
assert.deepStrictEqual(D.parseLines(' A \n\na\nB\r\n  '), ['A', 'B']);
m = fresh();
const inv = D.addField(m, 'inventory', 'datos', seq(8));
assert.strictEqual(D.addInventoryType(m, inv), true); assert.strictEqual(D.field(m, inv).config.inventory_types.length, 2);
assert.strictEqual(D.removeInventoryType(m, inv, 'tipo1'), true);
assert.strictEqual(D.removeInventoryType(m, inv, D.field(m, inv).config.inventory_types[0].key), false, 'queda al menos un tipo');
const sel = D.addField(m, 'select', 'datos', seq(4));
D.field(m, sel).options = [];
assert.ok(D.validate(m).some((x) => x.includes('al menos una opción')));
D.field(m, sel).title = '<b>x</b>';
assert.ok(D.validate(m).some((x) => x.includes('«<»')));
D.field(m, sel).title = ' ';
assert.ok(D.validate(m).some((x) => x.includes('sin título')));

// 11) Vista previa: valores de ejemplo para todos los tipos y la tarjeta se arma con los campos puestos
m = fresh();
const kinds = creatable.map((t, i) => D.addField(m, t, 'datos', seq(i + 20)));
kinds.forEach((k, i) => D.calPlace(m, k, D.ZONES[i % 4]));
const ev = D.sampleEvent(m);
kinds.forEach((k) => assert.ok(ev.extra[k] !== undefined, 'sin ejemplo para ' + D.field(m, k).type));
const EF = require('../../static/js/event-field-render.js');
const cm = EF.cardModel(ev, EF.calendarLayout({ fields: m.fields, calendar_layout: { zones: m.zones }, people: { commercial: [{ id: 1, name: 'P' }], coordinator: [{ id: 1, name: 'P' }] } }));
assert.strictEqual(['top', 'left', 'right', 'bottom'].reduce((a, z) => a + cm[z].filter((x) => D.isCustom(x.key)).length, 0), kinds.length, 'todo tipo muestra algo en la tarjeta de ejemplo');
assert.ok(cm.top.some((x) => x.key === 'name'));

console.log('event_template_designer_check: ok');
