// Problema C (29-oct-2026): la MISMA etiqueta por los dos caminos (USB del celular y ventana de Chrome del computador). Mide y reporta, en mm, la trama final de cada camino (ancho, margen
// superior/inferior/laterales, largo y giro) con la plantilla vertical y la horizontal, y comprueba que lo que sí se puede igualar por lógica (largo máximo 96 mm, escala, márgenes de la trama)
// coincida. Lo que depende del hardware (margen de avance de la QL, origen lateral del controlador de Windows) se imprime aparte: lo decide la prueba física de docs/HANDOFF_IMPRESION_COMPARTIDA_29OCT.md.
// Se corre con: node tests/js/label_paths_check.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const QL = require("../../static/js/ql-usb.js");
global.QLUsb = QL;
class Canvas {
  constructor() { this.width = 0; this.height = 0; this.rgba = null; }
  getContext() {
    const self = this;
    return {
      set fillStyle(v) { this._f = v; },
      fillRect() { self.rgba = new Uint8ClampedArray(self.width * self.height * 4).fill(255); },
      drawImage(shot, dx, dy, w, h) { for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const sx = Math.floor(x * shot.width / w), sy = Math.floor(y * shot.height / h), i = (y * w + x) * 4, j = (sy * shot.width + sx) * 4; for (let k = 0; k < 4; k++) self.rgba[i + k] = shot.rgba[j + k]; } },
      getImageData() { return { data: self.rgba }; }, createImageData(w, h) { return { data: new Uint8ClampedArray(w * h * 4) }; }, putImageData() {},
    };
  }
  toDataURL() { return "data:image/png;base64,AAA"; }
}
global.window = global;
global.document = { createElement: () => new Canvas() };
const LC = require("../../static/js/label-compose.js");
const DPM = 300 / 25.4;
const html = fs.readFileSync(path.resolve(__dirname, "../../templates/badge_print.html"), "utf8");
const chromeConst = /const PAGE_W = 62, PAGE_LEFT_MM = 0\.5, PAGE_H = 99\.8, MAX_IMG_H = (\d+);/.exec(html);
assert.ok(chromeConst, "las constantes inamovibles de la ventana de impresión siguen en badge_print.html");
const CHROME = { PAGE_W: 62, LEFT: 0.5, PAGE_H: 99.8, MAX: Number(chromeConst[1]) };
assert.strictEqual(LC.MAX_IMG_MM, CHROME.MAX, "el largo máximo del USB es el MISMO que el de la ventana de impresión (parámetro inamovible)");

function shotOf(tplW, tplH, ink) {
  const w = Math.round(tplW * DPM), h = Math.round(tplH * DPM), rgba = new Uint8ClampedArray(w * h * 4).fill(255);
  for (let y = Math.round(ink.y * DPM); y < Math.round((ink.y + ink.h) * DPM); y++) for (let x = Math.round(ink.x * DPM); x < Math.round((ink.x + ink.w) * DPM); x++) { const i = (y * w + x) * 4; rgba[i] = rgba[i + 1] = rgba[i + 2] = 0; }
  return { width: w, height: h, rgba };
}
function bbox(bitmap, W, H) {                                             // filas y columnas con tinta
  let top = H, bottom = -1, left = W, right = -1;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (bitmap[y * W + x]) { if (y < top) top = y; if (y > bottom) bottom = y; if (x < left) left = x; if (x > right) right = x; }
  return { top, bottom, left, right };
}
const mm = (d) => Math.round(d / DPM * 100) / 100;

// geometría que sale por el USB (celular): la trama que se manda; el margen de avance (feedMm) lo agrega la impresora arriba y abajo
function usbGeometry(out, p) {
  const f = LC.fitToPaper(out), b = bbox(f.bitmap, out.tapeDots, f.height);
  return { camino: "USB (celular)", escala: Math.round(f.scale * 1000) / 1000, anchoVentanaMm: mm(out.tapeDots), largoTramaMm: mm(f.height), tintaArribaMm: mm(b.top), tintaAbajoMm: mm(f.height - 1 - b.bottom),
    tintaIzqMm: mm(b.left), tintaDerMm: mm(out.tapeDots - 1 - b.right), extraAvanceArribaAbajoMm: p.feedMm, giro: out.layout.rotation };
}
// geometría de la ventana de Chrome (computador): fórmulas de templates/badge_print.html (inamovibles); la imagen va a 0,5 mm del borde izquierdo de la página de 62 mm
function chromeGeometry(out) {
  const spec = LC.pageSpec(out), fit = Math.min(1, CHROME.MAX / spec.imageHeightMm), imgW = spec.imageWidthMm * fit, imgH = spec.imageHeightMm * fit, left = CHROME.LEFT + (spec.imageWidthMm - imgW) / 2;
  const b = bbox(out.bitmap, out.tapeDots, out.height), k = fit / DPM;
  return { camino: "Chrome (computador)", escala: Math.round(fit * 1000) / 1000, anchoVentanaMm: Math.round(imgW * 100) / 100, largoTramaMm: Math.round(imgH * 100) / 100, tintaArribaMm: Math.round(b.top * k * 100) / 100,
    tintaAbajoMm: Math.round((out.height - 1 - b.bottom) * k * 100) / 100, tintaIzqMm: Math.round(((spec.imageWidthMm - imgW) / 2 + b.left * k) * 100) / 100, tintaDerMm: Math.round(((spec.imageWidthMm - imgW) / 2 + (out.tapeDots - 1 - b.right) * k) * 100) / 100,
    extraAvanceArribaAbajoMm: 0, giro: out.layout.rotation, origenIzqPaginaMm: Math.round(left * 100) / 100, paginaMm: [CHROME.PAGE_W, CHROME.PAGE_H] };
}

const prefs = (o) => Object.assign({}, QL.PREF_DEFAULTS, o || {});
const CASES = [
  ["vertical 62×100", 62, 100, { x: 8, y: 30, w: 40, h: 25 }],
  ["horizontal 100×62", 100, 62, { x: 30, y: 10, w: 40, h: 30 }],
  ["horizontal 105×62 (más larga que el papel)", 105.4, 62, { x: 33, y: 10, w: 40, h: 30 }],
  ["vertical alta 62×130", 62, 130, { x: 8, y: 30, w: 40, h: 60 }],
];
const report = [];
for (const [name, w, h, ink] of CASES) {
  const p = prefs();
  const out = LC.composeBitmap(shotOf(w, h, ink), w, h, p);                              // la MISMA trama compartida para los dos caminos
  const usb = usbGeometry(out, p), chrome = chromeGeometry(out);
  report.push({ plantilla: name, usb, chrome });
  // lo que SÍ es lógica compartida y debe coincidir: escala, largo de la trama, márgenes de la trama arriba/abajo y giro
  assert.ok(Math.abs(usb.escala - chrome.escala) < 0.002, `${name}: misma escala (${usb.escala} vs ${chrome.escala})`);
  assert.ok(usb.largoTramaMm <= CHROME.MAX + 0.1 && chrome.largoTramaMm <= CHROME.MAX + 0.1, `${name}: ninguno pasa de ${CHROME.MAX} mm`);
  assert.ok(Math.abs(usb.largoTramaMm - chrome.largoTramaMm) < 0.15, `${name}: mismo largo de trama (${usb.largoTramaMm} vs ${chrome.largoTramaMm})`);
  assert.ok(Math.abs(usb.tintaArribaMm - chrome.tintaArribaMm) < 0.15 && Math.abs(usb.tintaAbajoMm - chrome.tintaAbajoMm) < 0.15, `${name}: mismos márgenes arriba y abajo de la trama`);
  assert.ok(Math.abs(usb.tintaIzqMm - chrome.tintaIzqMm) < 0.2 && Math.abs(usb.tintaDerMm - chrome.tintaDerMm) < 0.2, `${name}: mismos márgenes laterales de la trama`);
  assert.strictEqual(usb.giro, chrome.giro, `${name}: mismo giro`);
}
// tamaño relativo (29-oct-2026): medida en la Brother, la escarapela del USB salía ~8 % más grande que la de Chrome; el USB aplica USB_SCALE al bitmap y la tinta mide exactamente esa fracción
{
  assert.ok(LC.USB_SCALE > 0.85 && LC.USB_SCALE < 1, "USB_SCALE es la perilla de calibración: " + LC.USB_SCALE);
  const p = prefs(), out = LC.composeBitmap(shotOf(62, 100, { x: 8, y: 30, w: 40, h: 25 }), 62, 100, p), full = LC.fitToPaper(out), small = LC.fitToPaper(out, LC.USB_SCALE);
  const a = bbox(full.bitmap, out.tapeDots, full.height), b = bbox(small.bitmap, out.tapeDots, small.height);
  const wr = (b.right - b.left + 1) / (a.right - a.left + 1), hr = (b.bottom - b.top + 1) / (a.bottom - a.top + 1);
  assert.ok(Math.abs(wr - LC.USB_SCALE) < 0.02 && Math.abs(hr - LC.USB_SCALE) < 0.02 && Math.abs(small.height / full.height - LC.USB_SCALE) < 0.01, "la tinta y el largo del USB miden USB_SCALE: " + wr + " " + hr);
  assert.ok(Math.abs((b.left) - (out.tapeDots - 1 - b.right)) <= (Math.abs(a.left - (out.tapeDots - 1 - a.right)) + 2), "sigue centrada a lo ancho");
}
// avance de la QL (29-oct-2026): se descuenta del blanco del bitmap, así bitmap + avance = largo y márgenes del bitmap de Chrome; nunca se come tinta
for (const [name, w, h, ink] of CASES.slice(0, 2)) {
  const p = prefs(), out = LC.composeBitmap(shotOf(w, h, ink), w, h, p), f = LC.fitToPaper(out, LC.USB_SCALE), feed = QL.mmToDots(p.feedMm), t = LC.trimBlankEnds(f, feed, feed);
  const a = bbox(f.bitmap, out.tapeDots, f.height), b = bbox(t.bitmap, out.tapeDots, t.height);
  assert.strictEqual(t.height, f.height - Math.min(feed, a.top) - Math.min(feed, f.height - 1 - a.bottom), name + ": se quitó el avance al inicio y al final");
  assert.strictEqual(b.top, a.top - Math.min(feed, a.top), name + ": la tinta no se tocó (misma tinta, menos blanco)");
  assert.strictEqual(b.bottom - b.top, a.bottom - a.top, name + ": mismo alto de tinta");
}
// medido por Juan (29-oct, 3.ª ronda): horizontal de 105 mm → Chrome 9,0 cm, el USB debe quedar en 9,0 cm (antes 9,5-9,6); vertical → el USB conserva USB_SCALE
{
  const p = prefs(), land = LC.composeBitmap(shotOf(105.4, 62, { x: 33, y: 10, w: 40, h: 30 }), 105.4, 62, p), u = LC.usbFit(land);
  assert.ok(Math.abs(u.height / DPM - 96 * LC.USB_SCALE_LANDSCAPE) < 0.3 && u.height / DPM > 89 && u.height / DPM < 90.6, "horizontal: el USB mide ~9,0 cm: " + (u.height / DPM));
  const vert = LC.composeBitmap(shotOf(62, 100, { x: 8, y: 30, w: 40, h: 25 }), 62, 100, p), v = LC.usbFit(vert);
  assert.ok(Math.abs(v.height / vert.height - LC.USB_SCALE) < 0.01, "vertical: escala USB_SCALE");
  assert.ok(LC.USB_LEAD_TRIM_MM > 0 && LC.USB_LEAD_TRIM_MM <= 2, "vertical: ~1 mm menos de margen arriba");
}
// una etiqueta de hasta 96 mm NO cambia con el tope (las de 100 mm de plantilla miden 95,08): el trabajo USB es byte a byte el de siempre
{
  const p = prefs(), out = LC.composeBitmap(shotOf(100, 62, { x: 30, y: 10, w: 40, h: 30 }), 100, 62, p), f = LC.fitToPaper(out);
  assert.ok(f.scale === 1 && f.bitmap === out.bitmap && f.height === out.height, "hasta 96 mm: sin cambios");
}
// tope: la etiqueta de 130 mm se reduce proporcionalmente y queda centrada a lo ancho (como en Chrome)
{
  const p = prefs(), out = LC.composeBitmap(shotOf(62, 130, { x: 0, y: 0, w: 62, h: 130 }), 62, 130, p), f = LC.fitToPaper(out), b = bbox(f.bitmap, out.tapeDots, f.height);
  assert.ok(f.height <= Math.round(CHROME.MAX * DPM) + 1 && Math.abs((b.left) - (out.tapeDots - 1 - b.right)) <= 1, "reducida y centrada a lo ancho");
}
console.log(JSON.stringify(report, null, 1));
console.log("DIFERENCIAS QUE NO SE IGUALAN POR LÓGICA (las decide la prueba física): (1) margen de avance de la QL (feedMm, hoy 1,5 mm arriba y abajo SOLO en USB); (2) origen lateral: en USB la ventana imprimible de 58,93 mm va centrada en la cinta de 62 mm por el cabezal (1,5 mm a cada lado); en Chrome la imagen va a 0,5 mm del borde izquierdo de la página de 62 mm y el controlador de Windows decide el resto.");
console.log("label_paths_check OK");
