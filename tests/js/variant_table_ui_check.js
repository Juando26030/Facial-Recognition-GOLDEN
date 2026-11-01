// P11: pantalla de la tabla de variantes (static/js/variant-table-ui.js) con jsdom y un contexto de diseñador de mentira.
// Correr: npm ci && node tests/js/variant_table_ui_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const dom = new JSDOM('<!doctype html><body><div id="host"></div></body>', { runScripts: 'outside-only', url: 'https://example.test/' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/element-names.js', 'static/js/variant-table.js', 'static/js/variant-table-ui.js'].forEach((f) => w.eval(fs.readFileSync(path.join(root, f), 'utf8')));
const CITIES = Array.from({ length: 31 }, (_, i) => `Ciudad ${String(i + 1).padStart(2, '0')}`), TYPES = ['Empleado', 'Invitado', 'Proveedor', 'Prensa'];
const J = (x) => JSON.parse(JSON.stringify(x));
const design = { fields: {
  c: { id: 'c', type: 'select', label: 'Ciudad', options: CITIES }, t: { id: 't', type: 'select', label: 'Tipo', options: TYPES },
  e: { id: 'e', type: 'select', label: 'Entidad', options: Array.from({ length: 10 }, (_, i) => 'E' + i) },
  p: { id: 'p', type: 'paragraph', content: 'Base' }, p2: { id: 'p2', type: 'paragraph', content: '' }, img: { id: 'img', type: 'image', src: '' },
  late: { id: 'late', type: 'select', label: 'Tardío', options: ['x', 'y'] } } };
const sheetIdx = { c: 0, t: 0, e: 0, p: 0, p2: 0, img: 0, late: 1 };
const log = { toasts: [], confirms: [], fetches: [], applied: [] };
let confirmAnswer = true, richAnswer = '<b>Con formato</b>';
const label = (id) => ({ c: 'Ciudad', t: 'Tipo', e: 'Entidad', p: 'Texto informativo', p2: 'Segundo texto', img: 'Imagen', late: 'Tardío' }[id]);
const propsOf = (id) => (design.fields[id].type === 'image' ? ['src'] : ['paragraph'].includes(design.fields[id].type) ? ['content'] : ['display_label', 'help']);
const ctx = {
  url: '/api/events/1/forms/2/variant-table', design: () => design,
  fields: () => Object.values(design.fields).filter((f) => propsOf(f.id).length).map((f) => ({ id: f.id, label: label(f.id) })),
  optionsOf: (id) => design.fields[id].options || null, fieldLabel: label, propsOf, propLabel: (p) => ({ content: 'Texto', src: 'Imagen', display_label: 'Nombre', help: 'Ayuda' }[p]), sheetOf: (id) => sheetIdx[id],
  assetUrl: (p) => p, toast: (m, k) => log.toasts.push([m, k]), confirm: async (m) => { log.confirms.push(m); return confirmAnswer; }, richEdit: async () => richAnswer,
  apply(built) {
    const before = JSON.stringify(design.fields);
    w.VariantTable.applyTo(design, built); log.applied.push(built);
    return () => { design.fields = JSON.parse(before); return true; };
  },
};
w.fetch = async (url, o) => { log.fetches.push([url, o]); return w.__fetchAnswer(url, o); };
log.blobs = []; w.URL.createObjectURL = (blob) => { log.blobs.push(blob); return 'blob:x'; }; w.URL.revokeObjectURL = () => {};
log.downloads = []; w.HTMLAnchorElement.prototype.click = function () { log.downloads.push(this.download); };
const host = w.document.getElementById('host');
const t0 = process.hrtime.bigint();
const ui = w.VariantTableUI.mount(host, ctx);
const tick = (ms) => new Promise((r) => setTimeout(r, ms || 0));
const q = (s) => host.querySelector(s), qa = (s) => Array.from(host.querySelectorAll(s));
const pickVar = (i, v) => { const el = q(`[data-vt-var="${i}"]`); el.value = v; el.dispatchEvent(new w.Event('change', { bubbles: true })); };
const click = (el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
const addCol = (field, prop, type, name) => {
  click(q('[data-vt-act="addcol"]')); const i = ui.state.columns.length - 1;
  const f = q(`[data-vt-colfield="${i}"]`); f.value = field; f.dispatchEvent(new w.Event('change', { bubbles: true }));
  if (prop) { const p = q(`[data-vt-colprop="${i}"]`); p.value = prop; p.dispatchEvent(new w.Event('change', { bubbles: true })); }
  if (type) { const t = q(`[data-vt-coltype="${i}"]`); t.value = type; t.dispatchEvent(new w.Event('change', { bubbles: true })); }
  if (name) { const n = q(`[data-vt-colname="${i}"]`); n.value = name; n.dispatchEvent(new w.Event('input', { bubbles: true })); }
};
const cell = (r, c) => q(`td[data-vt-r="${r}"][data-vt-c="${c}"]`);
const type = async (r, c, v) => { click(cell(r, c)); const el = cell(r, c).querySelector('input,select'); el.value = v; el.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); await tick(); };
const paste = (text, target) => { const ev = new w.Event('paste', { bubbles: true, cancelable: true }); ev.clipboardData = { getData: () => text }; (target || q('.vt-gridwrap')).dispatchEvent(ev); return ev; };

(async () => {
  assert.ok(host.textContent.includes('No escribas aquí información confidencial'), 'aviso fijo');
  assert.ok(/texto de presentación/.test(host.textContent), 'la ayuda de pantalla explica que fechas y números son texto');
  // ---- variables y filas
  pickVar(0, 'c'); assert.strictEqual(ui.state.rows.length, 31);
  pickVar(1, 't'); assert.strictEqual(ui.state.rows.length, 124);
  pickVar(2, 'e'); assert.strictEqual(ui.state.rows.length, 0); assert.ok(/1240 combinaciones/.test(q('.vt-err').textContent), q('.vt-err').textContent);
  const subset = qa('[data-vt-subset="0"]'); subset.forEach((cb, i) => { cb.checked = i < 5; });
  subset[0].dispatchEvent(new w.Event('change', { bubbles: true }));
  assert.strictEqual(ui.state.rows.length, 5 * 4 * 10, 'con un subconjunto sí cabe');
  pickVar(2, ''); const sub2 = qa('[data-vt-subset="0"]'); sub2.forEach((cb) => { cb.checked = true; }); sub2[0].dispatchEvent(new w.Event('change', { bubbles: true }));
  assert.strictEqual(ui.state.rows.length, 124);
  // ---- columnas con tipo
  addCol('p', 'content', 'text', 'Lugar'); addCol('p2', 'content', 'date', 'Fecha'); addCol('p', 'content', 'text', 'Repetida');
  assert.strictEqual(ui.state.columns.length, 3); assert.strictEqual(qa('td[data-vt-r]').length, 124 * 3);
  const img = (addCol('img', 'src', 'image', 'Foto'), ui.state.columns[3]); assert.strictEqual(img.type, 'image');
  assert.deepStrictEqual(J(Array.from(q('[data-vt-coltype="3"]').options).map((o) => o.value)), ['image'], 'la propiedad imagen solo admite columna de imagen');
  click(q('[data-vt-act="delcol"][data-vt-i="2"]')); assert.strictEqual(ui.state.columns.length, 3);
  // ---- editar celdas
  await type(0, 0, 'Chapinero'); assert.strictEqual(ui.state.rows[0].cells[ui.state.columns[0].id], 'Chapinero'); assert.strictEqual(cell(0, 0).textContent, 'Chapinero');
  await type(0, 1, '5/3/26'); assert.strictEqual(cell(0, 1).textContent, '05/03/2026', 'la fecha se muestra con el formato local');
  await type(1, 1, '31/02/2026'); assert.strictEqual(cell(1, 1).getAttribute('aria-invalid'), 'true'); assert.ok(cell(1, 1).title && /Fecha no válida/.test(cell(1, 1).title));
  assert.ok(/1 celda inválida/.test(q('.vt-status').textContent));
  click(cell(2, 0)); const rb = cell(2, 0).querySelector('[data-vt-rich]'); assert.ok(rb, 'las celdas de texto ofrecen «Formato…»'); click(rb); await tick(10);
  assert.strictEqual(ui.state.rows[2].cells[ui.state.columns[0].id], '<b>Con formato</b>'); assert.strictEqual(cell(2, 0).textContent, 'Con formato');
  // ---- no se aplica con celdas inválidas
  click(q('[data-vt-act="apply"]')); await tick();
  assert.ok(log.toasts.some(([m, k]) => /celdas inválidas/.test(m) && k === 'error') && log.applied.length === 0);
  await type(1, 1, '1/3/2026'); assert.strictEqual(cell(1, 1).getAttribute('aria-invalid'), 'false');

  // ---- pegar desde Excel: por valores de las variables y por posición
  let ev = paste('Ciudad\tTipo\tLugar\tFecha\tFoto\nCiudad 02\tInvitado\tSur\t2/4/26\tc2.jpg\nCiudad 99\tPrensa\tX\t\t\n', cell(0, 0));
  assert.ok(ev.defaultPrevented, 'el bloque de Excel no se pega como texto');
  const row = ui.state.rows.findIndex((r) => r.keys[0] === 'Ciudad 02' && r.keys[1] === 'Invitado');
  assert.strictEqual(ui.state.rows[row].cells[ui.state.columns[0].id], 'Sur'); assert.strictEqual(cell(row, 1).textContent, '02/04/2026');
  assert.ok(/Se pegaron 3 celdas; 1 fila no está en la tabla y se ignoró/.test(q('.vt-status').textContent), q('.vt-status').textContent);
  click(cell(10, 0)); const cur = q('.vt-gridwrap');
  paste('uno\ndos', cell(10, 0).querySelector('input')); assert.ok(true);
  assert.strictEqual(ui.state.rows[10].cells[ui.state.columns[0].id], 'uno'); assert.strictEqual(ui.state.rows[11].cells[ui.state.columns[0].id], 'dos', 'sin las variables, el bloque empieza en la celda elegida');
  click(cell(12, 0)); const single = paste('solo un valor', cell(12, 0).querySelector('input')); assert.ok(!single.defaultPrevented, 'un valor suelto en una celda se pega normal');

  // ---- Excel: descargar y subir (el servidor lo hace; aquí se comprueba lo que se manda y cómo se usa la respuesta)
  w.__fetchAnswer = async () => ({ ok: true, blob: async () => new w.Blob(['x']) });
  click(q('[data-vt-act="download"]')); await tick(10);
  const dl = log.fetches.find(([u]) => u.endsWith('/template')); assert.ok(dl && dl[1].method === 'POST');
  assert.deepStrictEqual(log.downloads, ['tabla-de-variantes.xlsx']);
  const sent = JSON.parse(dl[1].body);
  assert.strictEqual(sent.rows.length, 124); assert.deepStrictEqual(J(sent.variables.map((v) => v.label)), ['Ciudad', 'Tipo']); assert.ok(sent.columns.every((c) => c.id && c.name && c.type));
  assert.ok(!('field' in sent.columns[0]), 'al servidor no se le mandan ids de campos del formulario');
  const col0 = ui.state.columns[0].id;
  w.__fetchAnswer = async (u, o) => ({ ok: true, json: async () => ({ rows: ui.state.rows.map((r, i) => ({ keys: r.keys, cells: i === 3 ? { [col0]: 'Desde Excel' } : {} })), matched_rows: [3], unmatched_rows: [7], duplicated_rows: [], ignored_columns: ['Notas'], missing_rows: 123, problems: [{ row: 3, col: ui.state.columns[1].id, message: 'Fecha no válida (escribe dd/mm/aaaa)' }] }) });
  const big = new w.File([new Uint8Array(10)], 'tabla.xlsx'); const inp = q('[data-vt-upload]');
  Object.defineProperty(inp, 'files', { value: [big], configurable: true }); inp.dispatchEvent(new w.Event('change', { bubbles: true })); await tick(10);
  assert.strictEqual(ui.state.rows[3].cells[col0], 'Desde Excel');
  assert.ok(/Se leyeron 1 filas.*1 celdas con problemas.*1 filas del Excel no están en la tabla.*Notas/.test(q('.vt-status').textContent), q('.vt-status').textContent);
  const up = log.fetches.find(([u]) => u.endsWith('/parse')); assert.ok(up[1].body instanceof w.FormData);
  const bad = new w.File([new Uint8Array(10)], 'tabla.xlsm'); Object.defineProperty(inp, 'files', { value: [bad], configurable: true }); inp.dispatchEvent(new w.Event('change', { bubbles: true })); await tick(10);
  assert.ok(log.toasts.some(([m]) => /Sube un archivo \.xlsx/.test(m)), 'solo .xlsx');
  assert.strictEqual(log.fetches.filter(([u]) => u.endsWith('/parse')).length, 1, 'un .xlsm ni siquiera se manda');

  // ---- imágenes: se empareja por nombre ANTES de subir; solo lo que empareja se sube
  log.uploads = [];
  ctx.uploadImage = async (f) => { log.uploads.push(f.name); if (/prensa/.test(f.name)) throw new Error('falla'); return 'acme/' + f.name.replace(/[^a-z0-9]/gi, '') + '.jpg'; };
  const mk = (name, size) => new w.File([new Uint8Array(size || 10)], name);
  const imgs = [mk('ciudad-01_empleado.jpg'), mk('Ciudad 02 Invitado.png'), mk('ciudad-04_prensa.jpg'), mk('ciudad-05_proveedor.jpg', 8000001), mk('ciudad-01_empleado.png'), mk('logo.png'), mk('doc.pdf')];
  const imgInput = q('[data-vt-images]'); assert.ok(imgInput, 'con una columna de imagen aparece «Imágenes…»');
  const choose = async (files) => { Object.defineProperty(imgInput, 'files', { value: files, configurable: true }); imgInput.dispatchEvent(new w.Event('change', { bubbles: true })); await tick(30); };
  confirmAnswer = false; await choose(imgs);
  assert.deepStrictEqual(J(log.uploads), [], 'sin confirmar no se sube NADA');
  const pmsg = log.confirms[log.confirms.length - 1];
  assert.ok(/3<\/b> de 7 imágenes emparejaron/.test(pmsg) && /2<\/b> no emparejaron y <b>no se subirán<\/b>: logo\.png, doc\.pdf/.test(pmsg) && /1 repetidas/.test(pmsg) && /1 pesan más de 8 MB/.test(pmsg), pmsg);
  confirmAnswer = true; await choose(imgs);
  assert.deepStrictEqual(J(log.uploads.slice().sort()), ['Ciudad 02 Invitado.png', 'ciudad-01_empleado.jpg', 'ciudad-04_prensa.jpg'], 'solo se suben las que emparejaron y caben');
  assert.ok(/Se subieron 2 imágenes; fallaron 1: ciudad-04_prensa\.jpg/.test(q('.vt-status').textContent), q('.vt-status').textContent);
  assert.ok(log.toasts.some(([m, k]) => /No se pudieron subir 1 imágenes/.test(m) && k === 'error'));
  const imgCol = ui.state.columns.find((c) => c.type === 'image').id;
  assert.strictEqual(ui.state.rows[0].cells[imgCol], 'ciudad-01_empleado.jpg'); assert.strictEqual(ui.state.images['ciudad-01_empleado.jpg'], 'acme/ciudad01empleadojpg.jpg');
  await choose(imgs); assert.strictEqual(log.uploads.filter((n) => n === 'ciudad-01_empleado.jpg').length, 1, 'la misma imagen no se sube dos veces');
  assert.strictEqual(log.uploads.filter((n) => n === 'ciudad-04_prensa.jpg').length, 2, 'la que falló se reintenta');
  const built = w.VariantTable.build(ui.spec(), design.fields);
  assert.deepStrictEqual(J(built.variants.img.src.items.map((i) => i.value)).sort(), ['acme/Ciudad02Invitadopng.jpg', 'acme/ciudad01empleadojpg.jpg'], 'la tabla usa las rutas ya subidas');
  assert.strictEqual(built.summary.rowsWithoutImage, 122);
  const none = [mk('x.png'), mk('y.jpg')]; log.uploads = []; await choose(none);
  assert.deepStrictEqual(J(log.uploads), []); assert.ok(log.toasts.some(([m]) => /Ninguna imagen emparejó/.test(m)));
  await choose(Array.from({ length: 201 }, (_, i) => mk('f' + i + '.png'))); assert.ok(log.toasts.some(([m]) => /hasta 200 imágenes/.test(m)));
  ui.state.rows.forEach((r) => { delete r.cells[imgCol]; }); ui.state.images = {}; ui.paint();

  // ---- vista previa y aplicar (reemplaza) y deshacer
  ui.state.rows.forEach((r) => { Object.keys(r.cells).forEach((k) => { if (k !== col0) delete r.cells[k]; }); });   // sin la fecha inválida del Excel
  ui.paint();
  click(q('[data-vt-act="apply"]')); await tick(10);
  const msg = log.confirms[log.confirms.length - 1];
  assert.ok(/Se crearán \d+ variantes en 1 elemento\. Se reemplazarán 0 variantes existentes\. 124 filas sin imagen, 2 valores/.test(msg) && /valores que no están en la lista/.test(msg), msg);
  assert.strictEqual(log.applied.length, 1); assert.ok(design.fields.p.variants.content.items.length >= 4);
  assert.ok(!q('[data-vt-act="undo"]').disabled, 'se puede deshacer');
  click(q('[data-vt-act="undo"]')); await tick();
  assert.ok(!design.fields.p.variants, 'deshacer devuelve el diseño anterior');
  confirmAnswer = false; click(q('[data-vt-act="apply"]')); await tick(10); assert.strictEqual(log.applied.length, 1, 'sin confirmar no se aplica nada'); confirmAnswer = true;

  // ---- plantillas de tabla (.json): se guardan las columnas y se reusan en otro formulario
  const readBlob = (blob) => new Promise((res) => { const r = new w.FileReader(); r.onload = () => res(String(r.result)); r.readAsText(blob); });
  log.blobs.length = 0; click(q('[data-vt-act="savetpl"]')); await tick(10);
  const tplText = await readBlob(log.blobs[log.blobs.length - 1]);
  const parsed = w.VariantTable.parseTemplate(tplText);
  assert.ok(!parsed.error, parsed.error); assert.strictEqual(parsed.columns.length, 3); assert.deepStrictEqual(J(parsed.variables), ['Ciudad', 'Tipo']);
  assert.ok(!/"field"|"late"/.test(tplText) && /"idElemento": "p"/.test(tplText), 'la plantilla lleva el id del elemento como pista, pero no los ids de columnas ni campos de las variables');
  assert.ok(log.downloads.includes('plantilla-de-tabla.json'));
  const host2 = w.document.createElement('div'); w.document.body.appendChild(host2);
  const ui2 = w.VariantTableUI.mount(host2, ctx);
  const upTpl = async (h, text, name) => { const inp = h.querySelector('[data-vt-tpl]'); Object.defineProperty(inp, 'files', { value: [new w.File([text], name || 'plantilla.json')], configurable: true }); inp.dispatchEvent(new w.Event('change', { bubbles: true })); await tick(40); };
  await upTpl(host2, tplText);
  assert.deepStrictEqual(J(ui2.state.columns.map((c) => [c.name, c.field, c.prop, c.type])), [['Lugar', 'p', 'content', 'text'], ['Fecha', 'p2', 'content', 'date'], ['Foto', 'img', 'src', 'image']], 'cada columna se asigna al elemento con el mismo nombre');
  assert.deepStrictEqual(J(ui2.state.varFields), ['c', 't']); assert.strictEqual(ui2.state.rows.length, 124);
  assert.ok(/Se cargaron 3 columnas\./.test(host2.querySelector('.vt-status').textContent));
  const other = tplText.replace('"Texto informativo"', '"Un elemento que no existe aquí"').replace('"idElemento": "p"', '"idElemento": ""');      // plantilla de OTRO formulario: sin id que valga ni nombre que coincida
  const nconf = log.confirms.length;
  confirmAnswer = false; await upTpl(host2, other); assert.strictEqual(log.confirms.length, nconf + 1, 'con columnas ya puestas pide confirmación'); assert.strictEqual(ui2.state.columns[0].field, 'p', 'sin confirmar no cambia nada');
  confirmAnswer = true; await upTpl(host2, other);
  assert.strictEqual(ui2.state.columns[0].field, ''); assert.ok(/1 sin elemento/.test(host2.querySelector('.vt-status').textContent));
  host2.querySelector('[data-vt-act="apply"]').click(); await tick(10);
  assert.ok(log.toasts.some(([m]) => /«Lugar» no tiene elemento/.test(m)), 'una columna sin elemento no se aplica');
  const f0 = host2.querySelector('[data-vt-colfield="0"]'); f0.value = 'p'; f0.dispatchEvent(new w.Event('change', { bubbles: true })); assert.strictEqual(ui2.state.columns[0].field, 'p'); assert.strictEqual(ui2.state.columns[0].prop, 'content');
  for (const [text, name] of [['{"no es": "una plantilla"}', 'x.json'], ['no es json', 'x.json'], ['x'.repeat(100001), 'x.json'], [tplText, 'x.txt'], [tplText, 'x.json.exe']]) {
    const before = log.toasts.length; await upTpl(host2, text, name);
    assert.ok(log.toasts.length > before && log.toasts[log.toasts.length - 1][1] === 'error', name + ' -> ' + (log.toasts[log.toasts.length - 1] || [])[0]);
  }
  assert.strictEqual(ui2.state.columns.length, 3, 'lo hostil no cambia nada');
  ui2.destroy();

  // ---- hojas (P12): una variante no puede usar un campo de una hoja posterior
  pickVar(0, 'late'); pickVar(1, ''); addCol('p', 'content', 'text', 'Otro');
  assert.ok(/«Tardío» está en una hoja posterior a «Texto informativo»/.test(q('.vt-err').textContent));
  click(q('[data-vt-act="apply"]')); await tick(10); assert.ok(log.toasts.some(([m]) => /hoja posterior/.test(m)));

  // ---- nombres de elementos (P11b): se distinguen en las listas, el nombre interno manda y la tabla va por id
  const d3 = { fields: {
    c: { id: 'c', type: 'select', label: 'Ciudad', options: ['Bogotá', 'Cali'] },
    p1: { id: 'p1', type: 'paragraph', content: 'Ciudad: Bogotá. Lugar evento norte' }, p2: { id: 'p2', type: 'paragraph', content: 'Segundo texto del evento' },
    i1: { id: 'i1', type: 'image', src: '' }, i2: { id: 'i2', type: 'image', src: '', alt: 'Logo' } }, rows: [['c'], ['p1'], ['p2'], ['i1'], ['i2']].map((items) => ({ items })) };
  const nm = () => w.ElementNames.build(d3, { typeLabel: (t) => ({ select: 'Lista', paragraph: 'Texto informativo', image: 'Imagen' }[t]), plain: (h) => w.RichText.toPlain(h) });
  const props3 = (id) => (d3.fields[id].type === 'image' ? ['src'] : d3.fields[id].type === 'paragraph' ? ['content'] : ['display_label', 'help']);
  const ctx3 = { url: '/x', design: () => d3, fields: () => Object.keys(d3.fields).filter((id) => props3(id).length).map((id) => ({ id, label: nm()[id].full })), optionsOf: (id) => d3.fields[id].options || null, fieldLabel: (id) => (d3.fields[id] ? nm()[id].full : '?'), shortName: (id) => (d3.fields[id] ? nm()[id].short : ''), exists: (id) => !!d3.fields[id], propsOf: props3, propLabel: (p) => ({ content: 'Texto', src: 'Imagen' }[p]), assetUrl: (p) => p, toast: ctx.toast, confirm: ctx.confirm, richEdit: ctx.richEdit, apply: ctx.apply };
  const host3 = w.document.createElement('div'); w.document.body.appendChild(host3);
  const ui3 = w.VariantTableUI.mount(host3, ctx3);
  const sel3 = host3.querySelector('[data-vt-var="0"]'); sel3.value = 'c'; sel3.dispatchEvent(new w.Event('change', { bubbles: true }));
  const add3 = (field) => { host3.querySelector('[data-vt-act="addcol"]').click(); const i = ui3.state.columns.length - 1; const f = host3.querySelector(`[data-vt-colfield="${i}"]`); f.value = field; f.dispatchEvent(new w.Event('change', { bubbles: true })); return ui3.state.columns[i]; };
  add3('p1');
  const optLabels = Array.from(host3.querySelector('[data-vt-colfield="0"]').options).map((o) => o.textContent);
  assert.ok(optLabels.includes('Texto informativo 1 — «Ciudad: Bogotá. Lugar evento norte»') && optLabels.includes('Texto informativo 2 — «Segundo texto del evento»') && optLabels.includes('Imagen 2 — «Logo»'), optLabels.join(' | '));
  assert.strictEqual(new Set(optLabels).size, optLabels.length, 'ningún nombre del desplegable se repite');
  assert.strictEqual(ui3.state.columns[0].name, 'Texto informativo 1', 'la columna nace con el nombre corto del elemento');
  const c2 = add3('p2'); assert.strictEqual(c2.name, 'Texto informativo 2');
  c2.field = 'p1'; ui3.paint(); const c3 = add3('p1'); assert.notStrictEqual(VT_norm(c3.name), VT_norm(ui3.state.columns[0].name), 'dos columnas no pueden llamarse igual');
  function VT_norm(x) { return String(x).toLowerCase(); }
  // nombre interno: manda en las listas; renombrar NO rompe la columna (va por id)
  ui3.state.columns.splice(2, 1); c2.field = 'p2'; ui3.paint();
  const colId = ui3.state.columns[0].id;
  d3.fields.p1.internal_name = 'Texto de Bogotá'; ui3.paint();
  assert.ok(Array.from(host3.querySelector('[data-vt-colfield="0"]').options).some((o) => o.textContent === 'Texto de Bogotá' && o.selected), 'la lista usa el nombre interno y la columna sigue en su elemento');
  assert.strictEqual(ui3.state.columns[0].id, colId); assert.strictEqual(ui3.state.columns[0].field, 'p1'); assert.strictEqual(ui3.state.columns[0].name, 'Texto informativo 1', 'el nombre de la columna no cambia solo');
  d3.rows.reverse(); ui3.paint(); assert.strictEqual(ui3.state.columns[0].field, 'p1', 'reordenar no cambia a qué elemento apunta');
  // plantilla .json: por id aunque lo hayan renombrado; si el id ya no existe se avisa
  log.blobs.length = 0; host3.querySelector('[data-vt-act="savetpl"]').click(); await tick(10);
  const tpl3 = await readBlob(log.blobs[log.blobs.length - 1]);
  assert.ok(/"idElemento": "p1"/.test(tpl3));
  d3.fields.p1.internal_name = 'Otro nombre completamente distinto'; d3.fields.p2.internal_name = 'Y otro';
  ui3.state.columns.length = 0; confirmAnswer = true;
  const inp3 = host3.querySelector('[data-vt-tpl]'); Object.defineProperty(inp3, 'files', { value: [new w.File([tpl3], 'p.json')], configurable: true }); inp3.dispatchEvent(new w.Event('change', { bubbles: true })); await tick(40);
  assert.deepStrictEqual(J(ui3.state.columns.map((c) => c.field)), ['p1', 'p2'], 'la plantilla encuentra el elemento por su id aunque tenga otro nombre');
  delete d3.fields.p2; d3.rows = d3.rows.filter((r) => r.items[0] !== 'p2'); ui3.paint();
  assert.ok(/El elemento de esta columna ya no existe/.test(host3.textContent) && /sin elemento/.test(host3.querySelector('table').textContent), 'un elemento borrado se avisa');
  host3.querySelector('[data-vt-act="apply"]').click(); await tick(10);
  assert.ok(log.toasts.some(([m]) => /no tiene elemento/.test(m)), 'y no se puede aplicar hasta reasignarlo');
  ui3.destroy();

  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  console.log(`  pantalla con 124 filas × 3 columnas en jsdom: ${ms.toFixed(0)} ms en total (incluye las pruebas)`);
  ui.destroy();
  console.log('variant_table_ui_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
