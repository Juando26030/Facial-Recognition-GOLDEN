// La etiqueta compuesta es UNA sola para el USB y para la ventana de impresión del navegador (27-oct-2026): mismo bitmap, mismas dimensiones; cambiar el recorte, el margen o el giro cambia las dos igual.
// Se corre con: node tests/js/label_compose_check.js
const assert = require("assert");
const path = require("path");
const QL = require("../../static/js/ql-usb.js");
global.QLUsb = QL;

// Un «canvas» mínimo: lo dibujado se guarda como RGBA y drawImage copia (vecino más cercano) de la captura de la plantilla.
class Canvas {
  constructor() { this.width = 0; this.height = 0; this.rgba = null; }
  getContext() {
    const self = this;
    return {
      set fillStyle(v) { this._f = v; },
      fillRect() { self.rgba = new Uint8ClampedArray(self.width * self.height * 4).fill(255); },
      drawImage(shot, dx, dy, w, h) { for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const sx = Math.floor(x * shot.width / w), sy = Math.floor(y * shot.height / h), i = (y * w + x) * 4, j = (sy * shot.width + sx) * 4; for (let k = 0; k < 4; k++) self.rgba[i + k] = shot.rgba[j + k]; } },
      getImageData(x, y, w, h) { return { data: self.rgba }; },
      createImageData(w, h) { return { data: new Uint8ClampedArray(w * h * 4) }; }, putImageData() {},
    };
  }
  toDataURL() { return "data:image/png;base64,AAA"; }
}
global.window = global;                                         // el módulo toma QLUsb y document de `window`
global.document = { createElement: () => new Canvas() };
const LC = require("../../static/js/label-compose.js");
const DPM = 300 / 25.4;

// La «plantilla dibujada»: tinta en un rectángulo (no centrado a propósito) de la plantilla de tplW × tplH mm, a 300 dpi.
function shotOf(tplW, tplH, ink) {
  const w = Math.round(tplW * DPM), h = Math.round(tplH * DPM), rgba = new Uint8ClampedArray(w * h * 4).fill(255);
  for (let y = Math.round(ink.y * DPM); y < Math.round((ink.y + ink.h) * DPM); y++) for (let x = Math.round(ink.x * DPM); x < Math.round((ink.x + ink.w) * DPM); x++) { const i = (y * w + x) * 4; rgba[i] = rgba[i + 1] = rgba[i + 2] = 0; }
  return { width: w, height: h, rgba };
}
const PLANTILLAS = [["vertical 62×100", 62, 100, { x: 8, y: 20, w: 40, h: 30 }], ["horizontal 100×62", 100, 62, { x: 10, y: 8, w: 60, h: 20 }]];
const prefs = (o) => Object.assign({}, QL.PREF_DEFAULTS, o || {});

for (const [name, w, h, ink] of PLANTILLAS) {
  const shot = shotOf(w, h, ink);
  const bytesOf = (p) => {                                         // lo que va a la impresora por USB (del MISMO bitmap compuesto)
    const out = LC.composeBitmap(shot, w, h, p);
    const job = QL.buildJob({ bitmap: out.bitmap, height: out.height, mediaWidthMm: p.tapeWidth, mirror: p.mirror, autoCut: p.cut, feedDots: QL.mmToDots(p.feedMm), lengthMm: p.tapeType === "diecut" ? p.lengthMm : undefined });
    return { out, job };
  };
  const heights = {};
  const sideways = w > h;                                          // horizontal: el blanco del final iguala al del inicio (28-oct-2026), así que el margen solo cuenta si pasa de ese blanco
  const bigMargin = sideways ? 20 : 8;
  for (const [label, o] of [["con recorte, margen 3 mm", { crop: true, cropMarginMm: 3 }], ["con recorte, margen 8 mm", { crop: true, cropMarginMm: bigMargin }], ["sin recorte", { crop: false }]]) {
    const p = prefs(o);
    const usb = bytesOf(p), page = LC.composeBitmap(shot, w, h, p), again = LC.composeBitmap(shot, w, h, p);
    assert.deepStrictEqual(Array.from(page.bitmap), Array.from(usb.out.bitmap), `${name} (${label}): mismos píxeles`);
    assert.strictEqual(page.height, usb.out.height, `${name} (${label}): misma altura`); assert.strictEqual(page.tapeDots, usb.out.tapeDots);
    assert.deepStrictEqual(Array.from(again.bitmap), Array.from(page.bitmap), "determinista");
    const spec = LC.pageSpec(page);
    assert.ok(Math.abs(spec.pageWidthMm - page.tapeDots / DPM) < 0.01 && Math.abs(spec.pageHeightMm - page.height / DPM) < 0.01, `${name} (${label}): la hoja mide los puntos × 25,4 / 300 mm`);
    assert.ok(spec.imageWidthMm === spec.pageWidthMm && spec.imageHeightMm === spec.pageHeightMm && /margin: 0/.test(spec.pageCss) && spec.pageCss.includes(`size: ${spec.pageWidthMm}mm ${spec.pageHeightMm}mm`), "@page del tamaño de la imagen, sin márgenes ni escalado");
    assert.ok(Math.abs(spec.pageWidthMm - 58.93) < 0.01, "ancho útil de la cinta: 58,93 mm");
    assert.ok(Math.abs(usb.out.height / DPM - spec.pageHeightMm) < 0.01, "USB y página miden lo mismo (mm)");
    heights[label] = page.height;
  }
  assert.ok(heights["con recorte, margen 8 mm"] > heights["con recorte, margen 3 mm"], `${name}: cambiar el margen cambia la salida`);
  assert.ok(heights["sin recorte"] >= heights["con recorte, margen 3 mm"], `${name}: sin recorte nunca es más corta`);
  // el margen cambia las DOS salidas igual: la altura del trabajo USB y la de la hoja crecen lo mismo
  const a = bytesOf(prefs({ crop: true, cropMarginMm: 3 })), b2 = bytesOf(prefs({ crop: true, cropMarginMm: bigMargin }));
  assert.ok(Math.abs((LC.pageSpec(b2.out).pageHeightMm - LC.pageSpec(a.out).pageHeightMm) - (b2.out.height - a.out.height) / DPM) < 0.02, `${name}: la hoja y el trabajo USB crecen lo mismo con el margen`);
  assert.ok(b2.job.length > a.job.length, `${name}: el trabajo USB también crece con el margen`);
}

// la horizontal gira 90° (a lo largo de la cinta) y nada sale cortado: el ancho de la hoja es el de la cinta y el largo, el de la plantilla
{
  const shot = shotOf(100, 62, { x: 0, y: 0, w: 100, h: 62 });        // tinta en toda la plantilla
  const out = LC.composeBitmap(shot, 100, 62, prefs({ crop: false }));
  assert.strictEqual(out.layout.rotation, 90, "la horizontal gira");
  assert.ok(Math.abs(LC.pageSpec(out).pageHeightMm - 100 * out.layout.scale) < 0.5, "el largo es el lado largo de la plantilla (con la escala por ser la plantilla de 62 mm y la cinta de 58,9 mm)");
}
console.log("label_compose_check OK");

// HORIZONTAL con recorte: el texto queda CENTRADO a lo largo de la tira (blanco al final = blanco al inicio); la VERTICAL no cambia (el final lleva solo el margen). Bug de producción 28-oct-2026.
{
  const blankRows = (out) => { let top = 0, bottom = 0, W = out.tapeDots, H = out.height; const row = (y) => { for (let x = 0; x < W; x++) if (out.bitmap[y * W + x]) return true; return false; };
    while (top < H && !row(top)) top++; while (bottom < H && !row(H - 1 - bottom)) bottom++; return { top, bottom, H }; };
  const hz = LC.composeBitmap(shotOf(100, 62, { x: 30, y: 10, w: 40, h: 30 }), 100, 62, prefs({ crop: true, cropMarginMm: 3 }));     // texto en el medio de los 100 mm
  const b = blankRows(hz);
  assert.ok(Math.abs(b.top - b.bottom) <= 1, "horizontal: el blanco del final iguala al del inicio (" + JSON.stringify(b) + ")");
  assert.ok(b.top > 3 * DPM + 5, "horizontal: el blanco inicial (el diseño) se conserva");
  const vt = LC.composeBitmap(shotOf(62, 100, { x: 8, y: 30, w: 40, h: 20 }), 62, 100, prefs({ crop: true, cropMarginMm: 3 }));
  const v = blankRows(vt);
  assert.ok(Math.abs(v.bottom - Math.round(3 * DPM)) <= 1 && v.top > v.bottom + 20, "vertical: sin cambios (final = solo el margen) " + JSON.stringify(v));
  const small = LC.composeBitmap(shotOf(100, 62, { x: 2, y: 10, w: 40, h: 30 }), 100, 62, prefs({ crop: true, cropMarginMm: 3 }));     // blanco inicial menor que el margen: manda el margen
  assert.ok(Math.abs(blankRows(small).bottom - Math.round(3 * DPM)) <= 1 || blankRows(small).bottom >= Math.round(3 * DPM) - 1, "horizontal con poco blanco inicial: al menos el margen");
  const big = LC.composeBitmap(shotOf(100, 62, { x: 70, y: 10, w: 30, h: 30 }), 100, 62, prefs({ crop: true, cropMarginMm: 3 }));       // tinta al final de la plantilla: nunca más larga que la plantilla
  assert.ok(big.height <= Math.round(100 * DPM * 0.95) + 2, "horizontal: nunca más larga que la plantilla");
}
console.log("label_compose_horizontal_centrada OK");
