// Prueba de la evaluación en vivo de requisitos de contraseña (static/js/password-policy.js).
// Correr: node tests/js/password_policy_check.js
// Los MISMOS casos están en tests/test_password_policy.py contra app/security.py: si el navegador y el servidor divergen, una de las dos pruebas falla.
const assert = require('assert');
const { evaluate, strength } = require('../../static/js/password-policy.js');
const COMMON = ['password', 'passw0rd', 'colombia', 'admin', '123456', '12345678', 'golden'];
const mk = (strict) => ({
  strict, min_length: strict ? 10 : 8, common: COMMON,
  rules: [{ id: 'length', label: 'largo' }].concat(strict ? [{ id: 'letter_digit', label: 'letra y número' }] : [], [{ id: 'not_username', label: 'no usuario' }, { id: 'not_common', label: 'no común' }]),
});
const cases = require('./password_cases.json');
for (const c of cases) {
  const r = evaluate(mk(c.strict), c.password, c.username || null);
  assert.strictEqual(r.allOk, c.ok, `${JSON.stringify(c)} -> ${JSON.stringify(r.rules)}`);
  if (!c.ok) assert.strictEqual(r.rules.find((x) => !x.ok).id, c.first_failed, JSON.stringify(c));
}
// confirmación y «distinta a la actual»
let r = evaluate(mk(false), 'Clave-segura-1', null, { confirm: 'Clave-segura-2', current: 'otra-cosa-1' });
assert.strictEqual(r.allOk, false); assert.strictEqual(r.rules.find((x) => !x.ok).id, 'match');
r = evaluate(mk(false), 'Clave-segura-1', null, { confirm: 'Clave-segura-1', current: 'Clave-segura-1' });
assert.strictEqual(r.rules.find((x) => !x.ok).id, 'different');
r = evaluate(mk(false), 'Clave-segura-1', null, { confirm: 'Clave-segura-1', current: 'otra-cosa-1' });
assert.strictEqual(r.allOk, true);
// fuerza: sin cumplir requisitos nunca pasa de «Débil»; vacía = sin etiqueta
assert.strictEqual(strength('', false).label, '');
assert.ok(strength('Aa1!Aa1!Aa1!Aa1!', false).level <= 1);
assert.strictEqual(strength('Aa1!Aa1!Aa1!Aa1!', true).label, 'Muy buena');
assert.ok(strength('abcdefgh1', true).level <= 2);
console.log('password_policy_check OK (' + cases.length + ' casos)');
