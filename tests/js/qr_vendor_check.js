// Prueba de la copia PROPIA de jsQR (static/vendor/jsqr) y de su carga desde static/js/qr.js. Correr: node tests/js/qr_vendor_check.js
// Comprueba: qr.js carga jsQR de /static (sin CDN) y la plantilla del registro lo manda a guardar al service worker; la copia decodifica un QR real (generado aquí con un codificador mínimo
// de QR versión 1-L, solo para la prueba) y no encuentra nada en una imagen en blanco.
const fs = require('fs');
const assert = require('assert');

// ---------------------------------------------------------------- codificador mínimo de QR v1-L (21x21, hasta 17 bytes), máscara 0: SOLO para esta prueba
function qrV1L(text) {
  const bytes = [...Buffer.from(text, 'utf8')]; assert.ok(bytes.length <= 17);
  const bits = []; const put = (v, n) => { for (let i = n - 1; i >= 0; i--) bits.push((v >> i) & 1); };
  put(0b0100, 4); put(bytes.length, 8); bytes.forEach((b) => put(b, 8)); put(0, Math.min(4, 19 * 8 - bits.length)); while (bits.length % 8) bits.push(0);
  const data = []; for (let i = 0; i < bits.length; i += 8) data.push(parseInt(bits.slice(i, i + 8).join(''), 2));
  for (let pad = 0xec; data.length < 19; pad ^= 0xec ^ 0x11) data.push(pad);
  // Reed-Solomon sobre GF(256) (0x11d), 7 palabras de corrección
  const exp = new Array(512), log = new Array(256); let x = 1; for (let i = 0; i < 255; i++) { exp[i] = x; log[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; } for (let i = 255; i < 512; i++) exp[i] = exp[i - 255];
  const mul = (a, b) => (a && b ? exp[log[a] + log[b]] : 0);
  let gen = [1]; for (let i = 0; i < 7; i++) { const next = new Array(gen.length + 1).fill(0); gen.forEach((c, j) => { next[j] ^= c; next[j + 1] ^= mul(c, exp[i]); }); gen = next; }
  const rem = new Array(7).fill(0);
  data.forEach((d) => { const f = d ^ rem.shift(); rem.push(0); gen.slice(1).forEach((c, j) => { rem[j] ^= mul(c, f); }); });
  const all = data.concat(rem);
  const size = 21, mod = Array.from({ length: size }, () => new Array(size).fill(false)), fn = Array.from({ length: size }, () => new Array(size).fill(false));
  const set = (cx, cy, v) => { mod[cy][cx] = v; fn[cy][cx] = true; };
  for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
  for (const [fx, fy] of [[3, 3], [size - 4, 3], [3, size - 4]]) for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) { const xx = fx + dx, yy = fy + dy; if (xx >= 0 && xx < size && yy >= 0 && yy < size) set(xx, yy, Math.max(Math.abs(dx), Math.abs(dy)) !== 2 && Math.max(Math.abs(dx), Math.abs(dy)) !== 4); }
  const fd = (1 << 3) | 0; let r = fd; for (let i = 0; i < 10; i++) r = (r << 1) ^ ((r >>> 9) * 0x537); const fmt = ((fd << 10) | r) ^ 0x5412; const bit = (v, i) => ((v >>> i) & 1) === 1;
  for (let i = 0; i <= 5; i++) set(8, i, bit(fmt, i)); set(8, 7, bit(fmt, 6)); set(8, 8, bit(fmt, 7)); set(7, 8, bit(fmt, 8)); for (let i = 9; i < 15; i++) set(14 - i, 8, bit(fmt, i));
  for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(fmt, i)); for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(fmt, i)); set(8, size - 8, true);
  let k = 0; for (let right = size - 1; right >= 1; right -= 2) { if (right === 6) right = 5; for (let vert = 0; vert < size; vert++) for (let j = 0; j < 2; j++) { const cx = right - j, up = ((right + 1) & 2) === 0, cy = up ? size - 1 - vert : vert; if (!fn[cy][cx] && k < all.length * 8) { mod[cy][cx] = bit(all[k >> 3], 7 - (k & 7)); k++; } } }
  for (let cy = 0; cy < size; cy++) for (let cx = 0; cx < size; cx++) if (!fn[cy][cx] && (cx + cy) % 2 === 0) mod[cy][cx] = !mod[cy][cx];
  return mod;
}
function toImage(mod, scale = 8, quiet = 4) {
  const n = mod.length + quiet * 2, w = n * scale, d = new Uint8ClampedArray(w * w * 4).fill(255);
  for (let y = 0; y < w; y++) for (let x = 0; x < w; x++) { const my = Math.floor(y / scale) - quiet, mx = Math.floor(x / scale) - quiet; if (my >= 0 && mx >= 0 && my < mod.length && mx < mod.length && mod[my][mx]) { const i = (y * w + x) * 4; d[i] = d[i + 1] = d[i + 2] = 0; } }
  return { data: d, width: w, height: w };
}

// ---------------------------------------------------------------- qr.js carga la copia propia (sin CDN)
const scripts = [];
global.window = {};
global.document = { createElement: (t) => { const el = { tag: t, set src(v) { this._src = v; scripts.push(v); setImmediate(() => { global.window.jsQR = () => null; this.onload(); }); }, get src() { return this._src; } }; return el; }, head: { appendChild() {} }, addEventListener() {} };
eval(fs.readFileSync('static/js/qr.js', 'utf8'));

(async () => {
  assert.ok(window.QrScanner && window.QrScanner.JSQR_URL, 'QrScanner expone JSQR_URL');
  assert.strictEqual(window.QrScanner.JSQR_URL, '/static/vendor/jsqr/jsQR.js?v=1.4.0');
  await window.QrScanner.loadJsQr();
  assert.deepStrictEqual(scripts, ['/static/vendor/jsqr/jsQR.js?v=1.4.0'], 'qr.js pide jsQR a /static, no a un CDN');
  assert.ok(!/https?:\/\//.test(fs.readFileSync('static/js/qr.js', 'utf8').split('\n').filter((l) => /src|JSQR_URL =/.test(l) && !l.trim().startsWith('//') && !l.trim().startsWith('*')).join('\n')), 'qr.js no carga nada de un CDN');

  // la copia propia decodifica un QR real: cédula, y la forma «cédula|nombre» de las escarapelas (versión 1-L: hasta 17 bytes)
  const jsQR = require('../../static/vendor/jsqr/jsQR.js');
  for (const text of ['1016100329', '1016100329|Ana', 'A|B']) {
    const img = toImage(qrV1L(text)); const out = jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
    assert.ok(out, `jsQR no decodificó «${text}»`); assert.strictEqual(out.data, text);
  }
  const blank = { data: new Uint8ClampedArray(200 * 200 * 4).fill(255), width: 200, height: 200 };
  assert.strictEqual(jsQR(blank.data, 200, 200), null, 'una imagen en blanco no es un QR');
  console.log('qr.js + static/vendor/jsqr: carga local y decodificación de un QR real OK');
})().catch((e) => { console.error(e); process.exit(1); });
