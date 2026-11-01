// P9/P10: editor de condiciones en árbol y de variantes (bloque «condiciones en árbol y variantes» de templates/kiosk_formulario_editor.html) con DOM de jsdom
// y las funciones del diseñador sustituidas por dobles: reglas anidadas, plegado, grupos, buscador, duplicar, «una por cada opción» y montaje diferido de los editores.
// Correr: npm ci && node tests/js/editor_variants_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const tpl = fs.readFileSync(path.join(root, 'templates/kiosk_formulario_editor.html'), 'utf8').split('\r\n').join('\n');
const block = tpl.slice(tpl.indexOf('// ---------------------------------------------------------------- condiciones en árbol y variantes (P9)'), tpl.indexOf('// ---------------------------------------------------------------- paleta'));
assert.ok(block.length > 3000, 'bloque encontrado');

const dom = new JSDOM('<!doctype html><body><div id="propsBox"></div><div id="sheetsBar"></div><div id="sheetsPanel"></div><div id="canvas"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-sync.js', 'static/js/cond-tree.js', 'static/js/element-names.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(root, f), 'utf8')));
const CITIES = Array.from({ length: 31 }, (_, i) => `Ciudad ${String(i + 1).padStart(2, '0')}`);
w.eval(`
  var toasts = [], confirms = [], dirtyCount = 0, canvasCount = 0, confirmAnswer = true;
  const $ = (id) => document.getElementById(id);
  const esc = RichText.esc;
  const STATIC = ['heading', 'paragraph', 'image'], NOCOND = ['payment', 'companions'];
  const TYPES = { text_short: ['Texto corto'], select: ['Lista'], checkbox: ['Casilla'], paragraph: ['Texto'], image: ['Imagen'], heading: ['Título'], payment: ['Pago'], companions: ['Acompañantes'] };
  const EV = 1, assetUrl = (p) => '/a/' + p;
  let eventFields = [{ key: 'opcional_1', label: 'Ciudad', type: 'select', options: ['Bogotá', 'Apartadó', 'Necoclí'] }];
  let design = { fields: {
    c: { id: 'c', type: 'select', label: 'Ciudad', options: ${JSON.stringify(CITIES)} },
    k: { id: 'k', type: 'text_short', label: 'Ciudad (texto)', key: 'opcional_1' },
    t: { id: 't', type: 'select', label: 'Tipo', options: ['Empleado', 'Invitado'] },
    p: { id: 'p', type: 'paragraph', content: 'Base', variants: null },
    n: { id: 'n', type: 'text_short', label: 'Nombre', help: 'ayuda' },
  }, rows: [] };
  const showToast = (m, k) => toasts.push([m, k]), showConfirm = async (m) => { confirms.push(m); return confirmAnswer; };
  let namesCache = null;
  const markDirty = () => { dirtyCount++; namesCache = null; }, renderCanvas = () => { canvasCount++; };
  let box = document.getElementById('propsBox'), selected = null, rtMounts = [];
  const mountRt = (h, o) => { const m = RichText.mount(h, o); rtMounts.push(m); return m; };
  function renderProps() { Object.keys(condOwners).forEach((k) => { if (!condOwners[k].keep) delete condOwners[k]; }); const f = design.fields[selected]; box.innerHTML = variantsHtml(f) + '<div id="vis">' + (() => { const id = regOwner(f.id, () => f.show_if, (n) => { f.show_if = CondTree.compact(n); markDirty(); }, { key: 'show:' + f.id }); return f.show_if ? condEditorHtml(id) + '<button data-co="' + id + '" data-cx="clearroot">x</button>' : '<button data-co="' + id + '" data-cx="startroot">y</button>'; })() + '</div>'; bindVariants(box, f); }
  ${block}
  window.T = { setCurrent: (id) => { selected = id; namesCache = null; renderProps(); }, f: (id) => design.fields[id], design: () => design, toasts, confirms, dirty: () => dirtyCount, answer: (v) => { confirmAnswer = v; }, ensureUids, foldItem };
`);
const T = w.T, box = w.document.getElementById('propsBox'), doc = w.document;
const tick = () => new Promise((r) => setTimeout(r, 0));
const click = async (el) => { el.dispatchEvent(new w.Event('click', { bubbles: true })); await tick(); };
const change = (el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', { bubbles: true })); };
const typeIn = (el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', { bubbles: true })); };
const q = (sel) => box.querySelector(sel), qa = (sel) => Array.from(box.querySelectorAll(sel));
const act = (a, extra) => q(`[data-vact="${a}"]${extra || ''}`);
const J = (x) => JSON.parse(JSON.stringify(x));
const editors = () => qa('.rt-ed').length;

(async () => {
  // ---- aviso fijo y activación: el texto base pasa a ser el valor por defecto
  T.setCurrent('p');
  assert.ok(box.textContent.includes('No escribas aquí información confidencial: todo el contenido de las variantes es visible para quien abra el formulario, aunque no se le muestre.'));
  await click(act('enable', '[data-vp="content"]'));
  assert.deepStrictEqual(J(T.f('p').variants), { content: { items: [], default: 'Base' } });
  await click(act('add', '[data-vp="content"]'));
  let v = T.f('p').variants.content;
  assert.deepStrictEqual(J(v.items[0].when), { match: 'all', rules: [{ field: 'c', op: 'equals', value: '' }] }, 'nace con una regla sobre el primer campo con opciones');
  assert.ok(v.items[0]._uid, 'cada variante lleva un id solo del editor');

  // ---- la regla: el valor SIEMPRE sale de una lista (propia o de Parámetros)
  let sel = q('[data-cx="valsel"]');
  assert.strictEqual(sel.options.length, 32);
  change(sel, 'Ciudad 03'); assert.strictEqual(v.items[0].when.rules[0].value, 'Ciudad 03');
  change(q('[data-cx="field"]'), 'k');
  assert.deepStrictEqual(J(Array.from(q('[data-cx="valsel"]').options).map((o) => o.textContent)), ['', 'Bogotá', 'Apartadó', 'Necoclí'], 'campo de texto enlazado a Parámetros: sus opciones');
  change(q('[data-cx="op"]'), 'in');
  qa('[data-cx="valin"]')[0].checked = true; qa('[data-cx="valin"]')[2].checked = true; change(qa('[data-cx="valin"]')[0]);
  assert.deepStrictEqual(J(v.items[0].when.rules[0].value), ['Bogotá', 'Necoclí']);
  // ---- grupos Y/O anidados hasta 3 niveles
  await click(q('[data-cx="addleaf"]')); await click(q('[data-cx="addgroup"]'));
  assert.strictEqual(v.items[0].when.rules.length, 3);
  await click(qa('[data-cx="addgroup"]')[0]);                                 // el del grupo interno (nivel 3)
  assert.strictEqual(w.CondTree.depth(v.items[0].when), 3); assert.strictEqual(qa('[data-cx="addgroup"]').length, 2, 'en el nivel 3 no se ofrece otro grupo');

  // ---- P10: nombrar un grupo de reglas y plegar reglas y grupos
  typeIn(qa('[data-cx="gname"]')[0], 'Costa');
  assert.ok(JSON.stringify(v.items[0].when).includes('Costa'));
  await click(qa('[data-cx="fold"]').find((b) => b.getAttribute('aria-label').includes('la regla')));
  assert.ok(qa('[data-leaf]').some((l) => l.querySelector('.hint') && l.querySelector('[data-cx="delnode"]') && !l.querySelector('select')), 'una regla plegada es una sola línea');
  const inner = qa('[data-cx="fold"]').find((b) => b.getAttribute('aria-label').includes('grupo') && b.dataset.cp === '');      // el grupo raíz (el que tiene nombre)
  await click(inner);
  assert.ok(/Costa · \d+ reglas?:/.test(box.textContent), 'el grupo plegado muestra su nombre y cuántas reglas tiene');

  // ---- resumen de una línea de la variante plegada y duplicar
  await click(act('toggle'));
  const head = q('.cvs').textContent;
  assert.ok(/^1\. /.test(head) && /→/.test(head), head);
  assert.strictEqual(q('.cvs').title, head, 'el resumen completo está en el atributo title (el panel es angosto y lo corta)');
  assert.strictEqual(q('.cvb').innerHTML, '', 'plegada: no hay cuerpo ni editores');
  await click(act('dup'));
  assert.strictEqual(T.f('p').variants.content.items.length, 2);
  assert.notStrictEqual(T.f('p').variants.content.items[0]._uid, T.f('p').variants.content.items[1]._uid);
  await click(act('del', '[data-vu="' + T.f('p').variants.content.items[1]._uid + '"]'));
  assert.strictEqual(T.f('p').variants.content.items.length, 1);

  // ---- «una variante por cada opción de la lista» con 31 ciudades
  T.f('p').variants.content.items = [];
  T.setCurrent('p');
  // ya cubiertas: una «es igual a», una dentro de un grupo O y una «es alguno de»: no se vuelven a crear
  const cov = (value, op) => ({ when: { match: 'all', rules: [{ field: 'c', op: op || 'equals', value }] }, value: 'ya', _uid: 'pre' + String(value).length + Math.random() });
  T.f('p').variants.content.items = [cov('Ciudad 05'), { when: { match: 'any', rules: [{ field: 'c', op: 'equals', value: 'ciudad 06' }, { field: 't', op: 'equals', value: 'Empleado' }] }, value: 'ya', _uid: 'preO' }, cov(['Ciudad 07', 'Ciudad 08'], 'in'),
    { when: { match: 'all', rules: [{ field: 'c', op: 'equals', value: 'Ciudad 09' }, { field: 't', op: 'equals', value: 'Empleado' }] }, value: 'ya', _uid: 'preY' }];
  T.setCurrent('p');
  q('[data-vpo="content"]').value = 'c';
  T.answer(true); await click(act('peropt'));
  assert.ok(/Se crearán 27 variantes/.test(T.confirms[T.confirms.length - 1]), T.confirms[T.confirms.length - 1]);       // 31 − (05, 06, 07 y 08 ya cubiertas); la 09 solo existe junto con otra condición (Y), así que SÍ se crea
  const made = T.f('p').variants.content.items.slice(4).map((i) => i.name);
  assert.strictEqual(made.length, 27); assert.ok(['Ciudad 05', 'Ciudad 06', 'Ciudad 07', 'Ciudad 08'].every((n) => !made.includes(n)) && made.includes('Ciudad 09'), made.join());
  T.f('p').variants.content.items = [];
  T.setCurrent('p');
  q('[data-vpo="content"]').value = 'c';
  T.answer(false); await click(act('peropt')); assert.strictEqual(T.f('p').variants.content.items.length, 0, 'sin confirmar no crea nada');
  assert.ok(/Se crearán 31 variantes, una por cada opción de «Ciudad»/.test(T.confirms[T.confirms.length - 1]), T.confirms[T.confirms.length - 1]);
  T.answer(true); await click(act('peropt'));
  v = T.f('p').variants.content;
  assert.strictEqual(v.items.length, 31);
  assert.deepStrictEqual(J(v.items[4].when), { match: 'all', rules: [{ field: 'c', op: 'equals', value: 'Ciudad 05' }] }); assert.strictEqual(v.items[4].name, 'Ciudad 05');
  assert.strictEqual(v.items[4].value, 'Base', 'el valor por defecto se copia para editarlo');
  assert.strictEqual(qa('.cv').length, 31); assert.strictEqual(qa('.cvb').filter((b) => b.innerHTML).length, 0, 'las 31 llegan plegadas');
  assert.strictEqual(editors(), 1, 'solo el editor del valor por defecto: no se monta uno por variante');
  T.toasts.length = 0; await click(act('peropt')); assert.ok(T.toasts.some(([m]) => /Ya hay una variante para cada opción/.test(m)), 'no repite las que ya existen');
  assert.strictEqual(T.f('p').variants.content.items.length, 31);

  // ---- desplegar una monta SU editor; plegarla lo desmonta
  await click(act('toggle', '[data-vu="' + v.items[2]._uid + '"]'));
  assert.strictEqual(editors(), 2); assert.ok(q('.cvb[data-vu="' + v.items[2]._uid + '"] .rt-ed'));
  await click(act('toggle', '[data-vu="' + v.items[2]._uid + '"]'));
  assert.strictEqual(editors(), 1);

  // ---- buscador
  const search = q('[data-vsearch]');
  typeIn(search, 'ciudad 07');
  assert.deepStrictEqual(J(qa('.cv').filter((c) => c.style.display !== 'none').map((c) => c.dataset.uid)), [v.items[6]._uid], 'solo la que coincide');
  typeIn(search, ''); assert.strictEqual(qa('.cv').filter((c) => c.style.display !== 'none').length, 31);

  // ---- grupos nombrados: se plieguen como grupo o por separado
  await click(act('toggle', '[data-vu="' + v.items[0]._uid + '"]'));
  await click(act('toggle', '[data-vu="' + v.items[1]._uid + '"]'));
  change(q('[data-vgroup="content:' + v.items[0]._uid + '"]'), 'Costa'); await tick();
  change(q('[data-vgroup="content:' + v.items[1]._uid + '"]'), 'Costa'); await tick();
  assert.strictEqual(T.f('p').variants.content.items[0].group, 'Costa'); assert.strictEqual(T.f('p').variants.content.items[1].group, 'Costa');
  assert.ok(q('[data-vact="gtoggle"]') && /Costa/.test(box.textContent), 'una banda con el nombre del grupo');
  assert.strictEqual(qa('.cv').length, 31);
  await click(q('[data-vact="gtoggle"]')); assert.strictEqual(qa('.cv').length, 29, 'el grupo plegado oculta sus variantes');
  await click(q('[data-vact="gtoggle"]')); assert.strictEqual(qa('.cv').length, 31);
  change(q('[data-vgname^="content:"]'), 'Caribe'); await tick();
  assert.strictEqual(T.f('p').variants.content.items[1].group, 'Caribe', 'renombrar el grupo cambia todas');
  assert.deepStrictEqual(J(v.items.slice(0, 3).map((i) => i.name)), ['Ciudad 01', 'Ciudad 02', 'Ciudad 03'], 'agrupar no cambia el orden ni cuál variante se muestra');

  // ---- plegar todas / desplegar todas
  T.answer(true);
  await click(act('unfoldall')); assert.ok(/Desplegar 31 variantes puede tardar/.test(T.confirms[T.confirms.length - 1]));
  assert.strictEqual(qa('.cvb').filter((b) => b.innerHTML).length, 31); assert.strictEqual(editors(), 32);
  await click(act('foldall')); assert.strictEqual(qa('.cvb').filter((b) => b.innerHTML).length, 0); assert.strictEqual(editors(), 1);

  // ---- el editor guarda lo que escribe la persona en cada variante, sin repintar todo
  await click(act('toggle', '[data-vu="' + v.items[9]._uid + '"]'));
  const ed = q('.cvb[data-vu="' + v.items[9]._uid + '"] .rt-ed');
  ed.innerHTML = '<b>Sede 10</b>'; ed.dispatchEvent(new w.Event('input', { bubbles: true }));
  assert.strictEqual(T.f('p').variants.content.items[9].value, '<b>Sede 10</b>');
  assert.ok(/Sede 10/.test(q('.cv[data-uid="' + v.items[9]._uid + '"] .cvs').textContent), 'el resumen se actualiza al escribir');

  // ---- campos de entrada: nombre, ayuda y texto de ejemplo; imagen
  T.setCurrent('n');
  ['display_label', 'help', 'placeholder'].forEach((p) => assert.ok(act('enable', `[data-vp="${p}"]`), p));
  await click(act('enable', '[data-vp="placeholder"]'));
  assert.deepStrictEqual(J(T.f('n').variants.placeholder), { items: [], default: '' });
  await click(act('add', '[data-vp="placeholder"]'));
  typeIn(q('[data-vtxt^="placeholder:"]'), 'ej. Ana');
  assert.strictEqual(T.f('n').variants.placeholder.items[0].value, 'ej. Ana');
  await click(q('[data-cx="startroot"]')); assert.strictEqual(T.f('n').show_if.field, 'c');
  await click(q('#vis [data-cx="clearroot"]')); assert.strictEqual(T.f('n').show_if, null);
  T.design().fields.i = { id: 'i', type: 'image', src: 'acme/a.png' };
  T.setCurrent('i');
  await click(act('enable', '[data-vp="src"]')); assert.strictEqual(T.f('i').variants.src.default, 'acme/a.png');
  await click(act('add', '[data-vp="src"]'));
  assert.ok(q('[data-vimg^="src:"]') && q('[data-vimg="src:def"]') && q('img[src="/a/acme/a.png"]'));

  // ---- rendimiento (jsdom, que es más lento que un navegador): pintar el panel con 31 variantes plegadas contra desplegadas
  T.setCurrent('p');
  const timeIt = (fn) => { const t0 = process.hrtime.bigint(); fn(); return Number(process.hrtime.bigint() - t0) / 1e6; };
  T.f('p').variants.content.items.forEach((it) => T.foldItem.set(it._uid, false));
  const folded = timeIt(() => T.setCurrent('p'));
  T.f('p').variants.content.items.forEach((it) => T.foldItem.set(it._uid, true));
  const open = timeIt(() => T.setCurrent('p'));
  console.log(`  panel con 31 variantes en jsdom: plegadas ${folded.toFixed(0)} ms, desplegadas ${open.toFixed(0)} ms`);
  assert.ok(folded < open, 'plegadas debe ser más barato que desplegadas');
  console.log('editor_variants_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
