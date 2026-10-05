/* Impresión directa en una Brother QL (QL-800 y hermanas) desde el navegador por USB (WebUSB), sin app nativa ni diálogo de impresión.
 *
 * Dos partes:
 *   1) `QLUsb.buildJob(...)`: PURA (sin navegador). Convierte un mapa de puntos en el flujo de comandos de «raster» de la serie QL (invalidar, inicializar, modo raster, información de
 *      impresión, corte, márgenes, líneas de 90 bytes, imprimir). Se prueba en tests/js/ql_usb_check.js.
 *   2) `QLUsb.connect()` / `sendJob()` / `readStatus()`: la parte de WebUSB (Chrome de Android y de escritorio, solo HTTPS). Pide permiso UNA vez (requestDevice, con un gesto del
 *      usuario); después `getDevices()` reconoce la impresora sin volver a preguntar.
 *
 * Datos de la QL-800 (300 dpi): cinta continua de 62 mm = 696 puntos imprimibles en una línea de 720 (12 de margen a cada lado). 1 mm ≈ 11,81 puntos.
 * NO verificado con una impresora real todavía (primera prueba pendiente): por eso la página tiene «espejo» e «invertir» y una etiqueta de prueba asimétrica.
 */
(function (root) {
  "use strict";

  var LINE_BYTES = 90;            // 720 puntos por línea en la serie QL de 62 mm
  var LINE_DOTS = LINE_BYTES * 8;
  var BROTHER_VENDOR = 0x04f9;
  var DOTS_PER_MM = 300 / 25.4;
  var MEDIA = {                    // ancho imprimible (puntos) por ancho de cinta en mm. Solo la de 62 mm está documentada para este montaje; otras se agregan al probarlas con la cinta puesta
    62: { printable: 696, margin: 12 }
  };

  function mmToDots(mm) { return Math.round(mm * DOTS_PER_MM); }

  /* bitmap: Uint8Array (alto × ancho) con 1 = negro; ancho = puntos imprimibles de la cinta. Devuelve la fila de 90 bytes (MSB = primer punto). */
  function packRow(bitmap, width, y, margin, mirror) {
    var row = new Uint8Array(LINE_BYTES);
    for (var x = 0; x < width; x++) {
      var v = bitmap[y * width + (mirror ? width - 1 - x : x)];
      if (v) {
        var dot = margin + x;
        if (dot >= 0 && dot < LINE_DOTS) row[dot >> 3] |= 0x80 >> (dot & 7);
      }
    }
    return row;
  }

  function buildJob(opts) {
    var mediaWidth = opts.mediaWidthMm || 62;
    var media = MEDIA[mediaWidth];
    if (!media) throw new Error("Ancho de cinta no soportado: " + mediaWidth + " mm");
    var width = media.printable, bitmap = opts.bitmap, height = opts.height;
    if (!(bitmap instanceof Uint8Array) || bitmap.length !== width * height) throw new Error("El mapa de puntos debe medir " + width + " × " + height);
    var continuous = opts.lengthMm == null || opts.lengthMm === 0;
    var parts = [];
    function push(bytes) { parts.push(Uint8Array.from(bytes)); }

    parts.push(new Uint8Array(200));                                       // invalidar: 200 bytes en cero (descarta cualquier comando a medias)
    push([0x1b, 0x40]);                                                    // inicializar
    push([0x1b, 0x69, 0x61, 0x01]);                                        // modo raster
    push([0x1b, 0x69, 0x21, 0x00]);                                        // sin notificación automática de estado
    var lines = height;
    push([0x1b, 0x69, 0x7a,                                                // información de impresión
      continuous ? 0x86 : 0x8e,                                            // válidos: recuperación (0x80), tipo (0x02), ancho (0x04) y, si hay, largo (0x08)
      continuous ? 0x0a : 0x0b,                                            // 0x0A continua, 0x0B troquelada
      mediaWidth, continuous ? 0 : (opts.lengthMm & 0xff),
      lines & 0xff, (lines >> 8) & 0xff, (lines >> 16) & 0xff, (lines >> 24) & 0xff,
      0x00, 0x00]);
    push([0x1b, 0x69, 0x4d, opts.autoCut === false ? 0x00 : 0x40]);        // modo: corte automático
    push([0x1b, 0x69, 0x4b, opts.autoCut === false ? 0x00 : 0x08]);        // ampliado: cortar al final
    var margin = continuous ? (opts.feedDots == null ? 35 : opts.feedDots) : 0;
    push([0x1b, 0x69, 0x64, margin & 0xff, (margin >> 8) & 0xff]);         // margen de avance (35 puntos = ~3 mm)
    push([0x4d, 0x00]);                                                    // sin compresión
    for (var y = 0; y < height; y++) {
      var row = packRow(bitmap, width, y, media.margin, !!opts.mirror);
      var line = new Uint8Array(3 + LINE_BYTES);
      line[0] = 0x67; line[1] = 0x00; line[2] = LINE_BYTES;
      line.set(row, 3);
      parts.push(line);
    }
    push([0x1a]);                                                          // imprimir y avanzar (última página)
    var total = 0;
    parts.forEach(function (p) { total += p.length; });
    var out = new Uint8Array(total), at = 0;
    parts.forEach(function (p) { out.set(p, at); at += p.length; });
    return out;
  }

  /* De un canvas (o de unos datos RGBA) a un mapa de 1 = negro con umbral (y opcionalmente invertido). */
  function bitmapFromRGBA(rgba, width, height, threshold, invert) {
    var out = new Uint8Array(width * height);
    for (var i = 0; i < width * height; i++) {
      var r = rgba[i * 4], g = rgba[i * 4 + 1], b = rgba[i * 4 + 2], a = rgba[i * 4 + 3];
      var lum = a === 0 ? 255 : (0.299 * r + 0.587 * g + 0.114 * b);        // transparente = papel
      var black = lum < (threshold == null ? 140 : threshold);
      out[i] = (invert ? !black : black) ? 1 : 0;
    }
    return out;
  }

  /* Respuesta de estado de 32 bytes → lo que importa. */
  function parseStatus(bytes) {
    if (!bytes || bytes.length < 32 || bytes[0] !== 0x80) return null;
    var e1 = bytes[8], e2 = bytes[9], errors = [];
    if (e1 & 0x01) errors.push("sin etiquetas");
    if (e1 & 0x02) errors.push("fin de cinta");
    if (e1 & 0x04) errors.push("atasco");
    if (e2 & 0x01) errors.push("cinta distinta a la configurada");
    if (e2 & 0x04) errors.push("cubierta abierta");
    return { mediaWidthMm: bytes[10], mediaType: bytes[11], statusType: bytes[18], errors: errors, ready: errors.length === 0 };
  }

  /* ---------------------------------------------------------------- WebUSB */
  function supported() { return typeof navigator !== "undefined" && !!navigator.usb; }

  function findEndpoints(device) {
    var cfg = device.configuration, found = { iface: null, out: null, inn: null };
    (cfg ? cfg.interfaces : []).forEach(function (itf) {
      var alt = itf.alternates[0];
      if (found.iface !== null || alt.interfaceClass !== 7) return;       // clase 7 = impresora
      found.iface = itf.interfaceNumber;
      alt.endpoints.forEach(function (ep) {
        if (ep.type !== "bulk") return;
        if (ep.direction === "out" && !found.out) found.out = ep.endpointNumber;
        if (ep.direction === "in" && !found.inn) found.inn = ep.endpointNumber;
      });
    });
    return found;
  }

  var state = { device: null, ep: null };

  async function open(device) {
    await device.open();
    if (device.configuration === null) await device.selectConfiguration(1);
    var ep = findEndpoints(device);
    if (ep.iface === null || ep.out === null) throw new Error("La impresora no expone la interfaz de impresión (¿modo «Editor Lite» encendido? Apáguelo con el botón de la impresora hasta que se apague la luz verde).");
    await device.claimInterface(ep.iface);
    state.device = device;
    state.ep = ep;
    return device;
  }

  async function connect(askPermission) {
    if (!supported()) throw new Error("Este navegador no permite USB. Use Chrome (Android o computador) y la página segura (https).");
    var devices = await navigator.usb.getDevices();
    var device = devices.find(function (d) { return d.vendorId === BROTHER_VENDOR; });
    if (!device && askPermission) device = await navigator.usb.requestDevice({ filters: [{ vendorId: BROTHER_VENDOR }] });
    if (!device) return null;
    return open(device);
  }

  async function sendJob(job) {
    if (!state.device) throw new Error("La impresora no está conectada.");
    var CHUNK = 16384;
    for (var at = 0; at < job.length; at += CHUNK) {
      var res = await state.device.transferOut(state.ep.out, job.slice(at, at + CHUNK));
      if (res.status !== "ok") throw new Error("La impresora no aceptó los datos (" + res.status + ").");
    }
  }

  async function readStatus() {
    if (!state.device) throw new Error("La impresora no está conectada.");
    await sendJob(Uint8Array.from([0x1b, 0x69, 0x53]));                    // pedir estado
    if (state.ep.inn === null) return null;
    var res = await state.device.transferIn(state.ep.inn, 32);
    return res.data ? parseStatus(new Uint8Array(res.data.buffer)) : null;
  }

  async function close() {
    if (state.device) { try { await state.device.close(); } catch (e) { /* ya cerrada */ } }
    state.device = null;
  }

  var api = { buildJob: buildJob, bitmapFromRGBA: bitmapFromRGBA, parseStatus: parseStatus, mmToDots: mmToDots, MEDIA: MEDIA, LINE_BYTES: LINE_BYTES,
              supported: supported, connect: connect, sendJob: sendJob, readStatus: readStatus, close: close, info: function () { return state.device; } };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.QLUsb = api;
})(typeof window !== "undefined" ? window : this);
