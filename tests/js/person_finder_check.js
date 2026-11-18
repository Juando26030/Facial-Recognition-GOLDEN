// Buscador único de Control de Áreas e Inventario (static/js/person-finder.js). Correr: node tests/js/person_finder_check.js
const assert = require('assert');
global.self = global;
global.GWVcard = require('../../static/js/vcard.js');
global.SearchCore = require('../../static/js/search-core.js');
global.QrCode = require('../../static/js/qr.js');
global.EVENT_ID = 7;
global.showToast = () => {};
const PF = require('../../static/js/person-finder.js');

const people = [
  { id: '1016100329', first_name: 'María Fernanda', last_name: 'Rodríguez', entity: 'Golden', code: 'A-0001' },
  { id: '52123456', first_name: 'Juan David', last_name: 'Pérez', entity: 'Acme' },
  { id: '52999000', first_name: 'Juana', last_name: 'Pérez Gómez', entity: 'Acme' },
];

function make(extra) {
  const handlers = {}, bh = {};
  const input = { value: '', addEventListener: (t, f) => { handlers[t] = f; } };
  const box = { innerHTML: '', hidden: true, addEventListener: (t, f) => { bh[t] = f; }, };
  const picked = [], raws = [], msgs = [];
  const api = PF.attach(Object.assign({ input, box, users: () => people, purpose: 'area', onPick: (u, via) => picked.push([u.id, via]), onRaw: (c, via) => raws.push([c, via]), onMessage: (m) => msgs.push(m) }, extra || {}));
  return { input, box, api, picked, raws, msgs, type: (t) => { input.value = t; handlers.input && handlers.input(); }, enter: async (t) => { if (t !== undefined) input.value = t; await api.submit(); } };
}

(async () => {
  // 1) en vivo: por nombre, por cédula (prefijo) y por empresa; sin elegir a nadie
  let c = make();
  c.type('juan'); assert.ok(c.box.innerHTML.includes('Juan David') && c.box.innerHTML.includes('Juana') && !c.box.hidden, 'nombre en vivo'); assert.strictEqual(c.picked.length, 0);
  c.type('5212'); assert.ok(c.box.innerHTML.includes('52123456') && !c.box.innerHTML.includes('52999000'), 'cédula por prefijo');
  c.type('acme'); assert.ok(c.box.innerHTML.includes('Empresa'), 'por empresa');
  c.type('zzzz'); assert.ok(c.box.innerHTML.includes('Sin coincidencias'));

  // 2) Enter con cédula completa exacta → toma a la persona (como el QR de la escarapela)
  c = make(); await c.enter('1016100329'); assert.deepStrictEqual(c.picked, [['1016100329', 'cedula']]);
  c = make(); await c.enter('1016100329|María Fernanda|Rodríguez'); assert.deepStrictEqual(c.picked, [['1016100329', 'qr']], 'QR propio');
  c = make(); await c.enter('1.016.100.329'); assert.deepStrictEqual(c.picked, [['1016100329', 'cedula']], 'con puntos');

  // 3) Enter con un nombre ambiguo → lista para elegir, NO elige solo; y al hacer clic sí
  c = make(); await c.enter('juan'); assert.strictEqual(c.picked.length, 0); assert.ok(c.box.innerHTML.includes('Juan David') && c.box.innerHTML.includes('Juana'));
  c = make(); await c.enter('maria'); assert.strictEqual(c.picked.length, 0, 'un nombre con una sola coincidencia también se confirma en la lista'); assert.ok(c.box.innerHTML.includes('María Fernanda'));

  // 4) el código de la persona (serial del QR) también encuentra
  c = make(); await c.enter('a-0001'); assert.deepStrictEqual(c.picked, [['1016100329', 'cedula']]);

  // 5) cédula completa que NO está en la lista → se manda al servidor tal cual
  c = make(); await c.enter('80111222'); assert.deepStrictEqual(c.raws, [['80111222', 'cedula']]);
  c = make(); await c.enter('xyz nadie'); assert.ok(c.msgs.length === 1 && c.picked.length === 0 && c.raws.length === 0, 'texto sin coincidencias: avisa');

  // 6) vCard de Golden (varias líneas, como las manda un lector de mano) → junta las líneas y toma el código de NOTE
  c = make();
  const card = GWVcard.build({ first_name: 'María Fernanda', last_name: 'Rodríguez', phone: '300', email: 'm@x.co', note: '1016100329|María Fernanda|Rodríguez' }).split('\n');
  for (const line of card) await c.enter(line);
  assert.deepStrictEqual(c.picked, [['1016100329', 'qr']], 'vCard por líneas');
  // …y la misma vCard de una vez, MECARD y enlace
  c = make(); await c.enter(card.join('\n')); assert.deepStrictEqual(c.picked, [['1016100329', 'qr']]);
  c = make(); await c.enter(GWVcard.buildMecard({ first_name: 'María', last_name: 'Rodríguez', note: '1016100329' })); assert.deepStrictEqual(c.picked, [['1016100329', 'qr']], 'MECARD de Golden');
  c = make(); await c.enter(GWVcard.buildLink('https://app.golden-eventos.com/tarjeta/AbCdEfGhIjKlMnOpQrSt', '1016100329')); assert.deepStrictEqual(c.picked, [['1016100329', 'qr']], 'enlace de Golden');

  // 7) vCard AJENA (el contacto de un celular, sin código de Golden): se busca por el nombre y se elige de la lista
  c = make(); await c.enter('BEGIN:VCARD\nVERSION:3.0\nN:Pérez;Juan David;;;\nFN:Juan David Pérez\nTEL:3001234567\nEND:VCARD');
  assert.strictEqual(c.picked.length, 0); assert.ok(c.box.innerHTML.includes('Juan David') && c.box.innerHTML.includes('52123456'), 'vCard ajena por nombre');
  assert.strictEqual(PF.nameFromForeignCard('MECARD:N:Pérez,Juan David;TEL:300;;'), 'Juan David Pérez');

  // 8) el QR dinámico de la credencial digital lo valida el servidor y devuelve «cédula|nombres|apellidos»
  global.QrCode = Object.assign({}, global.QrCode, { resolveDynamic: async () => '52123456|Juan David|Pérez' });
  c = make(); await c.enter('gwq1.5.12345.0123456789abcdef0123'); assert.deepStrictEqual(c.picked, [['52123456', 'qr']], 'dinámico');
  global.QrCode = Object.assign({}, global.QrCode, { resolveDynamic: async () => { throw new Error('Código vencido'); } });
  c = make(); await c.enter('gwq1.5.12345.0123456789abcdef0123'); assert.deepStrictEqual(c.msgs, ['Código vencido']); assert.strictEqual(c.picked.length, 0);
  console.log('person_finder_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
