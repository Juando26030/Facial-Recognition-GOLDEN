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

// Cédula con PDF417 sin cifrar (campos de ancho fijo, vacíos con \0): la cámara entrega eso y se registra por la cédula (19-nov-2026)
{
  const pad = (v, n) => (v + '\0'.repeat(n)).slice(0, n);
  const raw = pad('\0\0\0\0PubDSK_1', 48) + '1016100329' + pad('ANGARITA', 23) + pad('ROJAS', 23) + pad('JHOAN', 23) + pad('SEBASTIAN', 23) + '\0M' + '19980206' + pad('', 20);
  const r = classify(raw, 'pdf417', old);
  assert.deepStrictEqual(r, { kind: 'cedula', cedula: '1016100329', nombres: 'JHOAN SEBASTIAN', apellidos: 'ANGARITA ROJAS' });
  const corta = pad('\0PubDSK_1', 48) + '0079876543' + pad('PEREZ', 23) + pad('', 23) + pad('ANA', 23) + pad('', 23) + '\0F' + '19850101' + pad('', 20);
  assert.deepStrictEqual(classify(corta, 'pdf417', old), { kind: 'cedula', cedula: '79876543', nombres: 'ANA', apellidos: 'PEREZ' }, 'sin segundo apellido ni segundo nombre, y con ceros a la izquierda');
  assert.strictEqual(classify('1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206', 'pdf417', old).cedula, '1016100329', 'el CSV del lector de mano sigue valiendo');
}
