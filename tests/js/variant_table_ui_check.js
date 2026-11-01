// P11: pantalla de la tabla de variantes (static/js/variant-table-ui.js) con jsdom y un contexto de diseñador de mentira.
// Correr: npm ci && node tests/js/variant_table_ui_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const dom = new JSDOM('<!doctype html><body><div id="host"></div></body>', { runScripts: 'outside-only', url: 'https://example.test/' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/variant-table.js', 'static/js/variant-table-ui.js'].forEach((f) => w.eval(fs.readFileSync(path.join(root, f), 'utf8')));
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
w.URL.createObjectURL = () => 'blob:x'; w.URL.revokeObjectURL = () => {};
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

  // ---- hojas (P12): una variante no puede usar un campo de una hoja posterior
  pickVar(0, 'late'); pickVar(1, ''); addCol('p', 'content', 'text', 'Otro');
  assert.ok(/«Tardío» está en una hoja posterior a «Texto informativo»/.test(q('.vt-err').textContent));
  click(q('[data-vt-act="apply"]')); await tick(10); assert.ok(log.toasts.some(([m]) => /hoja posterior/.test(m)));

  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  console.log(`  pantalla con 124 filas × 3 columnas en jsdom: ${ms.toFixed(0)} ms en total (incluye las pruebas)`);
  ui.destroy();
  console.log('variant_table_ui_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
