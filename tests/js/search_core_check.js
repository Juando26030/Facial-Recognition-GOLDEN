// Prueba del núcleo puro del buscador único (static/js/search-core.js). Correr: node tests/js/search_core_check.js
const assert = require('assert');
const SC = require('../../static/js/search-core.js');
const { classifyQuery: cq, matchPerson: mp } = SC;

const juan = { id: '1016100329', first_name: 'Juan David', last_name: 'Ramírez Juzga', entity: 'Compañía Ñañez S.A.S.' };
const maria = { id: '52000111', first_name: 'María José', last_name: 'Gómez', entity: 'Acme' };
const pasaporte = { id: 'AB123456', first_name: 'Ana', last_name: 'Smith', entity: '' };
const sin = (p, q, o) => assert.strictEqual(mp(p, q, o).coincide, false, `no debía coincidir: ${JSON.stringify(q)}`);
const con = (p, q, motivo, o) => { const r = mp(p, q, o); assert.ok(r.coincide, `debía coincidir: ${JSON.stringify(q)}`); assert.strictEqual(r.motivo, motivo); };

// Clasificación
assert.strictEqual(cq('').kind, 'vacio');
assert.strictEqual(cq('   \n ').kind, 'vacio');
assert.strictEqual(cq(null).kind, 'vacio');
assert.strictEqual(cq('1016100329').kind, 'cedula');
assert.strictEqual(cq('1.016.100.329').cedula, '1016100329');
assert.strictEqual(cq('1 016 100-329').cedula, '1016100329');
assert.strictEqual(cq('1234').kind, 'texto');                                   // 4 dígitos: no es cédula
assert.strictEqual(cq('Juan').kind, 'texto');
assert.strictEqual(cq('1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206').kind, 'lector');
assert.strictEqual(cq('1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206').cedula, '1016100329');
assert.strictEqual(cq('0001016100329').kind, 'lector');                          // ceros a la izquierda: lo entrega el lector
assert.strictEqual(cq('0001016100329').cedula, '1016100329');
assert.strictEqual(cq('1016100329\n').kind, 'cedula');                           // el Enter del lector al final no cambia la cédula
assert.strictEqual(cq('1016100329|Juan David|Ramirez').kind, 'qr');
assert.strictEqual(cq('Juan|1016100329|Ramirez').cedula, '1016100329');
assert.strictEqual(cq('  JOSÉ   María ').normalized, 'jose maria');
assert.deepStrictEqual(cq('  JOSÉ   María ').words, ['jose', 'maria']);

// Cédula: EXACTA (D2)
con(juan, '1016100329', 'Cédula exacta');
con(juan, '1.016.100.329', 'Cédula exacta');
con(juan, ' 1016100329 ', 'Cédula exacta');
sin(juan, '1016100');                                                            // parcial (7 dígitos): NO
sin(juan, '16100329');                                                           // subcadena: NO
sin(juan, '10161003290');
sin(juan, '1016100328');
sin(juan, '12345');
sin(juan, '123');                                                                // corto: texto, no coincide con nada
con(pasaporte, 'ab-123456', 'Cédula exacta');                                    // documento con letras: igual, exacto
sin(pasaporte, '123456');
sin(pasaporte, 'ab123');

// Lector: ceros, CSV y QR
con(juan, '0001016100329', 'Código del lector');
con(juan, '1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206', 'Código del lector');
con(juan, '1016100329|Juan David|Ramirez Juzga', 'Código del lector');
sin(maria, '1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206');                // el nombre del código NO hace coincidir a otra persona
sin(juan, '101610,A,B,C,D,1999');                                                // cédula parcial dentro del lector: NO

// Nombre y empresa: prefijo de palabra, tildes y mayúsculas
con(juan, 'juan', 'Nombre');
con(juan, 'JUAN DA', 'Nombre');
con(juan, 'ramirez', 'Nombre');                                                  // sin tilde encuentra «Ramírez»
con(juan, 'RAMÍREZ juzga', 'Nombre');
con(juan, 'david juzga', 'Nombre');                                              // cualquier orden
con(maria, 'maria jose', 'Nombre');                                              // nombre compuesto
con(maria, '  María   José  ', 'Nombre');                                        // espacios múltiples
con(maria, 'jose', 'Nombre');
sin(maria, 'ose');                                                               // no es prefijo de palabra
sin(maria, 'maria maria');                                                       // no reutiliza la misma palabra
sin(juan, 'juan perez');
con(juan, 'nanez', 'Empresa');                                                   // «Ñañez» se encuentra sin la eñe
con(juan, 'compania', 'Empresa');
con(juan, 'compañía ñañez', 'Empresa');
con(maria, 'acme', 'Empresa');
con({ id: '9', first_name: 'Acme', last_name: 'Pérez', entity: 'Acme Ltda' }, 'acme', 'Nombre y empresa');
sin(pasaporte, 'acme');
sin({ id: '9', first_name: 'X' }, 'acme');                                       // sin entidad: no revienta
sin({ id: null }, 'x');

// Vacíos
sin(juan, '');
sin(juan, '   ');
sin(juan, null);
sin(juan, undefined);
assert.deepStrictEqual(mp(null, 'x'), { coincide: false, motivo: '' });

// Aceptar una consulta ya clasificada
con(juan, cq('1016100329'), 'Cédula exacta');

// Copia local (sin cédula ni entidad): cédula por huella EXACTA, nombre por prefijo
const local = { __local: true, __h: 'abc123', id: 'abc123', first_name: 'María José', last_name: 'Gómez' };
con(local, '1016100329', 'Cédula exacta', { hash: 'abc123' });
sin(local, '1016100329', { hash: 'zzz' });
sin(local, '1016100329');                                                        // sin huella calculada todavía: no coincide
con(local, 'maria', 'Nombre');
sin(local, 'acme');                                                              // la copia vieja no trae empresa

// Rendimiento: 10.000 personas por tecla < 50 ms. Las claves de cada persona se calculan UNA vez (prepare, al cargar el directorio); la tecla solo compara.
const N = 10000;
const gente = Array.from({ length: N }, (_, i) => ({ id: String(1000000000 + i), first_name: i === 4321 ? 'María José' : 'Persona' + i, last_name: 'Gómez', entity: i % 2 ? 'Compañía Ñañez' : 'Otra' }));
SC.prepare(gente);
const qMaria = cq('maria jose'), qCed = cq('1000004321'), qEmp = cq('compania nanez');     // la consulta se clasifica UNA vez por tecla
let t0 = process.hrtime.bigint();
const hallados = gente.filter((p) => mp(p, qMaria).coincide);
let ms = Number(process.hrtime.bigint() - t0) / 1e6;
assert.strictEqual(hallados.length, 1);
assert.ok(ms < 50, `10.000 personas, una búsqueda: ${ms.toFixed(1)} ms`);
t0 = process.hrtime.bigint();
const hCed = gente.filter((p) => mp(p, qCed).coincide);
const hEmp = gente.filter((p) => mp(p, qEmp).coincide);
ms = Number(process.hrtime.bigint() - t0) / 1e6;
assert.strictEqual(hCed.length, 1);
assert.strictEqual(hEmp.length, N / 2);
assert.ok(ms < 50, `dos búsquedas en caliente: ${ms.toFixed(1)} ms`);

console.log('search_core_check OK');
