// P9: el editor de condiciones en árbol y de variantes (bloque «condiciones en árbol y variantes» de templates/kiosk_formulario_editor.html), con DOM de jsdom
// y las funciones del diseñador sustituidas por dobles. Correr: npm ci && node tests/js/editor_variants_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const tpl = fs.readFileSync(path.join(root, 'templates/kiosk_formulario_editor.html'), 'utf8').split('\r\n').join('\n');
const block = tpl.slice(tpl.indexOf('// ---------------------------------------------------------------- condiciones en árbol y variantes (P9)'), tpl.indexOf('// ---------------------------------------------------------------- paleta'));
assert.ok(block.length > 3000, 'bloque encontrado');

const dom = new JSDOM('<!doctype html><body><div id="propsBox"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-sync.js', 'static/js/cond-tree.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(root, f), 'utf8')));
w.eval(`
  var toasts = [], dirtyCount = 0, canvasCount = 0, mounts = [];
  const $ = (id) => document.getElementById(id);
  const esc = RichText.esc;
  const STATIC = ['heading', 'paragraph', 'image'], NOCOND = ['payment', 'companions'];
  const TYPES = { text_short: ['Texto corto'], select: ['Lista'], checkbox: ['Casilla'], paragraph: ['Texto'], image: ['Imagen'], heading: ['Título'], payment: ['Pago'], companions: ['Acompañantes'] };
  const EV = 1, assetUrl = (p) => '/a/' + p;
  let eventFields = [{ key: 'opcional_1', label: 'Ciudad', type: 'select', options: ['Bogotá', 'Apartadó', 'Necoclí'] }];
  let design = { fields: {
    c: { id: 'c', type: 'select', label: 'Ciudad', options: ['Bogotá', 'Apartadó', 'Necoclí'] },
    k: { id: 'k', type: 'text_short', label: 'Ciudad (texto)', key: 'opcional_1' },
    t: { id: 't', type: 'select', label: 'Tipo', options: ['Empleado', 'Invitado'] },
    p: { id: 'p', type: 'paragraph', content: 'Base', variants: null },
    n: { id: 'n', type: 'text_short', label: 'Nombre', help: 'ayuda' },
  } };
  const showToast = (m, k) => toasts.push([m, k]), showConfirm = async () => true;
  const markDirty = () => { dirtyCount++; }, renderCanvas = () => { canvasCount++; };
  let box = document.getElementById('propsBox'), current = null;
  const mountRt = (h, o) => { mounts.push([h.dataset.vrt, o]); return { destroy() {} }; };
  function renderProps() { condOwners = {}; box.innerHTML = variantsHtml(current) + '<div id="vis">' + (() => { const id = regOwner(current.id, () => current.show_if, (n) => { current.show_if = CondTree.compact(n); markDirty(); }); return current.show_if ? condEditorHtml(id) + '<button data-co="' + id + '" data-cx="clearroot">x</button>' : '<button data-co="' + id + '" data-cx="startroot">y</button>'; })() + '</div>'; bindVariants(box, current); }
  ${block}
  window.T = { setCurrent: (id) => { current = design.fields[id]; renderProps(); }, f: (id) => design.fields[id], design: () => design, toasts, mounts, dirty: () => dirtyCount, renderProps, setEventFields: (e) => { eventFields = e; } };
`);
const T = w.T, box = w.document.getElementById('propsBox');
const click = (el) => el.dispatchEvent(new w.Event('click', { bubbles: true }));
const change = (el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', { bubbles: true })); };
const q = (sel) => box.querySelector(sel), qa = (sel) => Array.from(box.querySelectorAll(sel));
const act = (a, extra) => q(`[data-vact="${a}"]${extra || ''}`);

// ---- aviso de confidencialidad siempre visible
T.setCurrent('p');
assert.ok(box.textContent.includes('No escribas aquí información confidencial: todo el contenido de las variantes es visible para quien abra el formulario, aunque no se le muestre.'));
// ---- activar variantes del texto: el texto base pasa a ser el valor por defecto
click(act('enable', '[data-vp="content"]'));
assert.deepStrictEqual(JSON.parse(JSON.stringify(T.f('p').variants)), { content: { items: [], default: 'Base' } });
click(act('add', '[data-vp="content"]'));
let v = T.f('p').variants.content;
assert.strictEqual(v.items.length, 1);
assert.deepStrictEqual(JSON.parse(JSON.stringify(v.items[0].when)), { match: 'all', rules: [{ field: 'c', op: 'equals', value: '' }] }, 'la variante nace con una regla sobre el primer campo con opciones');
// ---- la regla: el valor SIEMPRE sale de la lista (propia o de Parámetros)
let sel = q('[data-cx="valsel"]');
assert.deepStrictEqual(Array.from(sel.options).map((o) => o.textContent), ['', 'Bogotá', 'Apartadó', 'Necoclí']);
change(sel, 'Bogotá');
assert.strictEqual(v.items[0].when.rules[0].value, 'Bogotá');
change(q('[data-cx="field"]'), 'k');                                   // campo de texto enlazado a Parámetros: también lista
sel = q('[data-cx="valsel"]');
assert.ok(sel && Array.from(sel.options).length === 4, 'las opciones del campo del evento aparecen aunque el campo sea de texto');
change(q('[data-cx="op"]'), 'in');
assert.strictEqual(qa('[data-cx="valin"]').length, 3, 'es alguno de → casillas');
qa('[data-cx="valin"]')[0].checked = true; qa('[data-cx="valin"]')[2].checked = true; change(qa('[data-cx="valin"]')[0]);
assert.deepStrictEqual(Array.from(v.items[0].when.rules[0].value), ['Bogotá', 'Necoclí']);
// ---- grupos anidados hasta 3 niveles
click(q('[data-cx="addleaf"]'));                                       // segunda regla en el grupo raíz
click(q('[data-cx="addgroup"]'));                                      // grupo (nivel 2)
let when = v.items[0].when;
assert.strictEqual(when.rules.length, 3); assert.ok(when.rules[2].rules);
change(qa('[data-cx="match"]')[1], 'any');
assert.strictEqual(T.f('p').variants.content.items[0].when.rules[2].match, 'any');
const addGroups = () => qa('[data-cx="addgroup"]');
click(addGroups()[0]);                                                 // grupo dentro del grupo (nivel 3)
assert.strictEqual(w.CondTree.depth(T.f('p').variants.content.items[0].when), 3);
assert.strictEqual(addGroups().length, 2, 'en el nivel 3 ya no se ofrece otro grupo');
// ---- quitar una hoja, un grupo; reordenar; duplicados de nombre
click(qa('[data-cx="delnode"]').find((b) => b.textContent === 'Quitar grupo'));
assert.ok(w.CondTree.depth(T.f('p').variants.content.items[0].when) < 3);
click(act('add', '[data-vp="content"]'));
change(q('[data-vname="content:1"]') || { value: '' });
const nm = q('[data-vname="content:1"]'); nm.value = 'Segunda'; nm.dispatchEvent(new w.Event('input', { bubbles: true }));
assert.strictEqual(T.f('p').variants.content.items[1].name, 'Segunda');
click(act('up', '[data-vi="1"]'));
assert.strictEqual(T.f('p').variants.content.items[0].name, 'Segunda', '↑ la sube');
click(act('del', '[data-vi="0"]'));
assert.strictEqual(T.f('p').variants.content.items.length, 1);
// ---- editores de texto con formato: uno por variante y uno para el valor por defecto
assert.ok(T.mounts.some(([k]) => k === 'content:0') && T.mounts.some(([k]) => k === 'content:def'));
// ---- quitar todas las variantes: queda el valor por defecto como texto
click(act('disable', '[data-vp="content"]'));
await_(() => { assert.ok(!T.f('p').variants); assert.strictEqual(T.f('p').content, 'Base'); });

function await_(fn) { return new Promise((r) => setTimeout(r, 0)).then(fn); }

(async () => {
  await await_(() => {});
  // ---- campo de entrada: nombre, ayuda y texto de ejemplo; placeholder es texto plano
  T.setCurrent('n');
  ['display_label', 'help', 'placeholder'].forEach((p) => assert.ok(act('enable', `[data-vp="${p}"]`), p));
  click(act('enable', '[data-vp="placeholder"]'));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(T.f('n').variants.placeholder)), { items: [], default: '' }, 'sin valor por defecto en las propiedades que caen al valor del campo');
  click(act('add', '[data-vp="placeholder"]'));
  const ph = q('[data-vtxt="placeholder:0"]'); ph.value = 'ej. Ana'; ph.dispatchEvent(new w.Event('input', { bubbles: true }));
  assert.strictEqual(T.f('n').variants.placeholder.items[0].value, 'ej. Ana');
  // ---- visibilidad con árbol, y limpieza de lo que apunta a un campo borrado
  T.setCurrent('n');
  click(q('[data-cx="startroot"]'));
  assert.strictEqual(T.f('n').show_if.field, 'c');
  click(q('#vis [data-cx="addleaf"]'));
  assert.strictEqual(T.f('n').show_if.rules.length, 2, 'dos reglas → grupo');
  click(q('#vis [data-cx="clearroot"]'));
  assert.strictEqual(T.f('n').show_if, null);
  // ---- imagen: la variante lleva su archivo y un valor por defecto
  T.design().fields.i = { id: 'i', type: 'image', src: 'acme/a.png' };
  T.setCurrent('i');
  click(act('enable', '[data-vp="src"]'));
  assert.strictEqual(T.f('i').variants.src.default, 'acme/a.png');
  click(act('add', '[data-vp="src"]'));
  assert.ok(q('[data-vimg="src:0"]') && q('[data-vimg="src:def"]'));
  assert.ok(q('img[src="/a/acme/a.png"]'), 'miniatura del valor por defecto');
  console.log('editor_variants_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
