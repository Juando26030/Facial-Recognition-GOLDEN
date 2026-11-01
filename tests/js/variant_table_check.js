// P11: tabla de variantes — lógica pura (static/js/variant-table.js): celdas, filas desde variables, tabla → variantes, ida y vuelta, pegar desde Excel e imágenes.
// Correr: node tests/js/variant_table_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const VT = require('../../static/js/variant-table.js');
const V = JSON.parse(fs.readFileSync(path.join(__dirname, '../variant_cell_vectors.json'), 'utf8'));
const J = (x) => JSON.parse(JSON.stringify(x));

// ---- celdas (mismos casos que pytest en el lado del servidor)
V.date.forEach(([raw, out]) => { const r = VT.parseCell('date', raw); assert.strictEqual(r.error ? null : r.value, out, 'fecha ' + raw); });
V.number.forEach(([raw, out]) => { const r = VT.parseCell('number', raw); assert.strictEqual(r.error ? null : r.value, out, 'número ' + raw); });
V.options.cases.forEach(([raw, out]) => { const r = VT.parseCell('options', raw, { options: V.options.options }); assert.strictEqual(r.error ? null : r.value, out, 'opción ' + raw); });
V.image.forEach(([raw, out]) => { const r = VT.parseCell('image', raw); assert.strictEqual(r.error ? null : r.value, out, 'imagen ' + raw); });
V.text.forEach(([raw, out]) => assert.strictEqual(VT.parseCell('text', raw).value, out));
assert.ok(VT.parseCell('text', 'x'.repeat(8001)).error, 'texto demasiado largo');

// ---- filas desde las variables
const CITIES = Array.from({ length: 31 }, (_, i) => `Ciudad ${String(i + 1).padStart(2, '0')}`), TYPES = ['Empleado', 'Invitado', 'Proveedor', 'Prensa'];
const vars = [{ field: 'c', label: 'Ciudad', options: CITIES }, { field: 't', label: 'Tipo', options: TYPES }];
let r = VT.rowsFromVariables(vars);
assert.strictEqual(r.rows.length, 124); assert.deepStrictEqual(J(r.rows[0].keys), ['Ciudad 01', 'Empleado']); assert.deepStrictEqual(J(r.rows[123].keys), ['Ciudad 31', 'Prensa']);
const ten = Array.from({ length: 10 }, (_, i) => 'E' + i);
r = VT.rowsFromVariables([vars[0], { field: 'e', label: 'Entidad', options: ten }]);
assert.ok(r.error && /310 combinaciones/.test(r.error) && /subconjunto/.test(r.error), r.error);
r = VT.rowsFromVariables([vars[0], { field: 'e', options: ten }], [CITIES.slice(0, 5), null]);
assert.strictEqual(r.rows.length, 50, 'con un subconjunto sí cabe');
assert.ok(VT.rowsFromVariables([]).error && VT.rowsFromVariables([vars[0], vars[0], vars[0], vars[0]]).error);

// ---- tabla → variantes
const mini = () => ({
  variables: [{ field: 'c', label: 'Ciudad', options: ['Bogotá', 'Cali', 'Pasto'] }],
  columns: [{ id: 'k1', name: 'Lugar', field: 'p', prop: 'content', type: 'text' }, { id: 'k2', name: 'Fecha', field: 'p2', prop: 'content', type: 'date' }, { id: 'k3', name: 'Foto', field: 'img', prop: 'src', type: 'image' }],
  rows: [{ keys: ['Bogotá'], cells: { k1: '<b>Chapinero</b>', k2: '5/3/26', k3: 'bogota.jpg' } }, { keys: ['Cali'], cells: { k1: 'Sur', k2: '', k3: '' } }, { keys: ['Pasto'], cells: {} }],
  images: { 'bogota.jpg': 'acme/abc123.jpg' },
});
let b = VT.build(mini(), {});
assert.ok(!b.error, b.error);
assert.deepStrictEqual(J(b.variants.p.content), { items: [{ when: { field: 'c', op: 'equals', value: 'Bogotá' }, value: '<b>Chapinero</b>', name: 'Bogotá' }, { when: { field: 'c', op: 'equals', value: 'Cali' }, value: 'Sur', name: 'Cali' }] });
assert.deepStrictEqual(J(b.variants.p2.content.items.map((i) => i.value)), ['05/03/2026'], 'la celda vacía no genera variante; la fecha queda normalizada');
assert.deepStrictEqual(J(b.variants.img.src.items.map((i) => i.value)), ['acme/abc123.jpg'], 'la imagen usa la ruta ya subida');
assert.deepStrictEqual(J(b.summary), { variants: 4, elements: 3, replaced: 0, rowsWithoutImage: 2, invalid: 0, notInList: 0 });
// dos variables → grupo Y; el servidor y el navegador lo evalúan igual que cualquier regla
const two = { variables: vars.slice(0, 2).map((v) => ({ ...v, options: [v.options[0], v.options[1]] })), columns: [{ id: 'a', name: 'Texto', field: 'p', prop: 'content', type: 'text' }], rows: [{ keys: ['Ciudad 01', 'Empleado'], cells: { a: 'uno' } }, { keys: ['Ciudad 01', 'Invitado'], cells: { a: 'dos' } }] };
b = VT.build(two, {});
assert.deepStrictEqual(J(b.variants.p.content.items[0].when), { match: 'all', rules: [{ field: 'c', op: 'equals', value: 'Ciudad 01' }, { field: 't', op: 'equals', value: 'Empleado' }] });
assert.strictEqual(b.variants.p.content.items[1].name, 'Ciudad 01 · Invitado');
// el valor por defecto que ya había se conserva y se cuenta lo que se reemplaza
b = VT.build(mini(), { p: { variants: { content: { items: [{ when: { field: 'c', op: 'equals', value: 'Cali' }, value: 'viejo' }, { when: { field: 'c', op: 'equals', value: 'Pasto' }, value: 'viejo2' }], default: 'Por defecto' } } } });
assert.strictEqual(b.variants.p.content.default, 'Por defecto'); assert.strictEqual(b.summary.replaced, 2);
// celdas inválidas se informan y no generan variante
const bad = mini(); bad.rows[0].cells.k2 = '31/02/2026';
b = VT.build(bad, {});
assert.strictEqual(b.summary.invalid, 1); assert.deepStrictEqual(J(b.problems.filter((p) => !p.soft)), [{ row: 0, col: 'k2', message: 'Fecha no válida (escribe dd/mm/aaaa)' }]);
assert.ok(!b.variants.p2, 'sin ninguna variante válida no se crea la propiedad');
// una opción que no está en la lista se cuenta aparte
const opt = { variables: mini().variables, columns: [{ id: 'o', name: 'Nivel', field: 'p', prop: 'help', type: 'options', options: ['Alto', 'Bajo'] }], rows: [{ keys: ['Bogotá'], cells: { o: 'alto' } }, { keys: ['Cali'], cells: { o: 'Medio' } }] };
b = VT.build(opt, {});
assert.strictEqual(b.summary.notInList, 1); assert.strictEqual(b.summary.invalid, 0); assert.strictEqual(b.summary.variants, 1);
// límites
const huge = mini(); huge.rows = Array.from({ length: 201 }, (_, i) => ({ keys: ['x' + i], cells: { k1: 'a' } }));
assert.ok(/200 filas/.test(VT.build(huge, {}).error));
const dup = mini(); dup.columns.push({ id: 'k4', name: 'Otra', field: 'p', prop: 'content', type: 'text' });
assert.ok(/apuntan a lo mismo/.test(VT.build(dup, {}).error));
assert.ok(/1 a 15 columnas/.test(VT.build({ ...mini(), columns: [] }, {}).error));
assert.ok(/3000/.test(VT.build(mini(), {}, { otherVariants: 2999 }).error), 'el total del formulario');
const many = mini(); many.columns = Array.from({ length: 16 }, (_, i) => ({ id: 'c' + i, name: 'C' + i, field: 'f' + i, prop: 'content', type: 'text' }));
assert.ok(/1 a 15 columnas/.test(VT.build(many, {}).error));

// ---- aplicar reemplaza SOLO las propiedades de las columnas, conserva lo demás y limpia lo que queda vacío
const design = { fields: { p: { id: 'p', type: 'paragraph', content: 'base', variants: { content: { items: [{ when: { field: 'c', op: 'equals', value: 'X' }, value: 'a' }] }, help: { items: [{ when: { field: 'c', op: 'equals', value: 'X' }, value: 'h' }] } } }, p2: { id: 'p2', type: 'paragraph', content: '' }, img: { id: 'img', type: 'image', src: '' } } };
VT.applyTo(design, VT.build(mini(), design.fields));
assert.strictEqual(design.fields.p.variants.content.items.length, 2, 'reemplazó content'); assert.ok(design.fields.p.variants.help, 'no tocó help');
assert.ok(design.fields.img.variants.src.items.length === 1);
const wipe = mini(); wipe.rows.forEach((row) => { row.cells = {}; });
VT.applyTo(design, VT.build(wipe, design.fields));
assert.ok(!design.fields.p2.variants && design.fields.p.variants.help && !design.fields.p.variants.content, 'sin nada que mostrar, la propiedad se quita y las demás se conservan');

// ---- ida y vuelta: del diseño a la tabla y de la tabla al mismo diseño
const d2 = { fields: { p: { id: 'p', type: 'paragraph', content: 'base' }, p2: { id: 'p2', type: 'paragraph', content: '' }, img: { id: 'img', type: 'image', src: '' } } };
VT.applyTo(d2, VT.build(mini(), d2.fields));
const blank = () => ({ variables: mini().variables, columns: mini().columns, rows: mini().rows.map((x) => ({ keys: x.keys, cells: {} })) });
const back = VT.fromDesign(d2, blank());
assert.strictEqual(back.skipped, 0);
assert.deepStrictEqual(J(back.rows.map((x) => x.cells.k1 || '')), ['<b>Chapinero</b>', 'Sur', '']);
assert.strictEqual(back.rows[0].cells.k3, 'acme/abc123.jpg');
const again = { ...mini(), rows: back.rows, images: {} };
const d3 = { fields: J(d2.fields) }; Object.values(d3.fields).forEach((f) => delete f.variants);
VT.applyTo(d3, VT.build(again, d3.fields));
assert.deepStrictEqual(J(d3.fields), J(d2.fields), 'descargar → subir deja el MISMO diseño');
// lo que no tiene forma de tabla no se toca ni se pierde: se cuenta
d2.fields.p.variants.content.items.push({ when: { match: 'any', rules: [{ field: 'c', op: 'equals', value: 'A' }, { field: 'c', op: 'equals', value: 'B' }] }, value: 'manual' });
d2.fields.p.variants.content.items.push({ when: { field: 'c', op: 'in', value: ['Cali', 'Pasto'] }, value: 'manual2' });
assert.strictEqual(VT.fromDesign(d2, blank()).skipped, 2);

// ---- pegar desde Excel
assert.deepStrictEqual(J(VT.parsePaste('a\tb\r\nc\t"d\te"\r\n"x ""y""\nz"\tq\r\n\r\n')), [['a', 'b'], ['c', 'd\te'], ['x "y"\nz', 'q']], 'comillas, tabuladores y saltos dentro de una celda');
assert.deepStrictEqual(J(VT.parsePaste('')), []);
assert.deepStrictEqual(J(VT.parsePaste('solo')), [['solo']]);
let spec = mini();
let pr = VT.pasteInto(spec, VT.parsePaste('Bogotá\tLugar nuevo\t7/8/26\nCALI\tÁrea\t\npasto\tX\t\nMedellín\tY\t\n'), { byKeys: true });
assert.strictEqual(pr.applied, 6); assert.deepStrictEqual(J(pr.unmatched), [3], 'una fila cuyo valor no está en la tabla se informa');
assert.strictEqual(spec.rows[0].cells.k1, 'Lugar nuevo'); assert.strictEqual(spec.rows[1].cells.k1, 'Área');
spec = mini();
pr = VT.pasteInto(spec, VT.parsePaste('Ciudad\tLugar\tFecha\tFoto\nBogotá\ta\tb\tc\n'), { byKeys: true });
assert.ok(pr.skippedHeader && spec.rows[0].cells.k1 === 'a', 'la fila de encabezados se salta');
spec = mini();
pr = VT.pasteInto(spec, VT.parsePaste('uno\ndos\ntres\ncuatro'), { startRow: 1, startCol: 0 });
assert.strictEqual(spec.rows[1].cells.k1, 'uno'); assert.strictEqual(spec.rows[2].cells.k1, 'dos'); assert.deepStrictEqual(J(pr.unmatched), [2, 3], 'lo que se pasa de las filas se informa');

// ---- imágenes: emparejar por nombre antes de subir
spec = mini();
let m = VT.matchImages(spec, ['bogota.jpg', 'CALI.PNG', 'Pasto_2.webp', 'doc.pdf', 'bogota.png']);
assert.deepStrictEqual(J(m.matches.map((x) => [x.file, x.row])), [['bogota.jpg', 0], ['CALI.PNG', 1]], 'sin tildes ni mayúsculas');
assert.deepStrictEqual(J(m.unmatched.map((x) => x.file)), ['Pasto_2.webp', 'doc.pdf']); assert.deepStrictEqual(J(m.duplicated), ['bogota.png'], 'dos archivos para la misma fila: gana el primero');
assert.strictEqual(m.rowsWithout, 1);
const two2 = { ...two, columns: [{ id: 'a', name: 'Foto', field: 'img', prop: 'src', type: 'image' }] };
m = VT.matchImages(two2, ['ciudad-01_empleado.jpg', 'Ciudad 01 Invitado.png', 'ciudad01.jpg']);
assert.deepStrictEqual(J(m.matches.map((x) => x.row)), [0, 1]); assert.strictEqual(m.unmatched.length, 1);
const multi = { ...two2, columns: [{ id: 'a', name: 'Foto', field: 'img', prop: 'src', type: 'image' }, { id: 'b', name: 'Logo', field: 'img2', prop: 'src', type: 'image' }] };
m = VT.matchImages(multi, ['ciudad-01_empleado@logo.png', 'ciudad-01_empleado.png']);
assert.deepStrictEqual(J(m.matches.map((x) => [x.row, x.col])), [[0, 'b']]); assert.ok(/varias columnas/.test(m.unmatched[0].reason));
assert.ok(/no tiene una columna de imagen/.test(VT.matchImages({ ...mini(), columns: [mini().columns[0]] }, ['a.jpg']).unmatched[0].reason));
// ---- plantillas de tabla (.json): solo columnas; nada de ids de campos
const cols = [{ id: 'k1', name: 'Lugar', field: 'p', prop: 'content', type: 'text' }, { id: 'k2', name: 'Nivel', field: 'q', prop: 'help', type: 'options', options: ['Alto', 'Bajo'] }, { id: 'k3', name: 'Foto', field: 'img', prop: 'src', type: 'image' }];
const json = VT.exportTemplate(cols, ['Ciudad', 'Tipo'], (id) => ({ p: 'Texto informativo', q: 'Nombre', img: 'Imagen' }[id]));
assert.ok(!/"field"|"id"/.test(json), 'la plantilla no lleva ids de campos');
const tpl = VT.parseTemplate(json);
assert.ok(!tpl.error, tpl.error);
assert.deepStrictEqual(J(tpl.columns), [{ name: 'Lugar', element: 'Texto informativo', prop: 'content', type: 'text', options: [] }, { name: 'Nivel', element: 'Nombre', prop: 'help', type: 'options', options: ['Alto', 'Bajo'] }, { name: 'Foto', element: 'Imagen', prop: 'src', type: 'image', options: [] }]);
assert.deepStrictEqual(J(tpl.variables), ['Ciudad', 'Tipo']);
const ok = (o) => JSON.stringify({ formato: 'goldenweb-plantilla-tabla', version: 1, columnas: [{ nombre: 'A', propiedad: 'content', tipo: 'text' }], ...o });
const err = (txt, re) => { const r = VT.parseTemplate(txt); assert.ok(r.error && re.test(r.error), `${txt.slice(0, 60)} -> ${r.error}`); };
err('x'.repeat(100001), /demasiado grande/); err('no es json {', /no es JSON/); err('[]', /no es una plantilla/); err('"hola"', /no es una plantilla/); err('null', /no es una plantilla/);
err(ok({ formato: 'otra-cosa' }), /no es una plantilla/); err(ok({ version: 2 }), /versión/);
err(ok({ columnas: 'x' }), /1 a 15 columnas/); err(ok({ columnas: [] }), /1 a 15 columnas/); err(ok({ columnas: Array.from({ length: 16 }, () => ({ nombre: 'A', propiedad: 'content', tipo: 'text' })) }), /1 a 15 columnas/);
err(ok({ columnas: [null] }), /no es válida/); err(ok({ columnas: [[]] }), /no es válida/); err(ok({ columnas: [{ propiedad: 'content', tipo: 'text' }] }), /no tiene nombre/);
err(ok({ columnas: [{ nombre: 'A', propiedad: 'onclick', tipo: 'text' }] }), /propiedad desconocida/); err(ok({ columnas: [{ nombre: 'A', propiedad: 'content', tipo: 'formula' }] }), /tipo desconocido/);
err(ok({ columnas: [{ nombre: 'A', propiedad: 'src', tipo: 'text' }] }), /imagen solo va/); err(ok({ columnas: [{ nombre: 'A', propiedad: 'content', tipo: 'image' }] }), /imagen solo va/);
err(ok({ columnas: [{ nombre: 'A', propiedad: 'help', tipo: 'options' }] }), /demasiadas opciones|al menos una/); err(ok({ columnas: [{ nombre: 'A', propiedad: 'help', tipo: 'options', opciones: [5, null, ''] }] }), /al menos una opción/);
err(ok({ columnas: [{ nombre: 'A', propiedad: 'help', tipo: 'options', opciones: Array.from({ length: 201 }, (_, i) => 'o' + i) }] }), /demasiadas opciones/);
const dd = VT.parseTemplate(ok({ columnas: [{ nombre: 'A', propiedad: 'help', tipo: 'options', opciones: ['Alto', 'alto', ' ALTO ', 'Bajo', 7, {}] }] }));
assert.deepStrictEqual(J(dd.columns[0].options), ['Alto', 'Bajo'], 'opciones sin repetidos (sin tildes ni mayúsculas) y solo texto');
const evilJson = '{"formato":"goldenweb-plantilla-tabla","version":1,"__proto__":{"polluted":true},"constructor":{"prototype":{"polluted":true}},"columnas":[{"nombre":"<img src=x onerror=alert(1)>' + String.fromCharCode(92) + 'u0000' + String.fromCharCode(92) + 'u001f' + 'x'.repeat(100) + '","propiedad":"content","tipo":"text","__proto__":{"polluted":true},"elemento":"' + 'y'.repeat(500) + '"}],"variables":["Ciudad",5,null,"a","b","c"]}';
const evil = VT.parseTemplate(evilJson);
assert.ok(!evil.error, evil.error); assert.strictEqual(({}).polluted, undefined, 'no contamina los objetos');
assert.strictEqual(evil.columns[0].name.length, 60); assert.ok(evil.columns[0].name.startsWith('<img src=x onerror=alert(1)>'), 'el nombre es texto: la pantalla lo escapa al pintarlo'); assert.ok(!/[ -]/.test(evil.columns[0].name));
assert.strictEqual(evil.columns[0].element.length, 200); assert.deepStrictEqual(J(evil.variables), ['Ciudad', 'a', 'b'], 'máximo 3 variables, solo texto');
console.log('variant_table_check OK');
