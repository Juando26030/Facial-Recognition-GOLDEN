// P12: formulario de varias hojas en el navegador (jsdom): visibilidad (mismos casos que pytest), navegación, validación por hoja, Enter, historial, saltos y sin validación nativa.
// Correr: npm ci && node tests/js/form_sheets_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const V = JSON.parse(fs.readFileSync(path.join(root, 'tests/sheet_vectors.json'), 'utf8'));
const { computeVisible } = require('../../static/js/form-render.js');
V.cases.forEach((c) => assert.deepStrictEqual([...computeVisible(V.design, c.values)].sort(), [...c.visible].sort(), c.name));

const dom = new JSDOM('<!doctype html><body><div id="h"></div></body>', { runScripts: 'outside-only', url: 'https://example.test/f/1/feria' });
const w = dom.window;
w.HTMLElement.prototype.scrollIntoView = () => {};
const stored = [];
const origSet = w.Storage.prototype.setItem;
w.Storage.prototype.setItem = function (k, v) { stored.push(k); return origSet.call(this, k, v); };
['static/js/fonts-propias.js', 'static/js/rich-text.js', 'static/js/form-render.js'].forEach((f) => w.eval(fs.readFileSync(path.join(root, f), 'utf8')));
const doc = w.document, tick = (ms) => new Promise((r) => setTimeout(r, ms || 20));
const fr = w.FormRender.render(doc.getElementById('h'), JSON.parse(JSON.stringify(V.design)), { previewOnly: true });
const sec = (id) => doc.querySelector(`[data-sheet="${id}"]`), shown = () => [...doc.querySelectorAll('.fr-sheet')].filter((s) => s.style.display !== 'none').map((s) => s.dataset.sheet);
const prog = () => doc.querySelector('[data-prog-text]').textContent, live = () => doc.querySelector('.fr-live').textContent;
const set = (name, v) => { const el = doc.querySelector(`[name="${name}"]`); el.value = v; el.dispatchEvent(new w.Event('input', { bubbles: true })); };
const visibleBtn = (sel) => doc.querySelector(sel).style.display !== 'none';

(async () => {
  assert.strictEqual(fr.form.noValidate, true, 'sin validación nativa del navegador');
  assert.strictEqual(doc.querySelectorAll('[required]').length, 0, 'ningún campo obligatorio de hojas ocultas puede disparar «no se puede enfocar»');
  // arranque: solo la primera y la última hoja se ven (las condicionales no cumplen todavía)
  assert.deepStrictEqual(shown(), ['s1']); assert.strictEqual(prog(), 'Hoja 1 de 2');
  assert.ok(visibleBtn('[data-nav=next]') && !visibleBtn('[data-nav=prev]') && !visibleBtn('.fr-btn'), 'en la primera: Siguiente sí, Anterior y Enviar no');
  assert.ok(sec('s1').textContent.includes('Tus datos'));

  // «Siguiente» con obligatorios sin llenar: se queda, marca, enfoca el primero y avisa
  fr.sheets.next();
  assert.deepStrictEqual(shown(), ['s1']);
  assert.ok(doc.querySelectorAll('.has-err').length === 2, 'marca los dos faltantes de esta hoja');
  assert.strictEqual(doc.activeElement.name, 'c', 'enfoca el primero');
  assert.strictEqual(doc.querySelector('[name=c]').getAttribute('aria-invalid'), 'true');
  await tick(60);
  assert.ok(/Faltan por completar o corregir 2 campos en esta hoja\. Empieza por «Ciudad»/.test(live()), live());

  // Bogotá + Empleado: aparecen las hojas 2 y 3 → "Hoja 1 de 4"
  set('c', 'Bogotá'); set('t', 'Empleado');
  assert.strictEqual(prog(), 'Hoja 1 de 4');
  fr.sheets.next();
  assert.deepStrictEqual(shown(), ['s2']); assert.strictEqual(prog(), 'Hoja 2 de 4');
  assert.strictEqual(doc.activeElement.id, 'frs_s2', 'el foco va al título de la hoja');
  await tick(60);
  assert.strictEqual(live(), 'Hoja 2 de 4: Sede Bogotá');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(Object.keys(w.history.state).sort())), ['d', 'frSheet'], 'en el historial solo van números de hoja, nunca datos');
  assert.strictEqual(w.history.state.frSheet, 1);
  assert.ok(visibleBtn('[data-nav=prev]') && visibleBtn('[data-nav=next]'));
  // «Anterior» conserva lo escrito y sigue el historial
  set('a', 'Chapinero');
  fr.sheets.prev(); await tick(80);
  assert.deepStrictEqual(shown(), ['s1']);
  assert.strictEqual(doc.querySelector('[name=c]').value, 'Bogotá', 'lo escrito se conserva');
  fr.sheets.next(); assert.deepStrictEqual(shown(), ['s2']);
  assert.strictEqual(doc.querySelector('[name=a]').value, 'Chapinero');
  // el botón «atrás» del navegador vuelve a la hoja anterior en vez de salir
  w.history.back(); await tick(80);
  assert.deepStrictEqual(shown(), ['s1'], 'atrás → hoja anterior');
  fr.sheets.next(); fr.sheets.next();                                     // a la 3 (b es obligatorio)
  assert.deepStrictEqual(shown(), ['s3']);
  fr.sheets.next();                                                      // falta el cargo: no avanza
  assert.deepStrictEqual(shown(), ['s3']);
  set('b', 'Gerente'); fr.sheets.next();
  assert.deepStrictEqual(shown(), ['s4']); assert.strictEqual(prog(), 'Hoja 4 de 4');
  assert.ok(visibleBtn('.fr-btn') && !visibleBtn('[data-nav=next]'), 'Enviar solo en la última hoja');

  // lo que se ocultó después no viaja: cambia la ciudad y las hojas 2 y 3 (a, b, d) se descartan
  set('z', 'comentario');
  fr.sheets.show(0); set('c', 'Cali');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(fr.collect().values)), { c: 'Cali', t: 'Empleado', b: 'Gerente', z: 'comentario' }, 'hoja 2 oculta: su campo (a) y el que dependía de él (d) no viajan');
  set('t', 'Invitado');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(fr.collect().values)), { c: 'Cali', t: 'Invitado', z: 'comentario' }, 'hoja 3 oculta: tampoco viaja lo escrito allí');
  assert.strictEqual(prog(), 'Hoja 1 de 2');

  // Enter: avanza solo en campos de una línea; en select no
  set('c', 'Bogotá'); set('t', 'Empleado');
  const enter = (el) => { const ev = new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }); el.dispatchEvent(ev); return ev.defaultPrevented; };
  assert.strictEqual(enter(doc.querySelector('select[name=c]')), false, 'Enter en una lista no avanza');
  fr.sheets.next();                                                      // a la hoja 2
  assert.strictEqual(enter(doc.querySelector('input[name=a]')), true, 'Enter en un campo de una línea avanza');
  assert.deepStrictEqual(shown(), ['s3']);

  // enviar saltándose hojas: validate() revisa todas las visibles y salta a la primera con error
  set('b', ''); fr.sheets.show(3);
  assert.strictEqual(fr.validate(), false);
  assert.deepStrictEqual(shown(), ['s3'], 'salta a la hoja con el error');
  // errores del servidor: salta a la hoja del primero
  fr.sheets.show(3); fr.setErrors({ a: 'Barrio: es obligatorio' });
  assert.deepStrictEqual(shown(), ['s2']);
  assert.ok(doc.querySelector('[data-fid=a]').classList.contains('has-err'));

  // una hoja con todos sus campos ocultos se salta sola
  set('t', 'Invitado'); fr.sheets.show(0);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(fr.sheets.effective())), [0, 1, 3]);
  assert.strictEqual(prog(), 'Hoja 1 de 3');

  assert.deepStrictEqual([...new Set(stored)], ['gw_cur'].filter((k) => stored.includes(k)), 'nada de lo escrito va a localStorage');

  // un formulario de una sola hoja: sin barra, sin botones de hojas, igual que siempre
  const solo = JSON.parse(JSON.stringify(V.design)); delete solo.sheets; solo.rows.forEach((r) => delete r.sheet);
  const host2 = doc.createElement('div'); doc.body.append(host2);
  const fr2 = w.FormRender.render(host2, solo, { previewOnly: true });
  assert.strictEqual(fr2.sheets, null); assert.strictEqual(host2.querySelectorAll('.fr-sheet, .fr-nav, .fr-prog').length, 0);
  assert.ok(host2.querySelector('.fr-btn').style.display !== 'none');
  console.log('form_sheets_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
