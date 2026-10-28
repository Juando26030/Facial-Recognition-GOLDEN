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

// ---- posición de los puntos (24-oct-2026, prueba física en la QL-800): el PRIMER punto de la línea queda en el borde DERECHO de la etiqueta, así que la columna IZQUIERDA del
//      dibujo va al ÚLTIMO punto imprimible (12 + 695). MSB primero, margen de 12 a cada lado.
const bitOn = (row, dot) => (row[dot >> 3] & (0x80 >> (dot & 7))) !== 0;
const line = (n) => job.slice(200 + 2 + 4 + 4 + 13 + 4 + 4 + 4 + 5 + 2 + n * 93 + 3, 200 + 2 + 4 + 4 + 13 + 4 + 4 + 4 + 5 + 2 + n * 93 + 93);
assert.ok(bitOn(line(0), 12 + 695), "x=0 (izquierda del dibujo) → último punto");
assert.strictEqual(line(0)[1], 0, "ya no va al primer punto (eso salía en espejo)");
assert.strictEqual(line(0).reduce((a, v) => a + (v ? 1 : 0), 0), 1);
assert.ok(bitOn(line(1), 12), "x=695 (derecha del dibujo) → primer punto");
assert.ok(bitOn(line(2), 12 + 695 - 100), "x=100 → punto 12 + 595");

// ---- impresora simulada (lo que vio Juan en la QL-800: el primer punto de la línea sale a la DERECHA de la etiqueta): la etiqueta de prueba (barra a la izquierda) en vertical y en
//      horizontal, normal y con espejo. El espejo SOLO refleja a lo ancho de la cinta; el giro (0°/90°) es otra cosa y no cambia con el espejo.
{
  const LD = 720;
  const decode = (jobBytes, h) => {                       // de las líneas raster a la etiqueta física (fila y, columna física de izquierda a derecha)
    const out = []; const start = jobBytes.length - 1 - h * 93;
    for (let y = 0; y < h; y++) { const row = jobBytes.slice(start + y * 93 + 3, start + y * 93 + 93); const phys = new Uint8Array(LD); for (let d = 0; d < LD; d++) if (row[d >> 3] & (0x80 >> (d & 7))) phys[LD - 1 - d] = 1; out.push(phys); }
    return out;
  };
  const label = (w, h) => { const b = new Uint8Array(w * h); for (let y = 0; y < h; y++) for (let x = 0; x < 20; x++) b[y * w + x] = 1; for (let x = w - 40; x < w - 30; x++) b[(h >> 1) * w + x] = 1; return b; };
  const run = (w, h, rotation, mirror) => {
    const p = Object.assign({}, QL.PREF_DEFAULTS, { rotation, crop: false, mirror });
    const lay = QL.layout(p, w / QL.mmToDots(1), h / QL.mmToDots(1));
    const prep = QL.prepareBitmap(label(w, h), w, h, p, lay);
    return decode(QL.buildJob({ bitmap: prep.bitmap, height: prep.height, mirror }), prep.height);
  };
  // vertical (sin giro): la barra sale a la IZQUIERDA sin espejo y a la DERECHA con espejo
  const vn = run(600, 300, 0, false), vm = run(600, 300, 0, true);
  const firstInk = (row) => row.indexOf(1), lastInk = (row) => row.lastIndexOf(1);
  assert.ok(firstInk(vn[0]) < 360 && lastInk(vn[0]) < 360, "vertical normal: barra a la izquierda");
  assert.ok(firstInk(vm[0]) > 360, "vertical con espejo: barra a la derecha");
  // horizontal (giro 90°) y cualquier giro: con espejo es EXACTAMENTE el reflejo a lo ancho de la normal (el espejo no toca el giro)
  for (const rot of [90, 270]) {
    const hn = run(600, 300, rot, false), hm = run(600, 300, rot, true);
    assert.strictEqual(hn.length, hm.length);
    for (let y = 0; y < hn.length; y++) for (let x = 0; x < LD; x++) assert.strictEqual(hm[y][x], hn[y][LD - 1 - x], `giro ${rot}: fila ${y}`);
  }
}

// ---- espejo: SOLO con «Espejo» la etiqueta sale reflejada (la columna izquierda va al primer punto)
const mir = QL.buildJob({ bitmap: bitmap(1, [[0, 0]]), height: 1, mirror: true });
const mline = mir.slice(mir.length - 1 - 90, mir.length - 1);
assert.ok(bitOn(mline, 12)); assert.ok(!bitOn(mline, 12 + 695));
// la etiqueta de prueba (barra negra a la izquierda): sin espejo la barra ocupa el FINAL de cada línea; con espejo, el principio
{
  const bar = new Uint8Array(W * 2); for (let y = 0; y < 2; y++) for (let x = 0; x < 30; x++) bar[y * W + x] = 1;
  const n = QL.buildJob({ bitmap: bar, height: 2 }), m = QL.buildJob({ bitmap: bar, height: 2, mirror: true });
  const ln = n.slice(n.length - 1 - 93 + 3, n.length - 1), lm = m.slice(m.length - 1 - 93 + 3, m.length - 1);
  assert.ok(bitOn(ln, 12 + 695) && bitOn(ln, 12 + 666) && !bitOn(ln, 12 + 665) && !bitOn(ln, 12));
  assert.ok(bitOn(lm, 12) && bitOn(lm, 12 + 29) && !bitOn(lm, 12 + 30) && !bitOn(lm, 12 + 695));
}

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
assert.deepStrictEqual(mem.d, { ql_cut: "0", ql_feed_mm: "2", ql_length_mm: "90", ql_mirror_v2: "1", ql_invert: "1" });       // «Espejo» con la clave NUEVA (significado corregido)
assert.deepStrictEqual(QL.readPrefs(mem), { cut: false, feedMm: 2, lengthMm: 90, mirror: true, invert: true, tapeWidth: 62, tapeType: "continuous", rotation: "auto", crop: true, cropMarginMm: 3 });
QL.savePrefs(mem, { lengthMm: null, feedMm: "abc" });
assert.strictEqual(QL.readPrefs(mem).lengthMm, null);
assert.strictEqual(QL.readPrefs(mem).feedMm, 1.5);                                               // valor ilegible: el de por defecto
assert.deepStrictEqual(QL.readPrefs(null), QL.readPrefs({ getItem() { throw new Error("bloqueado"); } }));

// ---- «Espejo» guardado con el significado VIEJO (ql_mirror, antes del 24-oct-2026) no se hereda: se ignora y dropLegacyPrefs lo borra
{
  const old = { d: { ql_mirror: "1", ql_cut: "0" }, getItem(k) { return k in this.d ? this.d[k] : null; }, setItem(k, v) { this.d[k] = String(v); }, removeItem(k) { delete this.d[k]; } };
  assert.strictEqual(QL.readPrefs(old).mirror, false, "el espejo viejo (que compensaba el error) ya no aplica");
  assert.strictEqual(QL.resolvePrefs(old, {}).source.mirror, "defecto");
  assert.strictEqual(QL.readPrefs(old).cut, false, "lo demás del equipo se conserva");
  QL.dropLegacyPrefs(old);
  assert.deepStrictEqual(old.d, { ql_cut: "0" });
  old.d.ql_mirror_v2 = "1";
  assert.strictEqual(QL.readPrefs(old).mirror, true, "el espejo nuevo sí se respeta");
  old.d.ql_mirror = "0"; QL.clearPrefs(old); assert.deepStrictEqual(old.d, {});
  QL.dropLegacyPrefs(null);                                                                        // sin almacenamiento: no falla
}


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
