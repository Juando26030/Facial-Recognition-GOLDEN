// P12: panel «Hojas» del diseñador (bloques de condiciones y de hojas de templates/kiosk_formulario_editor.html) con jsdom y dobles de lo demás.
// Correr: npm ci && node tests/js/editor_sheets_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const tpl = fs.readFileSync(path.join(root, 'templates/kiosk_formulario_editor.html'), 'utf8').split('\r\n').join('\n');
const block = tpl.slice(tpl.indexOf('// ---------------------------------------------------------------- condiciones en árbol y variantes (P9)'), tpl.indexOf('// ---------------------------------------------------------------- paleta'));
const grab = (name) => tpl.split('\n').find((l) => l.startsWith(`function ${name}(`));      // son funciones de una línea
assert.ok(block.includes('function renderSheets') && block.includes('function deleteSheet'), 'bloques encontrados');

const dom = new JSDOM('<!doctype html><body><div id="sheetsBar"></div><div id="sheetsPanel"></div><div id="propsBox"></div></body>', { runScripts: 'outside-only' });
const w = dom.window;
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-sync.js', 'static/js/cond-tree.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(root, f), 'utf8')));
w.eval(`
  var toasts = [], confirms = [], dirty = 0;
  const $ = (id) => document.getElementById(id);
  const esc = RichText.esc;
  const STATIC = ['heading', 'paragraph', 'image'], NOCOND = ['payment', 'companions'];
  const TYPES = { text_short: ['Texto', ''], select: ['Lista', ''], payment: ['Pago', ''] };
  let n = 0; const uid = () => 'f' + (++n);
  let eventFields = [], selected = null;
  let design = { fields: {
    a: { id: 'a', type: 'select', label: 'Ciudad', options: ['Bogotá', 'Cali'], key: 'opcional_1', sync: false },
    b: { id: 'b', type: 'text_short', label: 'Barrio', show_if: { field: 'a', op: 'equals', value: 'Bogotá' } },
    pay: { id: 'pay', type: 'payment', label: 'Pago', pay: { mode: 'fixed', amount: 2000 } } },
    rows: [{ align: 'left', items: ['a'] }, { align: 'left', items: ['b'] }, { align: 'left', items: ['pay'] }] };
  let confirmAnswer = true;
  const showToast = (m, k) => toasts.push([m, k]), showConfirm = async (m) => { confirms.push(m); return confirmAnswer; };
  const markDirty = () => { dirty++; }, renderCanvas = () => {}, renderProps = () => {}, renderAll = () => { renderSheets(); };
  let rtMounts = []; const mountRt = () => ({ destroy() {} });
  ${grab('locate')}
  ${grab('detach')}
  ${block}
  window.T = { design: () => design, toasts, confirms, dirty: () => dirty, answer: (v) => { confirmAnswer = v; }, active: () => activeSheet, norm: normSheets, fieldsBefore: fieldsBeforeSheet, moveToSheet, split: splitSheets, setSelected: (v) => { selected = v; }, setActive: (v) => { activeSheet = v; renderSheets(); } };
`);
const T = w.T, doc = w.document, tick = () => new Promise((r) => setTimeout(r, 0));
const click = (el) => el.dispatchEvent(new w.Event('click', { bubbles: true }));
const act = (a) => doc.querySelector(`[data-shact="${a}"]`);
const J = (x) => JSON.parse(JSON.stringify(x));
const sheetsOf = () => T.design().sheets.map((s) => s.id);
const rowsBySheet = () => J(T.design().rows.map((r) => [r.sheet, r.items.join(',')]));

(async () => {
  // una sola hoja: solo se ofrece dividir; las filas no llevan hoja
  T.setActive(null);
  assert.ok(act('split') && !T.design().sheets && T.design().rows.every((r) => !('sheet' in r)));
  click(act('split'));
  let [s1, s2] = sheetsOf();
  assert.strictEqual(sheetsOf().length, 2);
  assert.deepStrictEqual(rowsBySheet(), [[s1, 'a'], [s1, 'b'], [s2, 'pay']], 'todo en la primera; el pago, en la última');
  assert.strictEqual(T.active(), s1);

  // el selector «Hoja» mueve un campo; el pago no sale de la última
  T.moveToSheet('b', s2);
  assert.deepStrictEqual(rowsBySheet(), [[s1, 'a'], [s2, 'pay'], [s2, 'b']].sort((x, y) => (x[0] === s1 ? 0 : 1) - (y[0] === s1 ? 0 : 1)));
  T.moveToSheet('pay', s1);
  assert.ok(T.toasts.some(([m]) => /última hoja/.test(m)), 'el pago solo en la última');
  assert.ok(T.design().rows.find((r) => r.items.includes('pay')).sheet === s2);

  // agregar una hoja en medio: el pago sigue en la última
  T.setActive(s1);
  click(act('add'));
  assert.strictEqual(sheetsOf().length, 3);
  const mid = sheetsOf()[1];
  assert.deepStrictEqual(J(sheetsOf()), [s1, mid, s2]);
  assert.strictEqual(T.design().rows.find((r) => r.items.includes('pay')).sheet, s2);

  // condición de la hoja intermedia: solo con campos de hojas anteriores (a está en la 1; b en la 3)
  assert.deepStrictEqual(J(T.fieldsBefore(1).map((f) => f.id)), ['a']);
  T.setActive(mid);
  const start = doc.querySelector('#sheetsPanel [data-cx="startroot"]');
  assert.ok(start, 'la hoja intermedia puede tener condición');
  click(start);
  assert.deepStrictEqual(J(T.design().sheets[1].show_if), { field: 'a', op: 'equals', value: '' });
  T.setActive(s1);
  assert.ok(!doc.querySelector('#sheetsPanel [data-cx="startroot"]') && /siempre se muestran/.test(doc.getElementById('sheetsPanel').textContent), 'la primera no tiene condición');

  // reordenar: la hoja condicional que queda primera o última pierde su condición
  T.setActive(mid);
  click(act('left'));
  assert.deepStrictEqual(J(sheetsOf()), [mid, s1, s2]);
  assert.strictEqual(T.design().sheets[0].show_if, undefined, 'la primera siempre se muestra');
  click(act('right'));
  assert.deepStrictEqual(J(sheetsOf()), [s1, mid, s2]);

  // duplicar: copias con ids nuevos, sin el vínculo a Parámetros, con las reglas internas apuntando a las copias; el pago no se copia
  T.moveToSheet('b', s1);                                                // b (regla sobre a) vuelve a la hoja 1 junto con a
  T.setActive(s1);
  const before = Object.keys(T.design().fields).length;
  click(act('dup'));
  assert.strictEqual(sheetsOf().length, 4);
  assert.strictEqual(Object.keys(T.design().fields).length, before + 2, 'se copian a y b');
  const copyId = sheetsOf()[1];
  const copyRows = T.design().rows.filter((r) => r.sheet === copyId);
  const [ca, cb] = copyRows.map((r) => T.design().fields[r.items[0]]);
  assert.ok(ca.id !== 'a' && ca.key === null, 'la copia no usa el mismo campo del evento');
  assert.strictEqual(cb.show_if.field, ca.id, 'la regla de la copia apunta a la copia de a');
  assert.strictEqual(T.design().fields.b.show_if.field, 'a', 'el original no cambia');
  assert.ok(T.design().sheets[1].title.endsWith('(copia)'));

  // eliminar: pide confirmación con cuántos campos pasan y adónde; si dice que no, no cambia nada
  T.setActive(copyId);
  T.answer(false); click(act('del')); await tick();
  assert.strictEqual(sheetsOf().length, 4);
  assert.ok(/Sus 2 campos pasan a la hoja «Hoja 1»/.test(T.confirms[T.confirms.length - 1]), T.confirms[T.confirms.length - 1]);
  T.answer(true); click(act('del')); await tick();
  assert.strictEqual(sheetsOf().length, 3);
  assert.strictEqual(T.design().rows.filter((r) => r.sheet === s1).flatMap((r) => r.items).length, 4, 'ningún campo se pierde: pasan a la anterior');
  // la primera: sus campos pasan a la siguiente
  T.setActive(s1);
  click(act('del')); await tick();
  assert.ok(/pasan a la hoja «Hoja 2»/.test(T.confirms[T.confirms.length - 1]));
  assert.strictEqual(sheetsOf().length, 2);

  // con una sola hoja otra vez, el diseño vuelve a ser el de siempre
  T.setActive(sheetsOf()[0]);
  click(act('del')); await tick();
  assert.ok(!T.design().sheets && T.design().rows.every((r) => !('sheet' in r)), 'al quedar una hoja, desaparece `sheets`');
  console.log('editor_sheets_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
