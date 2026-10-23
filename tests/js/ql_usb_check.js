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
assert.deepStrictEqual(QL.readPrefs(mem), { cut: true, feedMm: 1.5, lengthMm: null, mirror: false, invert: false });
QL.savePrefs(mem, { cut: false, feedMm: 2, lengthMm: 90, mirror: true, invert: true });
assert.deepStrictEqual(mem.d, { ql_cut: "0", ql_feed_mm: "2", ql_length_mm: "90", ql_mirror: "1", ql_invert: "1" });
assert.deepStrictEqual(QL.readPrefs(mem), { cut: false, feedMm: 2, lengthMm: 90, mirror: true, invert: true });
QL.savePrefs(mem, { lengthMm: null, feedMm: "abc" });
assert.strictEqual(QL.readPrefs(mem).lengthMm, null);
assert.strictEqual(QL.readPrefs(mem).feedMm, 1.5);                                               // valor ilegible: el de por defecto
assert.deepStrictEqual(QL.readPrefs(null), QL.readPrefs({ getItem() { throw new Error("bloqueado"); } }));

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
