/* Impresión directa en una Brother QL (QL-800 y hermanas) desde el navegador por USB (WebUSB), sin app nativa ni diálogo de impresión.
 *
 * Dos partes:
 *   1) `QLUsb.buildJob(...)`: PURA (sin navegador). Convierte un mapa de puntos en el flujo de comandos de «raster» de la serie QL (invalidar, inicializar, modo raster, información de
 *      impresión, corte, márgenes, líneas de 90 bytes, imprimir). Se prueba en tests/js/ql_usb_check.js.
 *   2) `QLUsb.connect()` / `sendJob()` / `readStatus()`: la parte de WebUSB (Chrome de Android y de escritorio, solo HTTPS). Pide permiso UNA vez (requestDevice, con un gesto del
 *      usuario); después `getDevices()` reconoce la impresora sin volver a preguntar.
 *   3) Una sola pestaña por equipo es la DUEÑA de la impresora (WebUSB no deja que dos pestañas la tomen: «Unable to claim interface»): un Web Lock con nombre fijo. Si otra pestaña la
 *      tiene, `connect()` lanza un error con `busy = true` y un mensaje amable; quien la usa la suelta con `close()` (releaseInterface + close + suelta el candado).
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

  /* Preferencias de impresión DEL EQUIPO (localStorage, las mismas para el Registro, la impresión compartida y /impresion-usb):
     ql_cut (corte automático, sí por defecto), ql_feed_mm (margen de avance, 1,5 mm por defecto), ql_length_mm (alto de etiqueta en mm; vacío = el de la plantilla),
     ql_mirror y ql_invert (no por defecto). */
  /* Preferencias (23-oct-2026, orden B): VALORES POR EVENTO (`Event.print_settings_json`, se editan en Parámetros) con SOBRESCRITURA POR EQUIPO (localStorage `ql_*`, el panel «⚙️ Impresión»).
     Orden: lo que el equipo fijó a mano > lo del evento > el valor de fábrica. `source` dice de dónde salió cada valor (para el indicador «impreso con…»); «Restablecer» borra lo del equipo.
       tapeWidth/tapeType: la cinta puesta (ancho en mm de QLUsb.MEDIA; «continuous» o «diecut» = troquelada con largo fijo `lengthMm`).
       rotation: «auto» (el lado largo de la etiqueta corre a lo largo de la cinta) | 0 | 90 | 180 | 270.  crop/cropMarginMm: recortar al contenido (última fila con tinta + margen). */
  var PREF_DEFAULTS = { cut: true, feedMm: 1.5, lengthMm: null, mirror: false, invert: false, tapeWidth: 62, tapeType: "continuous", rotation: "auto", crop: true, cropMarginMm: 3 };
  /* «Espejo» cambió de significado el 24-oct-2026 (ver packRow): la clave del equipo pasó a `ql_mirror_v2` y la vieja `ql_mirror` se IGNORA (quien la activó para compensar el error
     quedaría ahora con la etiqueta reflejada). `dropLegacyPrefs` la borra. */
  var LEGACY_KEYS = ["ql_mirror"];
  var PREF_KEYS = { cut: "ql_cut", feedMm: "ql_feed_mm", lengthMm: "ql_length_mm", mirror: "ql_mirror_v2", invert: "ql_invert", tapeWidth: "ql_tape_width", tapeType: "ql_tape_type", rotation: "ql_rotation", crop: "ql_crop", cropMarginMm: "ql_crop_margin_mm" };
  function _num(v, lo, hi) { var n = parseFloat(v); return isFinite(n) && n >= lo && n <= hi ? n : null; }
  function _clean(field, raw) {            // valor válido o undefined
    if (raw === null || raw === undefined || raw === "") return undefined;
    switch (field) {
      case "cut": case "mirror": case "invert": case "crop": return raw === true || raw === "1" || raw === 1 ? true : (raw === false || raw === "0" || raw === 0 ? false : undefined);
      case "feedMm": { var f = _num(raw, 0, 50); return f === null ? undefined : f; }
      case "cropMarginMm": { var c = _num(raw, 0, 30); return c === null ? undefined : c; }
      case "lengthMm": { var l = _num(raw, 10, 1000); return l === null ? undefined : l; }
      case "tapeWidth": { var t = _num(raw, 1, 1000); return t !== null && MEDIA[Math.round(t)] ? Math.round(t) : undefined; }
      case "tapeType": return raw === "continuous" || raw === "diecut" ? raw : undefined;
      case "rotation": { if (raw === "auto") return "auto"; var r = _num(raw, 0, 270); return r !== null && r % 90 === 0 ? r : undefined; }
    }
    return undefined;
  }
  function resolvePrefs(storage, eventPrefs) {
    function get(k) { try { return storage ? storage.getItem(k) : null; } catch (e) { return null; } }
    var prefs = {}, source = {};
    Object.keys(PREF_DEFAULTS).forEach(function (field) {
      var dev = _clean(field, get(PREF_KEYS[field]));
      var evt = _clean(field, eventPrefs ? eventPrefs[field] : undefined);
      if (dev !== undefined) { prefs[field] = dev; source[field] = "equipo"; }
      else if (evt !== undefined) { prefs[field] = evt; source[field] = "evento"; }
      else { prefs[field] = PREF_DEFAULTS[field]; source[field] = "defecto"; }
    });
    return { prefs: prefs, source: source };
  }
  function readPrefs(storage, eventPrefs) { return resolvePrefs(storage, eventPrefs).prefs; }
  function savePrefs(storage, p) {
    function set(k, v) { try { if (v === null || v === "") storage.removeItem(k); else storage.setItem(k, String(v)); } catch (e) { /* sin almacenamiento: vale para esta sesión */ } }
    ["cut", "mirror", "invert", "crop"].forEach(function (f) { if (f in p) set(PREF_KEYS[f], p[f] ? "1" : "0"); });
    ["feedMm", "cropMarginMm", "tapeWidth", "tapeType", "rotation"].forEach(function (f) { if (f in p) set(PREF_KEYS[f], p[f]); });
    if ("lengthMm" in p) set(PREF_KEYS.lengthMm, p.lengthMm || "");
  }
  function clearPrefs(storage) {                     // «Restablecer»: el equipo vuelve a usar los valores del evento
    Object.keys(PREF_KEYS).forEach(function (f) { try { storage.removeItem(PREF_KEYS[f]); } catch (e) { /* nada que borrar */ } });
    dropLegacyPrefs(storage);
  }
  function dropLegacyPrefs(storage) {                // borra las claves con el significado viejo (nunca se leen)
    LEGACY_KEYS.forEach(function (k) { try { if (storage) storage.removeItem(k); } catch (e) { /* sin almacenamiento */ } });
  }
  function describePrefs(prefs, source, layoutInfo) {
    var src = {}; Object.keys(source || {}).forEach(function (k) { src[source[k]] = true; });
    var from = src.origen ? "el equipo que la pidió" : src.equipo && src.evento ? "equipo y evento" : src.equipo ? "este equipo" : src.evento ? "el evento" : "valores de fábrica";
    var rot = layoutInfo ? (prefs.rotation === "auto" ? "giro automático (" + layoutInfo.rotation + "°)" : "giro " + layoutInfo.rotation + "°") : (prefs.rotation === "auto" ? "giro automático" : "giro " + prefs.rotation + "°");
    return "Cinta " + prefs.tapeWidth + " mm " + (prefs.tapeType === "diecut" ? "troquelada de " + prefs.lengthMm + " mm" : "continua") + " · " + rot +
      (prefs.tapeType === "diecut" ? "" : " · " + (prefs.crop ? "recorte al contenido (+" + prefs.cropMarginMm + " mm)" : "alto de la plantilla")) + " · corte " + (prefs.cut ? "sí" : "no") + " · margen " + prefs.feedMm + " mm · según " + from;
  }

  /* ---- geometría pura de la etiqueta (sin navegador; se prueba en tests/js/ql_usb_check.js) ---- */
  function printableMm(tapeWidth) { var m = MEDIA[tapeWidth]; return m ? m.printable / DOTS_PER_MM : 0; }
  /* ¿Cómo queda la plantilla (w×h mm) en la cinta? rotation efectivo, mm a lo ancho de la cinta (`across`) y a lo largo (`along`), y si es más ancha que la cinta (`tooWide`: se encoge `scale` y hay que AVISAR). */
  function layout(prefs, tplWmm, tplHmm) {
    var rot = prefs.rotation === "auto" ? (tplWmm > tplHmm ? 90 : 0) : prefs.rotation;      // auto: el lado largo corre a lo largo de la cinta
    var sideways = rot === 90 || rot === 270;
    var across = sideways ? tplHmm : tplWmm, along = sideways ? tplWmm : tplHmm;
    var avail = printableMm(prefs.tapeWidth);
    var tooWide = across > avail + 0.3;
    return { rotation: rot, acrossMm: across, alongMm: along, availMm: avail, tooWide: tooWide, scale: tooWide ? avail / across : 1 };
  }
  function rotateBitmap(bm, w, h, deg) {            // bm: Uint8Array w×h (1 = tinta). 90 = en sentido horario.
    deg = ((deg % 360) + 360) % 360;
    if (deg === 0) return { bitmap: bm, w: w, h: h };
    var out, x, y;
    if (deg === 180) { out = new Uint8Array(w * h); for (y = 0; y < h; y++) for (x = 0; x < w; x++) out[(h - 1 - y) * w + (w - 1 - x)] = bm[y * w + x]; return { bitmap: out, w: w, h: h }; }
    out = new Uint8Array(w * h);                    // el resultado mide h×w
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      if (deg === 90) out[x * h + (h - 1 - y)] = bm[y * w + x];
      else out[(w - 1 - x) * h + y] = bm[y * w + x];                       // 270
    }
    return { bitmap: out, w: h, h: w };
  }
  function centerOnTape(bm, w, h, tapeDots) {         // pone la etiqueta centrada a lo ancho de la cinta (blanco a los lados); si es más ancha, se recorta el sobrante simétrico
    if (w === tapeDots) return bm;
    var out = new Uint8Array(tapeDots * h), off = Math.floor((tapeDots - w) / 2), x, y;
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) { var tx = x + off; if (tx >= 0 && tx < tapeDots) out[y * tapeDots + tx] = bm[y * w + x]; }
    return out;
  }
  function lastInkRow(bm, w, h) {
    for (var y = h - 1; y >= 0; y--) { var base = y * w; for (var x = 0; x < w; x++) if (bm[base + x]) return y; }
    return -1;
  }
  function firstInkRow(bm, w, h) {
    for (var y = 0; y < h; y++) { var base = y * w; for (var x = 0; x < w; x++) if (bm[base + x]) return y; }
    return -1;
  }
  function cropToContent(bm, w, h, marginDots, minTailDots) {      // conserva hasta la última fila con tinta + margen (nunca más que lo que había; si no hay tinta, no recorta). minTailDots: blanco mínimo al final (horizontal: el del inicio)
    var last = lastInkRow(bm, w, h);
    if (last < 0) return { bitmap: bm, h: h };
    var nh = Math.min(h, last + 1 + Math.max(0, Math.round(marginDots), Math.round(minTailDots || 0)));
    return nh === h ? { bitmap: bm, h: h } : { bitmap: bm.subarray(0, w * nh), h: nh };
  }
  function invertBitmap(bm) { var out = new Uint8Array(bm.length); for (var i = 0; i < bm.length; i++) out[i] = bm[i] ? 0 : 1; return out; }
  /* De la etiqueta ya dibujada (mapa 1 = tinta, sin invertir) al trabajo para la cinta: giro, centrado, recorte (solo continua) e invertir. Devuelve {bitmap, height, rotation, cropped}. */
  function prepareBitmap(bm, w, h, prefs, lay) {
    var r = rotateBitmap(bm, w, h, lay.rotation);
    var tapeDots = MEDIA[prefs.tapeWidth].printable;
    var bitmap = centerOnTape(r.bitmap, r.w, r.h, tapeDots), height = r.h, cropped = false;
    if (prefs.tapeType === "diecut" && prefs.lengthMm) {                     // troquelada: largo fijo (se rellena de blanco o se corta lo que sobre)
      var want = mmToDots(prefs.lengthMm), fixed = new Uint8Array(tapeDots * want);
      fixed.set(bitmap.subarray(0, Math.min(bitmap.length, fixed.length)));
      bitmap = fixed; height = want;
    } else if (prefs.crop) {
      // Horizontal (gira 90°/270°): el texto suele quedar centrado a lo largo de la tira y el recorte solo quitaba el blanco del FINAL, así que la tinta salía pegada al extremo. 28-oct-2026
      // (prueba física en la Brother, producción): el blanco del final iguala al del inicio (nunca más largo que la plantilla). La vertical no cambia.
      var sideways = lay.rotation === 90 || lay.rotation === 270;
      var c = cropToContent(bitmap, tapeDots, height, mmToDots(prefs.cropMarginMm), sideways ? Math.max(0, firstInkRow(bitmap, tapeDots, height)) : 0);
      cropped = c.h !== height; bitmap = c.bitmap; height = c.h;
    } else if (prefs.lengthMm) {                                              // alto fijo manual (continua)
      var fh = mmToDots(prefs.lengthMm), fx = new Uint8Array(tapeDots * fh);
      fx.set(bitmap.subarray(0, Math.min(bitmap.length, fx.length)));
      bitmap = fx; height = fh;
    }
    if (prefs.invert) bitmap = invertBitmap(bitmap);
    return { bitmap: bitmap, height: height, rotation: lay.rotation, cropped: cropped };
  }

  /* bitmap: Uint8Array (alto × ancho) con 1 = negro; ancho = puntos imprimibles de la cinta. Devuelve la fila de 90 bytes (MSB = primer punto).
     El cabezal de la serie QL pone el PRIMER punto de cada línea en el borde DERECHO de la etiqueta (vista como sale de la impresora): por eso la columna izquierda del dibujo va al
     ÚLTIMO punto. Error real (24-oct-2026, prueba física de Juan en la QL-800): se mandaba la columna izquierda en el primer punto y la etiqueta salía en espejo sin «Espejo»
     (y derecha con «Espejo»). Es lo mismo que hace la librería brother_ql (voltea izquierda-derecha antes de mandar las líneas). Ahora: sin espejo = derecha; con espejo = reflejada. */
  function packRow(bitmap, width, y, margin, mirror) {
    var row = new Uint8Array(LINE_BYTES);
    for (var x = 0; x < width; x++) {
      var v = bitmap[y * width + (mirror ? x : width - 1 - x)];
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
    if (opts.autoCut !== false) push([0x1b, 0x69, 0x41, 0x01]);            // cortar cada 1 etiqueta (22-oct-2026: sin esto la cinta podía salir sin cortar)
    push([0x1b, 0x69, 0x4b, opts.autoCut === false ? 0x00 : 0x08]);        // ampliado: cortar al final
    var margin = continuous ? (opts.feedDots == null ? 35 : opts.feedDots) : 0;
    push([0x1b, 0x69, 0x64, margin & 0xff, (margin >> 8) & 0xff]);         // margen de avance (35 puntos = ~3 mm; quien llama pasa feedDots de las preferencias del equipo)
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
  var BUSY_MSG = "La impresora está en uso en otra pestaña de este equipo: ciérrala.";
  var LOCK_NAME = "golden-ql-usb";
  var owner = { held: false, release: null };

  function busyError() { var e = new Error(BUSY_MSG); e.busy = true; return e; }

  /* Candado entre pestañas del mismo equipo (Web Locks). Sin Web Locks en el navegador se decide solo por claimInterface. */
  function own() {
    if (owner.held || typeof navigator === "undefined" || !navigator.locks) return Promise.resolve(true);
    return new Promise(function (resolve) {
      navigator.locks.request(LOCK_NAME, { ifAvailable: true }, function (lock) {
        if (!lock) { resolve(false); return null; }
        owner.held = true;
        resolve(true);
        return new Promise(function (r) { owner.release = r; });             // se mantiene hasta disown() o hasta que se cierre la pestaña
      }).catch(function () { resolve(true); });
    });
  }
  function disown() {
    if (owner.release) owner.release();
    owner.held = false;
    owner.release = null;
  }

  async function open(device) {
    if (!(await own())) throw busyError();
    try {
      await device.open();
      if (device.configuration === null) await device.selectConfiguration(1);
      var ep = findEndpoints(device);
      if (ep.iface === null || ep.out === null) throw new Error("La impresora no expone la interfaz de impresión (¿modo «Editor Lite» encendido? Apáguelo con el botón de la impresora hasta que se apague la luz verde).");
      try { await device.claimInterface(ep.iface); }
      catch (e) { throw busyError(); }                                          // «Unable to claim interface»: otra pestaña (o página) la tiene tomada
      state.device = device;
      state.ep = ep;
      return device;
    } catch (e) {
      try { if (device.opened) await device.close(); } catch (e2) { /* ya cerrada */ }
      disown();
      throw e;
    }
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

  async function close() {                                                     // suelta la impresora para otra pestaña: releaseInterface + close + candado
    if (state.device) {
      try { if (state.ep && state.ep.iface !== null) await state.device.releaseInterface(state.ep.iface); } catch (e) { /* ya suelta o desconectada */ }
      try { await state.device.close(); } catch (e) { /* ya cerrada */ }
    }
    state.device = null;
    state.ep = null;
    disown();
  }

  var api = { readPrefs: readPrefs, savePrefs: savePrefs, resolvePrefs: resolvePrefs, clearPrefs: clearPrefs, describePrefs: describePrefs, PREF_DEFAULTS: PREF_DEFAULTS, PREF_KEYS: PREF_KEYS,
              layout: layout, printableMm: printableMm, dropLegacyPrefs: dropLegacyPrefs, LEGACY_KEYS: LEGACY_KEYS, rotateBitmap: rotateBitmap, centerOnTape: centerOnTape, cropToContent: cropToContent, invertBitmap: invertBitmap, prepareBitmap: prepareBitmap, buildJob: buildJob, bitmapFromRGBA: bitmapFromRGBA, parseStatus: parseStatus, mmToDots: mmToDots, MEDIA: MEDIA, LINE_BYTES: LINE_BYTES,
              supported: supported, connect: connect, sendJob: sendJob, readStatus: readStatus, close: close, info: function () { return state.device; },
              BUSY_MSG: BUSY_MSG, LOCK_NAME: LOCK_NAME, isOwner: function () { return owner.held; } };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.QLUsb = api;
})(typeof window !== "undefined" ? window : this);
