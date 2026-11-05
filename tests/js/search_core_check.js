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
assert.strictEqual(cq('1234').kind, 'cedula');                                  // 3-4 dígitos: cédula PARCIAL (predictiva con red)
assert.strictEqual(cq('1234').completa, false);
assert.strictEqual(cq('12').kind, 'texto');                                     // 2 dígitos: texto
assert.strictEqual(cq('10161').completa, true);
assert.strictEqual(cq('1016100329,A,B,C,D,1').completa, true);
assert.strictEqual(cq('Juan').completa, false);
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
con(juan, '1016100', 'Cédula (empieza por 1016100…)');                           // con red: predictivo por prefijo
con(juan, '101', 'Cédula (empieza por 101…)');
con(juan, '1.016', 'Cédula (empieza por 1016…)');
con(juan, '16100329', 'Cédula (contiene 16100329)');                              // los últimos dígitos / un tramo: SÍ, después de las que empiezan igual
sin(juan, '1016100328');                                                           // un dígito distinto: NO
sin(juan, '10161003290');                                                        // más larga que la cédula: NO
sin(juan, '1016100328');
sin(juan, '12345');
sin(juan, '123');
sin(juan, '12');                                                                 // 2 dígitos: texto, no coincide con nada
con(pasaporte, 'ab-123456', 'Cédula exacta');                                    // documento con letras: igual, exacto
sin(pasaporte, '123456');
sin(pasaporte, 'ab123');

// Predictivo y orden: exacta > prefijo > nombre/empresa
const gp = [{ id: '10161003291', first_name: 'A', last_name: 'B' }, { id: '1016100329', first_name: 'C', last_name: 'D' }, { id: '1016200000', first_name: 'E', last_name: 'F' }, { id: '5', first_name: 'G', last_name: 'H', entity: '1016 SA' }];
SC.prepare(gp);
let r3 = SC.search(gp, '101');
assert.deepStrictEqual(r3.map((x) => x.persona.id), ['10161003291', '1016100329', '1016200000']);
assert.ok(r3.every((x) => x.orden === 1));
r3 = SC.search(gp, '1016100329');
assert.deepStrictEqual(r3.map((x) => [x.persona.id, x.motivo]), [['1016100329', 'Cédula exacta'], ['10161003291', 'Cédula (empieza por 1016100329…)']]);
assert.deepStrictEqual(SC.search(gp, '1016').map((x) => x.persona.id), ['10161003291', '1016100329', '1016200000']);

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
assert.strictEqual(mp(null, 'x').coincide, false);

// Aceptar una consulta ya clasificada
con(juan, cq('1016100329'), 'Cédula exacta');

// Copia local (sin cédula ni entidad): cédula por huella EXACTA, nombre por prefijo
const local = { __local: true, __h: 'abc123', id: 'abc123', first_name: 'María José', last_name: 'Gómez' };
con(local, '1016100329', 'Cédula exacta', { hash: 'abc123' });
sin(local, '1016100329', { hash: 'zzz' });
sin(local, '101', { hash: 'abc123' });                                          // sin cédula en claro, un parcial no puede coincidir (la huella no admite prefijos)
sin(local, '1016', { hash: 'abc123' });
// Con la cédula en claro (la entrega el llamador por parámetro) la fila local también es predictiva
con(local, '101', 'Cédula (empieza por 101…)', { cedulaPlain: '1016100329' });
con(local, '1016100329', 'Cédula exacta', { cedulaPlain: '1016100329' });
con(local, '1.016.100', 'Cédula (empieza por 1016100…)', { cedulaPlain: '1016100329' });
sin(local, '102', { cedulaPlain: '1016100329' });
con(local, '16100', 'Cédula (contiene 16100)', { cedulaPlain: '1016100329' });      // con la cédula en claro también se busca por un tramo
con(local, '101', 'Cédula (empieza por 101…)', { cedulaOf: () => '1016100329' });
assert.strictEqual(local.id_plain, undefined);                                   // el módulo no deja cédulas en la persona
const pl = ['1016100329', '10161003291', '1016200000'];
const locales = pl.map((c, i) => ({ __local: true, __h: 'h' + i, first_name: 'L' + i }));
const orden = SC.search(locales.slice().reverse(), '1016100329', { cedulaOf: (p) => pl[locales.indexOf(p)] });
assert.deepStrictEqual(orden.map((x) => x.motivo), ['Cédula exacta', 'Cédula (empieza por 1016100329…)']);
sin(local, '1016100329');                                                        // sin huella calculada todavía: no coincide
con(local, 'maria', 'Nombre');
sin(local, 'acme');                                                              // la copia vieja no trae empresa

// Rendimiento: 10.000 personas por tecla < 50 ms. Las claves de cada persona se calculan UNA vez (prepare, al cargar el directorio); la tecla solo compara.
const N = 10000;
const gente = Array.from({ length: N }, (_, i) => ({ id: String(1000000000 + i), first_name: i === 4321 ? 'María José' : 'Persona' + i, last_name: 'Gómez', entity: i % 2 ? 'Compañía Ñañez' : 'Otra' }));
SC.prepare(gente);
const locales10k = gente.map((p, i) => ({ __local: true, __h: 'h' + i, first_name: p.first_name, last_name: p.last_name }));
SC.prepare(locales10k);
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
t0 = process.hrtime.bigint();
const hLoc = SC.search(locales10k, '1000004', { cedulaOf: (p) => gente[Number(p.__h.slice(1))].id });
ms = Number(process.hrtime.bigint() - t0) / 1e6;
assert.strictEqual(hLoc.length, 1000);                                           // 1000004000..1000004999
assert.ok(ms < 50, `10.000 filas locales con cédula en claro: ${ms.toFixed(1)} ms`);
assert.ok(ms < 50, `dos búsquedas en caliente: ${ms.toFixed(1)} ms`);

// Plan 5 («No eliminar repetidos»): el serial «123456-2» conserva el guion y NO choca con «1234562»
const rep = { id: '123456-2', first_name: 'Ana', last_name: 'Repetida', entity: '' };
const pegada = { id: '1234562', first_name: 'Beto', last_name: 'Otro', entity: '' };
assert.strictEqual(SC.cedulaKey('123456-2'), '123456-2');
assert.notStrictEqual(SC.cedulaKey('123456-2'), SC.cedulaKey('1234562'));
assert.strictEqual(SC.cedulaKey('1.016.100-329'), '1016100329');                  // guion con 3 dígitos detrás: separador de siempre
assert.strictEqual(SC.cedulaKey('ab123456-12'), 'ab123456-12');                   // pasaporte con serial
assert.strictEqual(cq('123456-2').cedula, '123456-2');
assert.ok(mp(rep, '123456-2').coincide, 'el serial se encuentra por su cédula con guion');
assert.strictEqual(mp(pegada, '123456-2').coincide, false, '«1234562» no es «123456-2»');
assert.strictEqual(mp(rep, '1234562').coincide, false, '«123456-2» no es «1234562»');
assert.ok(mp(rep, '123456').coincide, 'la cédula sin serial encuentra también a sus repetidas (predictivo por prefijo)');
// Pedido de Juan David (5-nov-2026): la búsqueda de nombres perdona errores de tipeo (como el buscador de tres cajas) y la cédula también se busca por sus últimos dígitos
con(juan, 'jaun david', 'Nombre');                                               // letras cambiadas de lugar
con(juan, 'yuan', 'Nombre');                                                     // una letra distinta
con(juan, 'david ramirez', 'Nombre');                                            // sin tilde, en el orden que sea
con(juan, 'jaun daivd ramirez', 'Nombre');                                       // dos palabras con error
con(maria, 'maira', 'Nombre');                                                   // transposición, 5 letras
con(juan, 'compania nanez', 'Empresa');
sin(juan, 'pedro');
sin(juan, 'jon');                                                                // menos de 4 letras: sin tolerancia
sin(pasaporte, '123457');                                                        // los números no se «corrigen»
const exactos = SC.search([{ id: '1', first_name: 'Yuan', last_name: 'Li', entity: '' }, { id: '2', first_name: 'Juan', last_name: 'Pérez', entity: '' }], 'juan');
assert.deepStrictEqual(exactos.map((r) => r.persona.id), ['2', '1'], 'lo escrito bien sale antes que lo corregido');
const porCedula = SC.search([{ id: '9990123', first_name: 'A', last_name: 'B', entity: '' }, { id: '1237777', first_name: 'C', last_name: 'D', entity: '' }, { id: '123', first_name: 'E', last_name: 'F', entity: '' }], '123');
assert.deepStrictEqual(porCedula.map((r) => r.persona.id), ['123', '1237777', '9990123'], 'exacta, luego empieza por, luego contiene');
console.log('search_core_check OK');
