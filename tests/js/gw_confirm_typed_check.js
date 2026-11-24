// Confirmaciones fuertes de gestión (static/js/gw-confirm-typed.js): lógica pura y flujo con showPrompt/showConfirm simulados. Uso: node tests/js/gw_confirm_typed_check.js
const assert = require('assert');
const toasts = []; let answer = null; const prompts = []; const confirms = [];
global.showPrompt = (html, opts) => { prompts.push({ html, opts }); return Promise.resolve(answer); };
global.showConfirm = (html, opts) => { confirms.push({ html, opts }); return Promise.resolve(true); };
global.showToast = (m, t) => toasts.push([m, t]);
const G = require('../../static/js/gw-confirm-typed.js');

assert.ok(G.matches('eliminar', 'ELIMINAR') && G.matches('  Eliminar ', 'ELIMINAR') && G.matches('suprímir', 'SUPRIMIR'));
assert.ok(!G.matches('', 'ELIMINAR') && !G.matches('ELIMINA', 'ELIMINAR') && !G.matches('x', '') && !G.matches(null, 'REABRIR'));
assert.strictEqual(G.fill('a {id} b {n}', { id: '<1>', n: 3 }), 'a &lt;1&gt; b 3');          // lo que escribe la persona va escapado
assert.strictEqual(G.fill('a {id}', {}), 'a {id}');

(async () => {
  answer = null; assert.strictEqual(await G.typed('x', 'ELIMINAR'), false); assert.strictEqual(toasts.length, 0);          // cancelar: no hace nada ni regaña
  answer = 'borrar'; assert.strictEqual(await G.typed('x', 'ELIMINAR'), false); assert.ok(/hay que escribir ELIMINAR/.test(toasts[0][0]) && toasts[0][1] === 'error');
  answer = 'eliminar'; assert.strictEqual(await G.typed('x', 'ELIMINAR', { title: 'T', confirmLabel: 'L' }), true);
  const o2 = prompts[2].opts;
  assert.deepStrictEqual({ title: o2.title, placeholder: o2.placeholder, confirmLabel: o2.confirmLabel }, { title: 'T', placeholder: 'ELIMINAR', confirmLabel: 'L' });
  // 23-nov-2026: el cuadro valida ahí mismo (no se cierra en silencio): palabra mal o vacía → aviso; bien → vacío
  assert.ok(o2.validate('eliminar ya').includes('ELIMINAR') && o2.validate('').includes('ELIMINAR'));
  assert.strictEqual(o2.validate('  eliminar '), '');
  answer = 'reabrir'; assert.strictEqual(await G.reopenEvent('En Proceso'), true);
  const re = prompts[prompts.length - 1].html; assert.ok(/7 días/.test(re) && /empieza de cero/.test(re) && /no vuelven/.test(re) && /REABRIR/.test(re));
  // cuenta que cobra
  const accounts = [{ id: 4, name: 'Acme <SAS>' }];
  assert.strictEqual(G.accountName({ account_id: 4 }, accounts), 'Acme <SAS>');
  assert.strictEqual(G.accountName({ account_id: 9 }, accounts), 'cuenta de cobro n.º 9');
  assert.strictEqual(G.accountName({ account_id: null }, accounts), null);
  const none = G.accountLine({ account_id: null }, { admin: true });
  assert.ok(/Cobra con:<\/b> \(sin asignar\) → asignar en <a href="\/cuentas-de-cobro">Cuentas de cobro<\/a>/.test(none), none);
  assert.ok(!/<a /.test(G.accountLine({ account_id: null }, { admin: false })));          // quien no es administrador no puede abrir esa pantalla: sin enlace
  assert.ok(/Acme &lt;SAS&gt;/.test(G.accountLine({ account_id: 4 }, { admin: true, accounts })));
  assert.strictEqual(await G.activatePaidForm({ account: 'Acme' }), true);
  const c = confirms[0]; assert.ok(/cobra dinero real/.test(c.html) && /Cobra con:<\/b> Acme/.test(c.html) && c.opts.variant === 'warning');
  await G.activatePaidForm({}); assert.ok(/\(sin asignar\): cobra la cuenta de Golden/.test(confirms[1].html));
  console.log('gw_confirm_typed_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
