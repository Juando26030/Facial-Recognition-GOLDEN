/* Lector ZXing en un hilo aparte (Web Worker): decodificar un cuadro grande en el hilo de la página congelaba el video de la cámara (~5 cuadros por segundo). Aquí el video sigue fluido.
   Mensajes: {id, width, height, buffer (RGBA), options} -> {id, results:[{text, bytes, format, isValid}]} | {id, error}. Los archivos del lector son copia propia (static/vendor/zxing/). */
'use strict';
let ready = false;
function init() {
  if (ready) return;
  importScripts('/static/vendor/zxing/zxing-reader.js');
  self.ZXingWASM.setZXingModuleOverrides({ locateFile: (path, prefix) => (/\.wasm$/.test(path) ? '/static/vendor/zxing/zxing_reader.wasm' : prefix + path) });
  ready = true;
}
self.onmessage = async (e) => {
  const m = e.data || {};
  try {
    init();
    const out = await self.ZXingWASM.readBarcodes({ data: new Uint8ClampedArray(m.buffer), width: m.width, height: m.height, colorSpace: 'srgb' }, m.options || {});
    self.postMessage({ id: m.id, results: (out || []).map((r) => ({ text: r.text, bytes: r.bytes, format: r.format, isValid: r.isValid })) });
  } catch (err) {
    self.postMessage({ id: m.id, error: String((err && err.message) || err) });
  }
};
