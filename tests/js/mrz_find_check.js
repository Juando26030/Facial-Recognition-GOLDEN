// Recorte automático de la cédula nueva (24-nov-2026): CedulaReaders.mrzFind ubica las 3 líneas en cualquier parte de la foto, las endereza y entrega solo esa zona.
// Imagen 100 % sintética (sin fuentes ni datos): «letras» = bloques con huecos al azar. Correr: node tests/js/mrz_find_check.js
const assert = require('assert'), fs = require('fs'), path = require('path');
const win = {}; new Function('window', fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', 'cedula-readers.js'), 'utf8'))(win);
const { mrzFind } = win.CedulaReaders;
assert.strictEqual(typeof mrzFind, 'function');

let seed = 7; const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
/** Foto W×H con una «cédula» (ancho frac·W, centro corrido dx,dy, girada ang°): fondo oscuro con vetas, tarjeta clara, texto suelto arriba y 3 líneas de 30 «letras» abajo. */
function scene(W, H, frac, dx, dy, ang) {
  const g = new Uint8Array(W * H), cw = frac * W, ch = cw * 54 / 85.6, cx = W / 2 + dx * W, cy = H / 2 + dy * H, a = ang * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
  const pitch = cw * (76.2 / 85.6) / 30, chH = pitch * 1.05, x0 = -cw / 2 + cw * .055, glyph = [];
  for (let l = 0; l < 3; l++) { glyph.push([]); for (let c = 0; c < 30; c++) { const m = []; for (let i = 0; i < 15; i++) m.push(rnd() < .62); glyph[l].push(m); } }
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const u = (x - cx) * ca + (y - cy) * sa, v = -(x - cx) * sa + (y - cy) * ca; let val = y % 37 < 2 ? 90 : 120;
    if (Math.abs(u) <= cw / 2 && Math.abs(v) <= ch / 2) {
      val = 228;
      for (let l = 0; l < 3; l++) {                                                     // las 3 líneas (paso entre líneas 4,23 mm sobre 54 mm de alto)
        const top = -ch / 2 + ch * (.72 + l * .0783), cu = (u - x0) / pitch, c = Math.floor(cu), fv = (v - top) / chH;
        if (c >= 0 && c < 30 && fv >= 0 && fv < 1) { const fx = cu - c; if (fx < .78 && glyph[l][c][Math.min(4, Math.floor(fv * 5)) * 3 + Math.min(2, Math.floor(fx / .78 * 3))]) val = 25; }
      }
      for (let l = 0; l < 5; l++) {                                                     // otros textos de la cédula (más cortos y de otro tamaño): no deben confundirse
        const top = -ch / 2 + ch * (.08 + l * .08), fv = (v - top) / (chH * .55), cu = (u - x0) / (pitch * .6), c = Math.floor(cu);
        if (fv >= 0 && fv < 1 && c >= 0 && c < 16 + l * 3 && cu - c < .7 && (c * 7 + l) % 5) val = 60;
      }
    }
    g[y * W + x] = val;
  }
  return g;
}
const cases = [['encuadrada', 1280, 720, .9, 0, 0, 0], ['pequeña y corrida', 1280, 720, .45, .15, -.1, 0], ['girada 12°', 1280, 720, .6, 0, 0, 12], ['girada -20°', 1280, 720, .55, .05, 0, -20], ['celular vertical', 720, 1280, .85, 0, .2, 3]];
for (const [name, W, H, frac, dx, dy, ang] of cases) {
  const f = mrzFind(scene(W, H, frac, dx, dy, ang), W, H);
  assert.ok(f, name + ': no ubicó las 3 líneas');
  assert.strictEqual(f.rot, 0, name); assert.ok(Math.abs(f.angle - ang) < 1.5, `${name}: ángulo ${f.angle}`);
  const I = f.info; assert.strictEqual(I.ok, true); assert.strictEqual(I.located, true); assert.strictEqual(I.bands.length, 3); assert.strictEqual(f.g.length, f.w * f.h);
  const mrzW = frac * W * (76.2 / 85.6), pitch = mrzW / 30;                             // el recorte es SOLO la zona de las 3 líneas, a la resolución de la foto
  assert.ok(Math.abs((I.x1 - I.x0) - mrzW) < mrzW * .06, `${name}: ancho ${I.x1 - I.x0} vs ${mrzW}`);
  assert.ok(f.w < mrzW * 1.2 && f.h < pitch * 1.05 * 7, `${name}: recorte ${f.w}×${f.h} demasiado grande`);
  const hs = I.bands.map((b) => b.y1 - b.y0 + 1), ps = [I.bands[1].y0 - I.bands[0].y0, I.bands[2].y0 - I.bands[1].y0];
  assert.ok(Math.max(...hs) / Math.min(...hs) < 1.3 && Math.max(...ps) / Math.min(...ps) < 1.2, name + ': bandas parejas');
  assert.ok(I.bands[0].y0 >= 0 && I.bands[2].y1 < f.h && I.bands[0].y1 < I.bands[1].y0 && I.bands[1].y1 < I.bands[2].y0, name + ': bandas en orden y sin pisarse');
  let ink = 0, n = 0; for (const b of I.bands) for (let y = b.y0; y <= b.y1; y++) for (let x = I.x0; x <= I.x1; x++) { n++; if (f.g[y * f.w + x] < 110) ink++; }
  assert.ok(ink / n > .2, `${name}: las bandas caen sobre la tinta (${(ink / n).toFixed(2)})`);
  const b = f.flip(); assert.strictEqual(b.rot, 2); assert.strictEqual(b.info.bands.length, 3); assert.ok(b.info.bands[0].y0 < b.info.bands[2].y0);
  assert.strictEqual(b.g[0], f.g[f.g.length - 1]);                                       // al revés = el mismo recorte girado 180°
}
{ const W = 1280, H = 720, s = scene(W, H, .6, 0, 0, 0), r = new Uint8Array(W * H);     // de lado (90°): se entrega rot = 1
  for (let y = 0; y < W; y++) for (let x = 0; x < H; x++) r[y * H + x] = s[x * W + (W - 1 - y)];
  const f = mrzFind(r, H, W); assert.ok(f && (f.rot === 1 || f.rot === 3) && f.info.bands.length === 3, 'de lado'); }
assert.strictEqual(mrzFind(new Uint8Array(640 * 360).fill(128), 640, 360), null);         // sin cédula: null (nada inventado)
{ const W = 1280, H = 720, g = new Uint8Array(W * H).fill(200); for (let y = 100; y < 600; y += 40) for (let x = 100; x < 1100; x++) if (y % 80 < 12 && x % 9 < 6) g[(y + (x % 3)) * W + x] = 30;
  const f = mrzFind(g, W, H); assert.ok(!f || f.info.bands.length === 3); }                // renglones cualesquiera: no revienta
console.log('mrz_find_check OK');
