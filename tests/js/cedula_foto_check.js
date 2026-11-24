// Cédula por FOTO con guía (static/js/cedula-foto.js, 24-nov-2026). Correr: node tests/js/cedula_foto_check.js
// Prueba la lógica pura: recuadro guía, paso del recuadro del video a la foto de alta resolución, opciones de takePhoto, votación de lecturas de la cédula nueva
// (la cédula siempre con dígitos de control; los nombres solo confirmados), reintentos sobre la misma foto y la respuesta del respaldo en el servidor. Datos sintéticos.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const F = require('../../static/js/cedula-foto.js');
const ROOT = path.join(__dirname, '..', '..');
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-6, `${msg}: ${a} ≠ ${b}`);

// 1) recuadro guía: igual que el de los lectores en vivo (proporción 4.8 vieja / 4.6 nueva), centrado y dentro del video
{
  const g = F.guideRect(1920, 1080, 0, 0, 4.8, 0.92);
  near(g.w, 1920 * 0.92, 'ancho limitado por el ancho'); near(g.w / g.h, 4.8, 'proporción'); near(g.x + g.w / 2, 960, 'centro x'); near(g.y + g.h / 2, 540, 'centro y');
  const v = F.guideRect(1080, 1920, 1080, 1920, 4.6, 0.94);           // celular vertical
  assert.ok(v.x >= 0 && v.x + v.w <= 1080 && v.y >= 0 && v.y + v.h <= 1920); near(v.w / v.h, 4.6, 'proporción vertical');
  const cov = F.guideRect(1920, 1080, 400, 400, 4.8, 0.92);           // elemento cuadrado con object-fit: cover → solo la franja visible del centro
  assert.ok(cov.x >= (1920 - 1080) / 2 - 1e-6 && cov.x + cov.w <= (1920 + 1080) / 2 + 1e-6, 'el recuadro queda en la parte visible');
}

// 2) del video a la foto fija: sensor 4:3 y video 16:9 recortado al centro; mismo tamaño (cuadro del video); orientación distinta → null (se usa la foto completa)
{
  const g = { x: 100, y: 200, w: 960, h: 200 };
  const same = F.photoRect(g, 1920, 1080, 1920, 1080); assert.deepStrictEqual(same, { x: 100, y: 200, w: 960, h: 200 });
  const p = F.photoRect(g, 1920, 1080, 4032, 3024), k = 4032 / 1920, oy = (3024 - 1080 * k) / 2;
  near(p.x, 100 * k, 'x'); near(p.y, oy + 200 * k, 'y con el margen de arriba del sensor'); near(p.w, 960 * k, 'w'); near(p.h, 200 * k, 'h');
  assert.strictEqual(F.photoRect(g, 1080, 1920, 4032, 3024), null);
  assert.strictEqual(F.photoRect(g, 0, 0, 4032, 3024), null);
  const e = F.expandRect({ x: 10, y: 10, w: 100, h: 20 }, 0.5, 2, 120, 60);     // se agranda y se recorta a la imagen
  assert.deepStrictEqual(e, { x: 0, y: 0, w: 120, h: 60 });
}

// 3) takePhoto a la máxima resolución (respetando el paso del sensor y el tope de 4600 px)
assert.deepStrictEqual(F.stillOptions({ imageWidth: { min: 640, max: 4032, step: 16 }, imageHeight: { min: 480, max: 3024, step: 16 } }), { imageWidth: 4032, imageHeight: 3024 });
{ const o = F.stillOptions({ imageWidth: { min: 1, max: 8000, step: 1 }, imageHeight: { min: 1, max: 6000, step: 1 } }); assert.strictEqual(o.imageWidth, 4600); assert.strictEqual(o.imageHeight, 3450); }
assert.deepStrictEqual(F.stillOptions(null), {});
assert.deepStrictEqual(F.stillOptions({ imageWidth: {}, imageHeight: {} }), {});

// 4) votación de la cédula nueva: los nombres (sin dígito de control) se aceptan con 2 lecturas iguales o confianza alta; si no, solo la cédula
{
  const P = (ced, n1, extra) => ({ cedula: ced, nombre1: n1, nombre2: '', apellido1: 'PEREZ', apellido2: '', nacimiento: '19850101', ok: true, ...extra });
  const strong = (p) => !!p && p.ok;
  assert.strictEqual(F.pickMrz([], strong, true), null);
  assert.strictEqual(F.pickMrz([{ parsed: P('52123456', 'ANA', { ok: false }), conf: [99, 99, 99] }], strong, true), null, 'sin dígitos de control en regla nunca se entrega');
  let r = F.pickMrz([{ parsed: P('52123456', 'ANA'), conf: [70, 60, 70] }, { parsed: P('52123456', 'ANA'), conf: [65, 60, 70] }], strong, false);
  assert.strictEqual(r.nombres, true); assert.strictEqual(r.datos.nombre1, 'ANA'); assert.strictEqual(r.datos.verificada, true);
  r = F.pickMrz([{ parsed: P('52123456', 'ANA'), conf: [90, 85, 81] }], strong, false); assert.strictEqual(r.nombres, true, 'una lectura muy segura basta');
  const dudosa = [{ parsed: P('52123456', 'ANA'), conf: [70, 60, 70] }, { parsed: P('52123456', 'AWA'), conf: [70, 60, 70] }];
  assert.strictEqual(F.pickMrz(dudosa, strong, false), null, 'mientras queden intentos no se decide');
  r = F.pickMrz(dudosa, strong, true);
  assert.deepStrictEqual([r.datos.cedula, r.datos.nombre1, r.datos.apellido1, r.datos.nombresSinConfirmar, r.nombres], ['52123456', '', '', true, false], 'al final: la cédula validada, sin nombres dudosos');
  assert.strictEqual(F.pickMrz([{ parsed: P('52123456', 'ANA'), conf: [1, 1, 1] }, { parsed: P('52123457', 'ANA'), conf: [1, 1, 1] }], strong, true), null, 'dos cédulas distintas: nada');
  assert.strictEqual(F.pickMrz([{ parsed: P('52123456', 'ANA'), conf: null }], strong, true).nombres, false, 'lectura de la foto completa (sin confianza por línea)');
}

// 5) reintentos sobre la MISMA foto: 3 tamaños de letra; al revés (180°) solo si derecho no aparece la estructura; sin 3 líneas no se insiste
(async () => {
  const strong = (p) => !!p && p.ok;
  const parse = (lines) => (lines[0] === 'BIEN' ? { cedula: '1', nombre1: 'A', nombre2: '', apellido1: 'B', apellido2: '', nacimiento: '', ok: true } : null);
  let calls = [];
  let reads = await F.readMrzCrop(async (flip, attempt) => { calls.push([flip, attempt]); return { texts: [{ text: flip ? 'BIEN' : 'MAL', conf: 50 }, { text: '', conf: 50 }, { text: '', conf: 50 }] }; }, parse, strong, []);
  assert.deepStrictEqual(calls, [[false, 0], [false, 1], [false, 2], [true, 0], [true, 1]], 'derecho 3 veces, luego al revés hasta confirmar con 2 lecturas');
  assert.ok(F.pickMrz(reads, strong, false));
  calls = [];
  await F.readMrzCrop(async (flip, attempt) => { calls.push([flip, attempt]); return {}; }, parse, strong, []);
  assert.deepStrictEqual(calls, [[false, 0]], 'sin 3 líneas en el recorte: no se gira ni se repite');
  calls = [];
  await F.readMrzCrop(async (flip, attempt) => { calls.push([flip, attempt]); return { texts: [{ text: 'BIEN', conf: 50 }, { text: '', conf: 50 }, { text: '', conf: 50 }] }; }, parse, strong, [], () => calls.length < 1);
  assert.deepStrictEqual(calls, [[false, 0]], 'al cerrar la ventana se deja de leer');

  // 6) respaldo del servidor → mismo formato que los lectores
  assert.deepStrictEqual(F.fromServer({ id: '52123456', first_name: 'ANA MARIA', last_name: 'PEREZ GOMEZ' }),
    { cedula: '52123456', nombre1: 'ANA MARIA', nombre2: '', apellido1: 'PEREZ GOMEZ', apellido2: '', nacimiento: '', verificada: true, origen: 'servidor' });
  assert.strictEqual(F.fromServer({}), null); assert.strictEqual(F.fromServer(null), null);

  // 7) mensajes pedidos y piezas del componente
  assert.strictEqual(F.MSG.processing, 'Procesando la foto…');
  assert.strictEqual(F.MSG.fail, 'No se pudo leer la cédula: acérquela, evite reflejos y tome otra foto.');
  const src = fs.readFileSync(path.join(ROOT, 'static/js/cedula-foto.js'), 'utf8');
  assert.ok(src.includes('takePhoto(') && src.includes('getPhotoCapabilities') && src.includes("imageOrientation: 'from-image'"), 'foto fija de alta resolución');
  assert.ok(src.includes('getTracks().forEach((t) => t.stop())'), 'libera la cámara');
  assert.ok(!/\b(alert|confirm|prompt)\(/.test(src) && !/console\.(log|info)\(/.test(src) && !/localStorage|indexedDB/.test(src), 'sin diálogos nativos, sin registros ni almacenamiento de la foto');
  // el componente usa métodos de los lectores generados: si se regeneran con otro nombre, esto avisa
  const readers = fs.readFileSync(path.join(ROOT, 'static/js/cedula-readers.js'), 'utf8');
  for (const m of ['async scanImage(file, { budgetMs = 15000 } = {})', 'async _read(gray, W, H, opts = {})', 'async scanImage(file) {', 'onUnknown']) assert.ok(readers.includes(m), 'cedula-readers.js ya no tiene ' + m);
  // 24-nov-2026 (rapidez): carrera navegador/servidor de la cédula nueva → gana la PRIMERA lectura no vacía; si todas fallan, null
  {
    const api = require(path.join(ROOT, 'static/js/cedula-foto.js'));
    const later = (v, ms) => new Promise((ok) => setTimeout(() => ok(v), ms));
    assert.deepStrictEqual(await api.firstFound([later(null, 5), later({ cedula: '1' }, 20), later({ cedula: '2' }, 40)]), { cedula: '1' });
    assert.deepStrictEqual(await api.firstFound([later({ cedula: '2' }, 30), Promise.reject(new Error('x')), later(null, 1)]), { cedula: '2' });
    assert.strictEqual(await api.firstFound([later(null, 1), Promise.reject(new Error('x'))]), null);
    assert.strictEqual(await api.firstFound([]), null);
    const src = fs.readFileSync(path.join(ROOT, 'static/js/cedula-foto.js'), 'utf8');
    assert.ok(src.includes('HD_SHORT_SIDE') && src.includes('SERVER_HEAD_START_MS') && src.includes('OLD_BUDGET_MS'), 'atajos de rapidez');
    const qr = fs.readFileSync(path.join(ROOT, 'static/js/qr.js'), 'utf8');
    const stage = qr.slice(qr.indexOf('gw-cam__stage'), qr.indexOf("+ '</div>'"));
    assert.ok(stage.includes('gw-cam__shoot'), '«Tomar foto» va dentro del recuadro de la cámara (encima del video)');
    assert.ok(qr.includes("classList.toggle('gw-cam--photo'"), 'modo cédula: todo en una pantalla');
  }
  console.log('cedula_foto_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
