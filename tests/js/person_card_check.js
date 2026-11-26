// Tarjeta de la persona en Inventario y Zonas (static/js/person-card.js, 25-nov-2026): siempre cédula y nombre, campos «Mostrar en el registro», estado (rojo si no registrada) y la acción al lado.
const assert = require('assert');
const C = require('../../static/js/person-card.js');
const fields = [{ key: 'id', label: 'Cédula' }, { key: 'first_name', label: 'Nombres' }, { key: 'last_name', label: 'Apellidos' },
  { key: 'city', label: 'Ciudad' }, { key: 'opcional_1', label: 'Talla' }, { key: 'certificate', label: 'Certificado' }, { key: 'firma', label: 'Firma', type: 'signature' }];
const u = { id: '1000', first_name: 'Ana', last_name: 'Lee', status: 'No registrado', city: 'BOGOTÁ', extra_fields: { opcional_1: 'M' }, code: '77' };
const ex = C.extraFields(u, fields);
assert.deepStrictEqual(ex.map((f) => f.label), ['Ciudad', 'Talla', 'Certificado']);           // sin cédula/nombres (van arriba) ni firma
assert.deepStrictEqual(ex.map((f) => f.value), ['BOGOTÁ', 'M', 'No']);
let r = C.render(u, { cardFields: fields, action: '<button id="x">Entregar</button>' });
assert.ok(/gw-person--err/.test(r.cls) && /No registrado/.test(r.html) && /NO está registrada/.test(r.html));
assert.ok(/Cédula: 1000/.test(r.html) && /Código: 77/.test(r.html) && /<button id="x">Entregar<\/button>/.test(r.html) && /BOGOTÁ/.test(r.html));
r = C.render(Object.assign({}, u, { status: 'Registrado', first_name: '<b>x' }), { cardFields: [] });
assert.ok(/gw-person--ok/.test(r.cls) && /Registrado/.test(r.html) && !/NO está registrada/.test(r.html) && /&lt;b&gt;x/.test(r.html));   // escapa
console.log('person_card_check: OK');
