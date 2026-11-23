// Prueba de la parte pura de static/js/event-contacts.js (normalize / problem). Correr: node tests/js/event_contacts_check.js
const assert = require('assert');
const { normalize, problem } = require('../../static/js/event-contacts.js');

assert.deepStrictEqual(normalize([]), []);
assert.deepStrictEqual(normalize([{ name: '', phone: '', email: '' }]), [], 'filas vacías se descartan');
let r = normalize([{ name: ' Ana ', email: 'a@x.co' }, { name: 'Luis', phone: '300' }]);
assert.strictEqual(r.length, 2); assert.strictEqual(r[0].name, 'Ana'); assert.strictEqual(r[0].is_primary, true); assert.strictEqual(r[1].is_primary, false, 'sin principal marcado, el primero');
r = normalize([{ name: 'A', is_primary: false }, { name: 'B', is_primary: true }, { name: 'C', is_primary: true }]);
assert.deepStrictEqual(r.map((x) => x.is_primary), [false, true, false], 'solo un principal: el primero marcado');
assert.ok(problem([{ name: 'A', email: 'a@x.co' }]).includes('teléfono'), 'a mano: teléfono obligatorio');
assert.ok(problem([{ name: 'A', phone: '1' }]).includes('correo'), 'a mano: correo obligatorio');
assert.strictEqual(problem([{ name: 'A', email: 'a@x.co', phone: '1' }]), '');
assert.strictEqual(problem([{ name: 'A', crm_contact_id: 5 }]), '', 'del CRM: sin exigir correo');
assert.ok(problem([{ name: '', phone: '300' }]).includes('necesita un nombre'));
assert.ok(problem([{ name: 'Ana', phone: '1', email: 'no-es-correo' }]).includes('correo'));
console.log('event_contacts_check OK');
