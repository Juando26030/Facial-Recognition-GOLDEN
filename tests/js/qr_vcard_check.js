// QR en vCard (Fase 10, C): static/js/vcard.js + lectores (qr.js, search-core.js). Correr: node tests/js/qr_vcard_check.js
const assert = require('assert');
const V = require('../../static/js/vcard.js');
const { parse, classify, isDynamic, unwrap, collect } = require('../../static/js/qr.js');
const SC = require('../../static/js/search-core.js');
const qrcode = require('../../static/vendor/qrcode-generator-1.4.4.min.js');

// ---- construir: nombre, teléfono y el código en NOTE
const card = V.build({ first_name: 'Ana', last_name: 'Pérez', phone: '300 123 4567', note: '1016100329|Ana|Pérez' });
assert.strictEqual(card, ['BEGIN:VCARD', 'VERSION:3.0', 'N:Pérez;Ana;;;', 'FN:Ana Pérez', 'TEL:300 123 4567', 'NOTE:GW:1016100329|Ana|Pérez', 'END:VCARD'].join('\n'));
assert.ok(!V.build({ first_name: 'Ana', last_name: 'P', note: 'x' }).includes('TEL'), 'sin teléfono no hay TEL');
assert.ok(V.build({ note: 'x' }).includes('FN:Asistente'));
assert.ok(V.build({ first_name: 'A;B,C', last_name: 'D', note: 'x' }).includes('N:D;A\\;B\\,C;;;'), 'se escapan ; y ,');

// ---- sacar el código de NOTE (round trip) y seguir aceptando el formato anterior
const payloads = ['1016100329', '1016100329|Ana|Pérez', 'Ana, la; de\\Mora|1.016.100.329', 'gwq1.5.12345678.' + 'a'.repeat(20), 'gwq1s.5.' + 'b'.repeat(20)];
for (const p of payloads) {
  assert.strictEqual(V.unwrap(V.build({ first_name: 'Ana', last_name: 'Mora', phone: '3001234567', note: p })), p, p);
  assert.strictEqual(unwrap(V.build({ first_name: 'Ana', note: p })), p);
}
assert.strictEqual(unwrap('1016100329|Ana|Mora'), '1016100329|Ana|Mora');            // formato anterior: igual
assert.strictEqual(unwrap('  gwq1s.5.' + 'b'.repeat(20)), '  gwq1s.5.' + 'b'.repeat(20));
const foreign = 'BEGIN:VCARD\nVERSION:3.0\nFN:Otro\nEND:VCARD';
assert.strictEqual(unwrap(foreign), foreign, 'una vCard ajena no se toca');
assert.strictEqual(unwrap(card.replace(/\n/g, '\r\n')), '1016100329|Ana|Pérez', 'CRLF');
assert.strictEqual(unwrap(card.replace(/\n/g, '')), '1016100329|Ana|PérezEND:VCARD'.replace('END:VCARD', ''), 'un lector que se come los saltos de línea');
assert.strictEqual(unwrap(card.replace('NOTE:GW:1016100329|Ana|Pérez', 'NOTE:GW:1016100329|Ana|\r\n Pérez')), '1016100329|Ana|Pérez', 'línea doblada');

// ---- los lectores
assert.deepStrictEqual(parse(card), { cedula: '1016100329', nombres: 'Ana', apellidos: 'Pérez', isQr: true });
assert.deepStrictEqual(parse('1016100329|Ana|Pérez'), parse(card));
assert.deepStrictEqual(classify(card, 'qr_code', null), { kind: 'qr', cedula: '1016100329', nombres: 'Ana', apellidos: 'Pérez' });
const dyn = 'gwq1.5.12345678.' + 'a'.repeat(20);
assert.strictEqual(isDynamic(V.build({ first_name: 'Ana', note: dyn })), true);
assert.strictEqual(isDynamic(card), false);
assert.strictEqual(isDynamic(dyn), true);
assert.strictEqual(parse(V.build({ first_name: 'Ana', note: '1016100329' })).cedula, '1016100329');
const q = SC.classifyQuery(card);
assert.strictEqual(q.kind, 'qr'); assert.strictEqual(q.cedula, SC.classifyQuery('1016100329|Ana|Pérez').cedula);

// ---- lector de mano: la vCard llega en varias líneas, cada una con su Enter
let out = [];
for (const line of card.split('\n')) out.push(collect(line));
assert.deepStrictEqual(out.slice(0, -1).filter((x) => x !== null), [], 'mientras no termina, nada');
assert.strictEqual(out[out.length - 1], card);
assert.strictEqual(collect('1016100329|Ana|Mora'), '1016100329|Ana|Mora');            // lectura normal: pasa tal cual
assert.strictEqual(collect('  52123456 '), '52123456');

// ---- densidad: la vCard cabe en una versión de QR chica con nivel L (el tamaño de la etiqueta no cambia: solo hay más cuadritos)
function version(text, level) {
  qrcode.stringToBytes = qrcode.stringToBytesFuncs['UTF-8'];
  const qr = qrcode(0, level); qr.addData(text); qr.make();
  return (qr.getModuleCount() - 17) / 4;
}
const typical = V.build({ first_name: 'María Fernanda', last_name: 'Rodríguez Castañeda', phone: '3001234567', note: '1016100329|María Fernanda|Rodríguez Castañeda' });
const dynamicCard = V.build({ first_name: 'María Fernanda', last_name: 'Rodríguez Castañeda', phone: '3001234567', note: dyn });
const longest = V.build({ first_name: 'Juan Sebastián Alejandro', last_name: 'Rodríguez Castañeda de la Hoz', phone: '+57 300 123 4567', note: '1016100329|Juan Sebastián Alejandro|Rodríguez Castañeda de la Hoz' });
console.log('versión QR  anterior(M):', version('1016100329|María Fernanda|Rodríguez Castañeda', 'M'), ' vCard típica(L):', version(typical, 'L'), ' vCard dinámica(L):', version(dynamicCard, 'L'), ' vCard larga(L):', version(longest, 'L'));
assert.ok(version(typical, 'L') <= 8, 'la vCard típica cabe en versión 8 (49 módulos) con nivel L');
assert.ok(version(dynamicCard, 'L') <= 8);
assert.ok(version(longest, 'L') <= 10, 'aun el peor caso razonable no pasa de versión 10 (57 módulos)');
assert.ok(version(typical, 'L') < version(typical, 'M'), 'L es más chico que M para el mismo texto');
console.log('qr_vcard_check OK');
