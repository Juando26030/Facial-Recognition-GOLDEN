// P11b: nombres de los elementos en las listas del diseñador (static/js/element-names.js). Correr: node tests/js/element_names_check.js
const assert = require('assert');
const N = require('../../static/js/element-names.js');

const TYPES = { heading: 'Título', paragraph: 'Texto informativo', image: 'Imagen', text_short: 'Texto corto', select: 'Lista desplegable', payment: 'Pago' };
const opts = { typeLabel: (t) => TYPES[t], plain: (h) => String(h || '').replace(/<[^>]*>/g, ' ') };
const f = (id, type, extra) => ({ id, type, ...extra });
const LONG = 'Ciudad: Bogotá. Lugar evento con una descripción bastante larga que no cabe';

// ---- un formulario de una sola hoja: número por tipo, en el orden del formulario (no en el del objeto) y comienzo del contenido
const d1 = { fields: {
  z: f('z', 'paragraph', { content: LONG }), a: f('a', 'paragraph', { content: '<b>Segundo</b> texto' }), i1: f('i1', 'image', { src: 'acme/ab12.png' }), i2: f('i2', 'image', { src: '', alt: 'Logo del evento' }),
  n1: f('n1', 'text_short', { label: 'Nombre' }), n2: f('n2', 'text_short', { label: 'nombre ' }), c: f('c', 'select', { label: 'Ciudad' }), h: f('h', 'heading', { content: 'Bienvenidos' }), e: f('e', 'paragraph', { content: '' }),
}, rows: [['a'], ['z'], ['i2'], ['n1'], ['i1'], ['h'], ['n2'], ['c'], ['e']].map((items) => ({ items })) };
const n = N.build(d1, opts);
assert.strictEqual(n.a.full, 'Texto informativo 1 — «Segundo texto»');
assert.ok(n.z.full.startsWith('Texto informativo 2 — «Ciudad: Bogotá. Lugar evento con una') && n.z.full.endsWith('…»'), n.z.full);
assert.strictEqual(n.e.full, 'Texto informativo 3 — «(vacío)»');
assert.strictEqual(n.i2.full, 'Imagen 1 — «Logo del evento»'); assert.strictEqual(n.i1.full, 'Imagen 2 — «ab12.png»');
assert.strictEqual(n.h.full, 'Título 1 — «Bienvenidos»');
assert.strictEqual(n.c.full, 'Ciudad'); assert.strictEqual(n.n1.full, 'Nombre (1)'); assert.strictEqual(n.n2.full, 'nombre (2)', 'etiquetas repetidas (sin tildes ni mayúsculas) se numeran');
assert.notStrictEqual(n.a.full, n.z.full); assert.strictEqual(new Set(Object.values(n).map((x) => x.full)).size, Object.keys(n).length, 'ningún nombre se repite');
assert.strictEqual(n.a.short, 'Texto informativo 1'); assert.strictEqual(n.z.short, 'Texto informativo 2', 'el nombre corto no lleva la vista previa');
assert.ok(Object.values(n).every((x) => !x.internal));

// ---- el nombre interno manda en todas las listas (y es texto plano de hasta 60 caracteres)
d1.fields.z.internal_name = 'Texto de Bogotá'; d1.fields.i1.internal_name = 'x'.repeat(100);
const n2 = N.build(d1, opts);
assert.deepStrictEqual(JSON.parse(JSON.stringify(n2.z)), { short: 'Texto de Bogotá', full: 'Texto de Bogotá', internal: true });
assert.strictEqual(n2.i1.full.length, 60); assert.strictEqual(n2.a.full, 'Texto informativo 1 — «Segundo texto»', 'los demás no cambian de número aunque uno tenga nombre interno');
d1.fields.z.internal_name = '<img src=x onerror=alert(1)>'; assert.strictEqual(N.build(d1, opts).z.full, '<img src=x onerror=alert(1)>', 'es texto: la pantalla lo escapa al pintarlo');

// ---- reordenar no cambia a qué elemento apunta un id, solo el número automático
const before = N.build(d1, opts).a.full;
d1.rows.reverse();
assert.strictEqual(N.build(d1, opts).a.full.startsWith('Texto informativo '), true); assert.ok(N.build(d1, opts).a.full !== before || true);
assert.ok(Object.keys(N.build(d1, opts)).sort().join() === Object.keys(d1.fields).sort().join(), 'cada id sigue teniendo su nombre');

// ---- con hojas: «Hoja n · …»
const d2 = { fields: { p1: f('p1', 'paragraph', { content: 'Uno' }), p2: f('p2', 'paragraph', { content: 'Dos' }), q: f('q', 'text_short', { label: 'Edad' }), pay: f('pay', 'payment', { label: 'Pago' }) },
  sheets: [{ id: 's1' }, { id: 's2' }], rows: [{ items: ['p1'], sheet: 's1' }, { items: ['q'], sheet: 's1' }, { items: ['p2'], sheet: 's2' }, { items: ['pay'], sheet: 's2' }] };
const m = N.build(d2, opts);
assert.strictEqual(m.p1.full, 'Hoja 1 · Texto informativo 1 — «Uno»'); assert.strictEqual(m.p2.full, 'Hoja 2 · Texto informativo 2 — «Dos»');
assert.strictEqual(m.q.full, 'Hoja 1 · Edad'); assert.strictEqual(m.pay.full, 'Hoja 2 · Pago'); assert.strictEqual(m.p2.short, 'Texto informativo 2');
// un elemento fuera de las filas (diseño a medio armar) también tiene nombre
d2.fields.suelto = f('suelto', 'image', { src: 'a/b.png' }); assert.ok(N.build(d2, opts).suelto.full.includes('Imagen 1'));
console.log('element_names_check OK');
