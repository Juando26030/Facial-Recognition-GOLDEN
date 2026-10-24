// Comprobación de static/js/ql-usb.js (flujo de comandos de la Brother QL). Se corre con: node tests/js/ql_usb_check.js
const assert = require("assert");
const QL = require("../../static/js/ql-usb.js");

const W = QL.MEDIA[62].printable;               // 696
assert.strictEqual(W, 696);
assert.strictEqual(QL.mmToDots(25.4), 300);

function bitmap(h, dots) {                       // dots: [[x, y], ...]
  const b = new Uint8Array(W * h);
  dots.forEach(([x, y]) => { b[y * W + x] = 1; });
  return b;
}

// ---- estructura del trabajo (continua, 3 líneas)
const job = QL.buildJob({ bitmap: bitmap(3, [[0, 0], [695, 1], [100, 2]]), height: 3 });
assert.strictEqual(job.length, 200 + 2 + 4 + 4 + 13 + 4 + 4 + 4 + 5 + 2 + 3 * 93 + 1);
assert.ok(job.slice(0, 200).every((v) => v === 0), "invalidar: 200 bytes en cero");
let at = 200;
assert.deepStrictEqual([...job.slice(at, at + 2)], [0x1b, 0x40]); at += 2;                       // inicializar
assert.deepStrictEqual([...job.slice(at, at + 4)], [0x1b, 0x69, 0x61, 0x01]); at += 4;           // modo raster
assert.deepStrictEqual([...job.slice(at, at + 4)], [0x1b, 0x69, 0x21, 0x00]); at += 4;           // sin notificación
assert.deepStrictEqual([...job.slice(at, at + 13)], [0x1b, 0x69, 0x7a, 0x86, 0x0a, 62, 0, 3, 0, 0, 0, 0, 0]); at += 13;   // info: continua, 62 mm, 3 líneas
assert.deepStrictEqual([...job.slice(at, at + 4)], [0x1b, 0x69, 0x4d, 0x40]); at += 4;           // corte automático
assert.deepStrictEqual([...job.slice(at, at + 4)], [0x1b, 0x69, 0x41, 0x01]); at += 4;           // cortar cada 1 etiqueta
assert.deepStrictEqual([...job.slice(at, at + 4)], [0x1b, 0x69, 0x4b, 0x08]); at += 4;           // cortar al final
assert.deepStrictEqual([...job.slice(at, at + 5)], [0x1b, 0x69, 0x64, 35, 0]); at += 5;          // margen 35 puntos
assert.deepStrictEqual([...job.slice(at, at + 2)], [0x4d, 0x00]); at += 2;                       // sin compresión
for (let y = 0; y < 3; y++) {
  assert.deepStrictEqual([...job.slice(at, at + 3)], [0x67, 0x00, 90]);
  at += 93;
}
assert.strictEqual(job[job.length - 1], 0x1a);                                                   // imprimir y avanzar

// ---- posición de los puntos: margen de 12, MSB primero
const line = (n) => job.slice(200 + 2 + 4 + 4 + 13 + 4 + 4 + 4 + 5 + 2 + n * 93 + 3, 200 + 2 + 4 + 4 + 13 + 4 + 4 + 4 + 5 + 2 + n * 93 + 93);
assert.strictEqual(line(0)[1], 0x08);                       // x=0 → punto 12 → byte 1, bit 0x80>>4
assert.strictEqual(line(0).reduce((a, v) => a + (v ? 1 : 0), 0), 1);
assert.strictEqual(line(1)[(12 + 695) >> 3] & (0x80 >> ((12 + 695) & 7)), 0x80 >> ((12 + 695) & 7));
assert.strictEqual(line(2)[(12 + 100) >> 3] & (0x80 >> ((12 + 100) & 7)), 0x80 >> ((12 + 100) & 7));

// ---- espejo: el punto de la izquierda pasa a la derecha
const mir = QL.buildJob({ bitmap: bitmap(1, [[0, 0]]), height: 1, mirror: true });
const mline = mir.slice(mir.length - 1 - 90, mir.length - 1);
assert.strictEqual(mline[(12 + 695) >> 3] & (0x80 >> ((12 + 695) & 7)), 0x80 >> ((12 + 695) & 7));
assert.strictEqual(mline[1], 0);

// ---- troquelada y sin corte
const die = QL.buildJob({ bitmap: bitmap(2, []), height: 2, lengthMm: 100, autoCut: false });
assert.deepStrictEqual([...die.slice(210, 223)], [0x1b, 0x69, 0x7a, 0x8e, 0x0b, 62, 100, 2, 0, 0, 0, 0, 0]);
assert.deepStrictEqual([...die.slice(223, 227)], [0x1b, 0x69, 0x4d, 0x00]);
assert.deepStrictEqual([...die.slice(227, 231)], [0x1b, 0x69, 0x4b, 0x00]);
assert.deepStrictEqual([...die.slice(231, 236)], [0x1b, 0x69, 0x64, 0, 0]);                   // troquelada: sin margen de avance

// ---- líneas largas (más de 255): el contador es de 32 bits
const long = QL.buildJob({ bitmap: bitmap(1063, []), height: 1063 });
assert.deepStrictEqual([...long.slice(210 + 7, 210 + 11)], [1063 & 255, 1063 >> 8, 0, 0]);


// ---- margen de avance de las preferencias (1,5 mm = 18 puntos) y sin corte: no se manda «cortar cada 1»
const fed = QL.buildJob({ bitmap: bitmap(1, []), height: 1, feedDots: QL.mmToDots(1.5) });
assert.ok(fed.join(",").includes([0x1b, 0x69, 0x64, 18, 0].join(",")), "margen 18 puntos");
const nocut = QL.buildJob({ bitmap: bitmap(1, []), height: 1, autoCut: false });
assert.ok(!nocut.join(",").includes([0x1b, 0x69, 0x41, 0x01].join(",")), "sin corte no hay ESC i A");

// ---- preferencias del equipo: por defecto corte sí, margen 1,5 mm, alto = el de la plantilla; se guardan y se leen con las mismas claves
const mem = { d: {}, getItem(k) { return k in this.d ? this.d[k] : null; }, setItem(k, v) { this.d[k] = String(v); }, removeItem(k) { delete this.d[k]; } };
assert.deepStrictEqual(QL.readPrefs(mem), { cut: true, feedMm: 1.5, lengthMm: null, mirror: false, invert: false, tapeWidth: 62, tapeType: "continuous", rotation: "auto", crop: true, cropMarginMm: 3 });
QL.savePrefs(mem, { cut: false, feedMm: 2, lengthMm: 90, mirror: true, invert: true });
assert.deepStrictEqual(mem.d, { ql_cut: "0", ql_feed_mm: "2", ql_length_mm: "90", ql_mirror: "1", ql_invert: "1" });
assert.deepStrictEqual(QL.readPrefs(mem), { cut: false, feedMm: 2, lengthMm: 90, mirror: true, invert: true, tapeWidth: 62, tapeType: "continuous", rotation: "auto", crop: true, cropMarginMm: 3 });
QL.savePrefs(mem, { lengthMm: null, feedMm: "abc" });
assert.strictEqual(QL.readPrefs(mem).lengthMm, null);
assert.strictEqual(QL.readPrefs(mem).feedMm, 1.5);                                               // valor ilegible: el de por defecto
assert.deepStrictEqual(QL.readPrefs(null), QL.readPrefs({ getItem() { throw new Error("bloqueado"); } }));


// ---- valores por EVENTO con sobrescritura por EQUIPO: lo del equipo > lo del evento > de fábrica; «Restablecer» deja solo lo del evento
{
  const dev = { d: {}, getItem(k) { return k in this.d ? this.d[k] : null; }, setItem(k, v) { this.d[k] = String(v); }, removeItem(k) { delete this.d[k]; } };
  const evt = { cropMarginMm: 5, rotation: 270, feedMm: 2, cut: false, tapeType: "diecut", lengthMm: 80, tapeWidth: 50, crop: false };   // 50 mm NO existe en MEDIA: se ignora
  let r = QL.resolvePrefs(dev, evt);
  assert.deepStrictEqual(r.prefs, { cut: false, feedMm: 2, lengthMm: 80, mirror: false, invert: false, tapeWidth: 62, tapeType: "diecut", rotation: 270, crop: false, cropMarginMm: 5 });
  assert.strictEqual(r.source.tapeWidth, "defecto"); assert.strictEqual(r.source.cropMarginMm, "evento"); assert.strictEqual(r.source.mirror, "defecto");
  QL.savePrefs(dev, { cropMarginMm: 1, cut: true });
  r = QL.resolvePrefs(dev, evt);
  assert.strictEqual(r.prefs.cropMarginMm, 1); assert.strictEqual(r.source.cropMarginMm, "equipo"); assert.strictEqual(r.prefs.cut, true); assert.strictEqual(r.prefs.rotation, 270);
  assert.ok(/según equipo y evento/.test(QL.describePrefs(r.prefs, r.source)));
  QL.clearPrefs(dev);
  assert.deepStrictEqual(dev.d, {});
  r = QL.resolvePrefs(dev, evt);
  assert.strictEqual(r.prefs.cropMarginMm, 5); assert.strictEqual(r.source.cropMarginMm, "evento");
  const bad = QL.resolvePrefs({ getItem: () => "xx", setItem() {}, removeItem() {} }, { rotation: 45, feedMm: -3, tapeType: "raro" });
  assert.deepStrictEqual(bad.prefs, QL.PREF_DEFAULTS);                                                   // valores ilegibles: de fábrica
  assert.ok(/continua/.test(QL.describePrefs(QL.PREF_DEFAULTS, {}, { rotation: 90 })) && /62 mm/.test(QL.describePrefs(QL.PREF_DEFAULTS, {})));
}

// ---- cinta de 62 mm: 696 puntos = 58,92 mm imprimibles. Giro automático: el lado largo corre a lo largo de la cinta; más ancha que la cinta = AVISO (no encoger en silencio)
{
  const P = QL.PREF_DEFAULTS;
  assert.ok(Math.abs(QL.printableMm(62) - 58.9) < 0.1);
  let l = QL.layout(P, 62, 100);                                  // vertical 62×100: no gira
  assert.deepStrictEqual([l.rotation, l.acrossMm, l.alongMm, l.tooWide, l.scale], [0, 62, 100, true, QL.printableMm(62) / 62]);   // 62 mm de plantilla > 58,9 imprimibles: avisa y encoge
  l = QL.layout(P, 100, 55);                                      // horizontal 100×55: gira 90° → 55 a lo ancho, 100 a lo largo
  assert.deepStrictEqual([l.rotation, l.acrossMm, l.alongMm, l.tooWide, l.scale], [90, 55, 100, false, 1]);
  l = QL.layout(P, 120, 100);                                     // ancha en las dos orientaciones
  assert.strictEqual(l.tooWide, true); assert.ok(l.scale < 1);
  l = QL.layout(Object.assign({}, P, { rotation: 180 }), 100, 55);
  assert.deepStrictEqual([l.rotation, l.acrossMm], [180, 100]);   // forzado: se respeta aunque no quepa
  l = QL.layout(Object.assign({}, P, { rotation: 270 }), 55, 100);
  assert.deepStrictEqual([l.rotation, l.acrossMm, l.alongMm], [270, 100, 55]);
}

// ---- rotación del mapa de bits: 4 giros vuelven al original; cada punto cae donde debe
{
  const w = 4, h = 2;
  const bm = Uint8Array.from([1, 0, 0, 0, 0, 0, 0, 1]);          // (0,0) y (3,1)
  const at = (r, x, y) => r.bitmap[y * r.w + x];
  let r = QL.rotateBitmap(bm, w, h, 90);                          // 2×4: (0,0)→(1,0); (3,1)→(0,3)
  assert.deepStrictEqual([r.w, r.h, at(r, 1, 0), at(r, 0, 3)], [2, 4, 1, 1]);
  r = QL.rotateBitmap(bm, w, h, 270);                             // (0,0)→(0,3); (3,1)→(1,0)
  assert.deepStrictEqual([r.w, r.h, at(r, 0, 3), at(r, 1, 0)], [2, 4, 1, 1]);
  r = QL.rotateBitmap(bm, w, h, 180);
  assert.deepStrictEqual([r.w, r.h, at(r, 3, 1), at(r, 0, 0)], [4, 2, 1, 1]);
  let t = { bitmap: bm, w, h };
  for (let i = 0; i < 4; i++) t = QL.rotateBitmap(t.bitmap, t.w, t.h, 90);
  assert.deepStrictEqual([t.w, t.h, Array.from(t.bitmap)], [w, h, Array.from(bm)]);
  assert.deepStrictEqual(QL.rotateBitmap(bm, w, h, 0).bitmap, bm);
}

// ---- recortar al contenido: última fila con tinta + margen (3 mm = 35 puntos); sin tinta no recorta; nunca crece
{
  const W = QL.MEDIA[62].printable, H = 400, bm = new Uint8Array(W * H);
  bm[100 * W + 5] = 1;                                            // la última tinta está en la fila 100
  let c = QL.cropToContent(bm, W, H, QL.mmToDots(3));
  assert.strictEqual(c.h, 101 + 35); assert.strictEqual(c.bitmap.length, W * c.h);
  c = QL.cropToContent(bm, W, H, 0); assert.strictEqual(c.h, 101);
  c = QL.cropToContent(new Uint8Array(W * H), W, H, 35); assert.strictEqual(c.h, H);                    // vacía: se deja
  bm[399 * W] = 1; c = QL.cropToContent(bm, W, H, 35); assert.strictEqual(c.h, H);                       // tinta al final: no crece
  // pipeline completo: plantilla 100×55 mm horizontal → gira 90° (55 a lo ancho, 100 a lo largo), centrada y recortada
  const pw = Math.round(100 * 300 / 25.4), ph = Math.round(55 * 300 / 25.4), tpl = new Uint8Array(pw * ph);
  for (let x = 0; x < pw; x++) tpl[(ph - 1) * pw + x] = 1;       // una raya en el borde inferior de la plantilla
  const lay = QL.layout(QL.PREF_DEFAULTS, 100, 55);
  const job = QL.prepareBitmap(tpl, pw, ph, QL.PREF_DEFAULTS, lay);
  assert.strictEqual(job.rotation, 90); assert.strictEqual(job.bitmap.length, W * job.height);
  assert.ok(job.height <= pw && job.height >= pw - 40, "el largo es el lado largo de la plantilla (100 mm ≈ " + pw + " puntos), no un largo fijo: " + job.height);
  assert.strictEqual(QL.prepareBitmap(tpl, pw, ph, Object.assign({}, QL.PREF_DEFAULTS, { crop: false }), lay).height, pw);   // sin recorte: el largo completo
  const diecut = QL.prepareBitmap(tpl, pw, ph, Object.assign({}, QL.PREF_DEFAULTS, { tapeType: "diecut", lengthMm: 80 }), lay);
  assert.strictEqual(diecut.height, QL.mmToDots(80));                                                   // troquelada: largo fijo
  const inv = QL.prepareBitmap(tpl, pw, ph, Object.assign({}, QL.PREF_DEFAULTS, { invert: true, crop: false }), lay);
  assert.strictEqual(inv.bitmap[0], 1);                                                                 // lo blanco queda negro al invertir
}

// ---- errores
assert.throws(() => QL.buildJob({ bitmap: new Uint8Array(10), height: 1 }), /mapa de puntos/);
assert.throws(() => QL.buildJob({ bitmap: bitmap(1, []), height: 1, mediaWidthMm: 12 }), /no soportado/);

// ---- de píxeles a puntos
const rgba = new Uint8ClampedArray([0, 0, 0, 255, 255, 255, 255, 255, 10, 10, 10, 0, 200, 200, 200, 255]);
assert.deepStrictEqual([...QL.bitmapFromRGBA(rgba, 4, 1, 140, false)], [1, 0, 0, 0]);          // negro opaco = punto; blanco, transparente y gris claro = papel
assert.deepStrictEqual([...QL.bitmapFromRGBA(rgba, 4, 1, 140, true)], [0, 1, 1, 1]);

// ---- estado de la impresora
const st = new Uint8Array(32); st[0] = 0x80; st[10] = 62; st[11] = 0x0a; st[18] = 0;
assert.deepStrictEqual(QL.parseStatus(st), { mediaWidthMm: 62, mediaType: 0x0a, statusType: 0, errors: [], ready: true });
st[8] = 0x01; st[9] = 0x04;
assert.deepStrictEqual(QL.parseStatus(st).errors, ["sin etiquetas", "cubierta abierta"]);
assert.strictEqual(QL.parseStatus(new Uint8Array(5)), null);
assert.strictEqual(QL.supported(), false);                                                       // sin navegador no hay WebUSB: la página lo avisa

console.log("ql_usb_check OK");
