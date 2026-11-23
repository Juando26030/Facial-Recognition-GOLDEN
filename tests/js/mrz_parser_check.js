// Lector de cédula NUEVA (app/pruebas/lector_cedula.html): lectura de las 3 líneas (MRZ) con dígitos de control. Datos 100 % sintéticos.
// Correr: node tests/js/mrz_parser_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'pruebas', 'lector_cedula.html'), 'utf8');
const a = html.indexOf('/* ============ Cédula NUEVA'), b = html.indexOf('/* ---------- geometría pura');
assert(a > 0 && b > a, 'no se encontró el bloque del parser en la página');
const { parseMrz, mrzCheck, mrzStrong } = new Function(html.slice(a, b) + '; return { parseMrz, mrzCheck, mrzStrong };')();

// 1) dígito de control: ejemplo oficial de ICAO 9303
assert.strictEqual(mrzCheck('L898902C3'), 6);
assert.strictEqual(mrzCheck('740812'), 2);
assert.strictEqual(mrzCheck('120415'), 9);

// 2) generador de las 3 líneas con sus controles
const pad = (s, n) => (s + '<'.repeat(n)).slice(0, n);
function make({ doc = '000123456', birth = '900515', sex = 'F', exp = '320101', ced = '52123456', names = 'GARCIA<LOPEZ<<MARIA<FERNANDA' }) {
  const opt1 = '12345';                                                           // dato opcional de la línea 1 (sin relación con la cédula)
  const l1 = pad('ICCOL' + doc + mrzCheck(doc) + opt1, 30);
  const opt2 = pad(ced + '<', 11);
  const core = birth + mrzCheck(birth) + sex + exp + mrzCheck(exp) + 'COL' + opt2;
  const comp = mrzCheck(l1.slice(5, 30) + core.slice(0, 7) + core.slice(8, 15) + opt2);
  return [l1, core + comp, pad(names, 30)];
}
const exp = (p, linea) => assert.strictEqual(p.linea, linea);

let L = make({});
assert.strictEqual(L.every(s => s.length === 30), true);
let p = parseMrz(L);
exp(p, '52123456,MARIA,FERNANDA,GARCIA,LOPEZ,19900515'); assert(mrzStrong(p)); assert.strictEqual(p.sexo, 'F'); assert.strictEqual(p.vencimiento, '20320101');

// 3) las líneas pueden llegar en otro orden
exp(parseMrz([L[2], L[0], L[1]]), '52123456,MARIA,FERNANDA,GARCIA,LOPEZ,19900515');

// 4) la cédula y los nombres NO están siempre en la misma posición
p = parseMrz(make({ ced: '1013259208', names: 'RAMIREZ<TORRES<<JUAN<DAVID' })); exp(p, '1013259208,JUAN,DAVID,RAMIREZ,TORRES,19900515'); assert(mrzStrong(p));
p = parseMrz(make({ ced: '79123456', names: 'DE<LA<CRUZ<<ANA' })); assert.strictEqual(p.apellido1, 'DE'); assert.strictEqual(p.apellido2, 'LA CRUZ'); assert.strictEqual(p.nombre1, 'ANA'); assert.strictEqual(p.nombre2, '');
p = parseMrz(make({ ced: '80123456', names: 'PEREZ<<LUIS<ALBERTO<JOSE' })); assert.strictEqual(p.apellido1, 'PEREZ'); assert.strictEqual(p.apellido2, ''); assert.strictEqual(p.nombre1, 'LUIS'); assert.strictEqual(p.nombre2, 'ALBERTO JOSE');
p = parseMrz(make({ ced: '1000000007', sex: 'M', birth: '050326' })); assert.strictEqual(p.nacimiento, '20050326'); assert.strictEqual(p.sexo, 'M');   // 05 → 2005
p = parseMrz(make({ birth: '350101' })); assert.strictEqual(p.nacimiento, '19350101');                                                            // año futuro → siglo XX

// 5) errores típicos del OCR: O por 0, I por 1, S por 5, dígitos dentro de los nombres…
let n = make({ ced: '1013259208' }).slice();
n[1] = n[1].replace('1013259208', '1O132S9208').replace('COL', 'C0L');
n[2] = n[2].replace('GARCIA', 'G4RCIA'.replace('4', 'A')).replace('MARIA', 'MAR1A');
p = parseMrz(n); assert.strictEqual(p.cedula, '1013259208'); assert.strictEqual(p.nombre1, 'MARIA'); assert(mrzStrong(p));

// 6) si un dígito de la cédula se lee mal, el control general lo delata: nunca queda como «fuerte»
n = make({ ced: '1013259208' }).slice(); n[1] = n[1].replace('1013259208', '1013259209');
p = parseMrz(n); assert.strictEqual(p.checks.composite, false); assert.strictEqual(mrzStrong(p), false);

// 6b) letras por dígitos también en el dato opcional de la línea 1 (el control general sigue cuadrando)
n = make({ ced: '1013259208' }).slice(); n[0] = n[0].replace('12345', 'I2345'); p = parseMrz(n); assert.strictEqual(p.checks.composite, true); assert(mrzStrong(p));
// 6c) si el OCR pierde un «<» de los nombres (sin «<<» entre apellidos y nombres), se separa por suposición pero NUNCA queda «fuerte»
n = make({ ced: '1013259208', names: 'RAMIREZ<TORRES<<JUAN<DAVID' }).slice(); n[2] = pad('RAMIREZ<TORRES<JUAN<DAVID', 30);
p = parseMrz(n); assert.strictEqual(p.apellido1, 'RAMIREZ'); assert.strictEqual(p.nombre2, 'DAVID'); assert.strictEqual(p.nombresIncierto, true); assert.strictEqual(mrzStrong(p), false);

// 7) basura o líneas incompletas → null
assert.strictEqual(parseMrz(['HOLA MUNDO', 'NADA QUE VER']), null);
assert.strictEqual(parseMrz([]), null);
assert.strictEqual(parseMrz([L[0]]), null);

// 8) el archivo del quiosco (static/js/cedula-readers.js) es EXACTAMENTE lo que genera scripts/build_cedula_readers.py desde la página de prueba, y se carga como script clásico
const { execFileSync } = require('child_process');
const built = execFileSync('python3', ['-c', "import sys; sys.path.insert(0, 'scripts'); import build_cedula_readers as b; sys.stdout.write(b.build())"], { cwd: path.join(__dirname, '..', '..'), encoding: 'utf8' });
const shipped = fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', 'cedula-readers.js'), 'utf8');
assert.strictEqual(shipped, built, 'static/js/cedula-readers.js quedó desactualizado: corre python scripts/build_cedula_readers.py');
const win = {}; new Function('window', shipped)(win);
assert.deepStrictEqual(Object.keys(win.CedulaReaders).sort(), ['CedulaScanner', 'MrzScanner', 'formatBirth', 'mrzStrong', 'parseCedula', 'parseMrz']);
assert.strictEqual(win.CedulaReaders.parseMrz(L).cedula, '52123456');
console.log('mrz_parser_check OK');
