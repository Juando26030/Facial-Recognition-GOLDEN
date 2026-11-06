// QrCode.classify (static/js/qr.js): el único «Escanear» decide si lo leído es un QR de escarapela o la cédula (PDF417). Correr: node tests/js/qr_classify_check.js
const assert = require('assert');
const { classify } = require('../../static/js/qr.js');
const old = (t) => { const p = t.split(','); return p.length >= 5 && /^\d+$/.test(p[0]) ? { cedula: p[0], nombres: p[1] + ' ' + p[2], apellidos: p[3] + ' ' + p[4] } : null; };

assert.strictEqual(classify('', 'qr_code', old), null);
assert.deepStrictEqual(classify('1016100329|Ana|Perez', 'qr_code', old), { kind: 'qr', cedula: '1016100329', nombres: 'Ana', apellidos: 'Perez' });
assert.strictEqual(classify('1016100329', 'qr_code', old).kind, 'qr');                         // QR con solo la cédula: mismo flujo de QR de siempre
assert.deepStrictEqual(classify('1016100329,ANA,MARIA,PEREZ,GOMEZ', 'pdf417', old), { kind: 'cedula', cedula: '1016100329', nombres: 'ANA MARIA', apellidos: 'PEREZ GOMEZ' });
assert.strictEqual(classify('52.123.456', 'pdf417', old).cedula, '52123456');
assert.strictEqual(classify('\u0001\u0002PubDSK_1\u0000 1016100329 ANA', 'pdf417', old).cedula, '1016100329');   // PDF417 con bytes de más: se extrae la cédula
assert.strictEqual(classify('sin numeros', 'pdf417', old), null);
console.log('qr_classify_check OK');
