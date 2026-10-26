/* Impresión por el CONTROLADOR de Windows (orden del 25-oct-2026). En Windows, Chrome no puede abrir la QL-800 por WebUSB cuando la tiene el controlador (open() da «Access denied»), así que ese
   computador imprime por la cola «Brother QL-800» del sistema: se arma la MISMA etiqueta de siempre (mismo motor, mismos ajustes), se manda como una página de tamaño exacto en milímetros y se
   imprime con window.print() desde un iframe oculto. Aquí está lo que NO toca el navegador (se prueba en tests/js/driver_print_check.js):
     · el modo de impresión del equipo («auto» | «usb» | «driver»), guardado en este equipo;
     · el tamaño exacto de la página y de la imagen (pageSpec) y su HTML (pageHtml);
     · el lanzador .bat para abrir Chrome con --kiosk-printing (impresión sin cuadro), que no instala nada ni toca el registro.
   La parte con navegador (bitmap → imagen, iframe, print) está al final. */
(function (root) {
  "use strict";

  var DPI = 300;                         // puntos por pulgada de la QL-800 (696 puntos = 58,93 mm imprimibles en la cinta de 62 mm)
  var MODE_KEY = "gw_print_mode";        // por EQUIPO (localStorage), no por evento
  var PAGE_KEY = "gw_driver_page_mm";    // ancho de página que se le pide al controlador (vacío = el ancho útil de la imagen: 58,9 mm)
  var DX_KEY = "gw_driver_dx", DY_KEY = "gw_driver_dy";      // calibración por equipo (mm, de −5 a +5): desplazamiento horizontal y vertical de la imagen
  var KIOSK_KEY = "gw_kiosk_print";      // la ventana se abrió con el lanzador (sessionStorage: sobrevive a recargar esa ventana)
  var MODES = ["auto", "usb", "driver"];
  var MODE_LABELS = { auto: "Automático (recomendado)", usb: "USB directo", driver: "Controlador de Windows" };

  function mmOfDots(dots) { return dots * 25.4 / DPI; }
  function round2(n) { return Math.round(n * 100) / 100; }

  /* ---------------------------------------------------------------- modo por equipo */
  function getMode(storage) {
    try { var v = storage && storage.getItem(MODE_KEY); return MODES.indexOf(v) >= 0 ? v : "auto"; } catch (e) { return "auto"; }
  }
  function setMode(storage, mode) {
    if (MODES.indexOf(mode) < 0) return false;
    try { if (mode === "auto") storage.removeItem(MODE_KEY); else storage.setItem(MODE_KEY, mode); return true; } catch (e) { return false; }
  }
  function getPageWidthMm(storage) {                       // null = automático (el ancho útil de la imagen)
    try { var n = parseFloat(storage && storage.getItem(PAGE_KEY)); if (isFinite(n) && n >= 20 && n <= 120) return n; } catch (e) { /* sin almacenamiento */ }
    return null;
  }
  function setPageWidthMm(storage, mm) {
    try { if (!mm) storage.removeItem(PAGE_KEY); else storage.setItem(PAGE_KEY, String(mm)); } catch (e) { /* nada */ }
  }
  function clampOffset(v) { var n = parseFloat(v); return isFinite(n) ? Math.max(-5, Math.min(5, Math.round(n * 10) / 10)) : 0; }
  function getOffsets(storage) {
    var dx = 0, dy = 0;
    try { dx = clampOffset(storage && storage.getItem(DX_KEY)); dy = clampOffset(storage && storage.getItem(DY_KEY)); } catch (e) { /* sin almacenamiento */ }
    return { dx: dx, dy: dy };
  }
  function setOffsets(storage, dx, dy) {
    var a = clampOffset(dx), b = clampOffset(dy);
    try { if (a) storage.setItem(DX_KEY, String(a)); else storage.removeItem(DX_KEY); if (b) storage.setItem(DY_KEY, String(b)); else storage.removeItem(DY_KEY); } catch (e) { /* nada */ }
    return { dx: a, dy: b };
  }

  /* ¿Esta ventana se abrió con el lanzador (?impresion=kiosk)? Se recuerda en sessionStorage para que sobreviva a recargar la ventana. */
  function kioskFromUrl(search, session) {
    var fromUrl = false;
    try { fromUrl = new URLSearchParams(search || "").get("impresion") === "kiosk"; } catch (e) { fromUrl = false; }
    try {
      if (fromUrl && session) session.setItem(KIOSK_KEY, "1");
      return fromUrl || !!(session && session.getItem(KIOSK_KEY) === "1");
    } catch (e) { return fromUrl; }
  }

  /* ---------------------------------------------------------------- tamaño exacto de lo que se manda a imprimir
     La imagen mide exactamente (puntos × 25,4 / 300) mm; la página mide `pageWidthMm` de ancho (el de la cinta: 62) por el largo de la etiqueta, sin márgenes ni escalado; la imagen va CENTRADA
     a lo ancho (la QL-800 imprime 696 de los 720 puntos de su cabezal: 12 de margen a cada lado). */
  /* 25-oct-2026: la página mide el ANCHO ÚTIL de la cinta (58,93 mm = 696 puntos) por el largo de la etiqueta; ninguna orientación la ensancha (la horizontal se gira 90° ANTES, con el mismo giro automático
     del USB: la imagen que llega ya va a lo largo de la cinta). `offsets` (calibración de este equipo, ±5 mm) mueve la imagen dentro de la página; lo que sobresalga se recorta. */
  function pageSpec(bitmapWidthDots, heightDots, pageWidthMm, offsets) {
    var imgW = mmOfDots(bitmapWidthDots), imgH = mmOfDots(heightDots);
    var pageW = pageWidthMm && pageWidthMm >= imgW ? pageWidthMm : imgW;
    var dx = offsets ? clampOffset(offsets.dx) : 0, dy = offsets ? clampOffset(offsets.dy) : 0;
    var pageH = imgH + Math.max(0, dy);                                    // hacia abajo se agrega papel en blanco; hacia arriba, lo que sobresale se recorta
    var left = (pageW - imgW) / 2 + dx;
    return { pageWidthMm: round2(pageW), pageHeightMm: round2(pageH), imageWidthMm: round2(imgW), imageHeightMm: round2(imgH), leftMm: round2(left), topMm: round2(dy),
             pageCss: "@page { size: " + round2(pageW) + "mm " + round2(pageH) + "mm; margin: 0 }" };
  }
  function pageHtml(spec, imageUrl) {
    var w = spec.pageWidthMm, h = spec.pageHeightMm;
    return "<!doctype html><html><head><meta charset=\"utf-8\"><title>Escarapela</title><style>" + spec.pageCss +
      " html,body{margin:0;padding:0;background:#fff}" +
      " body{width:" + w + "mm;height:calc(" + h + "mm - 0.2mm);overflow:hidden}" +             // 0,2 mm menos: ninguna página en blanco por un redondeo
      " img{display:block;position:absolute;top:" + spec.topMm + "mm;left:" + spec.leftMm + "mm;width:" + spec.imageWidthMm + "mm;height:" + spec.imageHeightMm + "mm;image-rendering:pixelated;-webkit-print-color-adjust:exact;print-color-adjust:exact}" +
      "</style></head><body><img alt=\"\" src=\"" + imageUrl + "\"></body></html>";
  }

  /* ---------------------------------------------------------------- lanzador para impresión SIN cuadro de diálogo
     Chrome solo imprime sin cuadro si se abre con --kiosk-printing y la impresora predeterminada es la Brother. El perfil propio (--user-data-dir) hace que el parámetro se aplique aunque ya haya
     otro Chrome abierto. El archivo no instala nada, no toca el registro ni pide permisos de administrador. */
  var CHROME_PATHS = ["%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe", "%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe", "%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"];
  var EDGE_PATHS = ["%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe", "%ProgramFiles%\\Microsoft\\Edge\\Application\\msedge.exe"];
  var PROFILE_DIR = "%LOCALAPPDATA%\\GoldenWebImpresion";
  function kioskUrl(href) {
    try { var u = new URL(href); u.searchParams.set("impresion", "kiosk"); u.hash = ""; return u.toString(); } catch (e) { return String(href || "") + (String(href || "").indexOf("?") < 0 ? "?" : "&") + "impresion=kiosk"; }
  }
  function launcherCommand(href) {                                                         // el mismo comando, como texto para un acceso directo
    return "\"" + CHROME_PATHS[0] + "\" --kiosk-printing --user-data-dir=\"" + PROFILE_DIR + "\" \"" + kioskUrl(href) + "\"";
  }
  function launcherBat(href) {
    var url = kioskUrl(href).replace(/%/g, "%%");
    var L = [];
    L.push("@echo off");
    L.push("rem Lanzador de impresion de GoldenWeb. NO instala nada y NO toca el registro de Windows: solo abre Chrome (o Edge) con la impresion sin cuadro de dialogo.");
    L.push("rem Requisito: la impresora Brother QL-800 debe ser la impresora PREDETERMINADA de Windows.");
    L.push("set \"URL=" + url + "\"");
    L.push("set \"PERFIL=" + PROFILE_DIR + "\"");
    L.push("set \"NAVEGADOR=\"");
    CHROME_PATHS.forEach(function (p) { L.push("if not defined NAVEGADOR if exist \"" + p + "\" set \"NAVEGADOR=" + p + "\""); });
    L.push("if defined NAVEGADOR goto abrir");
    L.push("rem No hay Chrome: se prueba con Microsoft Edge (viene con Windows 11).");
    EDGE_PATHS.forEach(function (p) { L.push("if not defined NAVEGADOR if exist \"" + p + "\" set \"NAVEGADOR=" + p + "\""); });
    L.push("if defined NAVEGADOR goto abrir");
    L.push("echo No se encontro Google Chrome ni Microsoft Edge en este computador.");
    L.push("echo Instala Google Chrome (https://www.google.com/chrome) y vuelve a abrir este archivo.");
    L.push("pause");
    L.push("exit /b 1");
    L.push(":abrir");
    L.push("start \"\" \"%NAVEGADOR%\" --kiosk-printing --user-data-dir=\"%PERFIL%\" \"%URL%\"");
    L.push("exit /b 0");
    return L.join("\r\n") + "\r\n";                                                          // saltos de línea de Windows
  }

  /* ---------------------------------------------------------------- con navegador */
  /* De un mapa de puntos (1 = tinta, `width` × `height`) a una imagen PNG en blanco y negro. `mirror`: reflejar a lo ancho (el «Espejo» elegido a propósito). */
  function bitmapToDataUrl(bitmap, width, height, mirror) {
    var canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = height;
    var ctx = canvas.getContext("2d"), img = ctx.createImageData(width, height);
    for (var y = 0; y < height; y++) {
      for (var x = 0; x < width; x++) {
        var v = bitmap[y * width + (mirror ? width - 1 - x : x)] ? 0 : 255, i = (y * width + x) * 4;
        img.data[i] = v; img.data[i + 1] = v; img.data[i + 2] = v; img.data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas.toDataURL("image/png");
  }

  /* ---------------------------------------------------------------- la etiqueta como PDF (impresión SIN cuadro: --kiosk-printing)
     27-oct-2026 (hotfix): con --kiosk-printing Chrome usa SU configuración por defecto, con «Encabezados y pies de página» activados; en una impresora real la zona que no puede imprimir le da
     margen, y ahí dibuja fecha y hora, el título, la dirección y «1/1» (con el cuadro, no: la vista previa los apaga sin margen). Ni el título vacío ni el iframe del tamaño de la hoja lo evitan
     (probado en Chrome real). El visor de PDF de Chrome NO dibuja encabezados ni pies: en modo sin cuadro la etiqueta se imprime como un PDF de UNA página del tamaño exacto de la hoja, con la
     imagen ya compuesta en blanco y negro (1 bit por punto, sin compresión ni dependencias). Función pura: se prueba en tests/js/driver_print_check.js. */
  function ptOfMm(mm) { return (mm * 72 / 25.4).toFixed(4); }
  function pdfFromBitmap(bitmap, width, height, spec, mirror) {
    var rowBytes = Math.ceil(width / 8), img = new Uint8Array(rowBytes * height), x, y;
    img.fill(0xff);                                                             // DeviceGray de 1 bit: 1 = papel, 0 = tinta
    for (y = 0; y < height; y++) {
      for (x = 0; x < width; x++) {
        if (bitmap[y * width + (mirror ? width - 1 - x : x)]) img[y * rowBytes + (x >> 3)] &= ~(0x80 >> (x & 7));
      }
    }
    var pw = ptOfMm(spec.pageWidthMm), ph = ptOfMm(spec.pageHeightMm), iw = ptOfMm(spec.imageWidthMm), ih = ptOfMm(spec.imageHeightMm);
    var ix = ptOfMm(spec.leftMm), iy = ptOfMm(spec.pageHeightMm - spec.topMm - spec.imageHeightMm);
    var content = "q " + iw + " 0 0 " + ih + " " + ix + " " + iy + " cm /Im0 Do Q";
    var enc = function (t) { var b = new Uint8Array(t.length); for (var i = 0; i < t.length; i++) b[i] = t.charCodeAt(i) & 0xff; return b; };
    var parts = [], offsets = [], size = 0;
    var push = function (b) { parts.push(b); size += b.length; };
    var obj = function (n, head, stream) {
      offsets[n] = size;
      push(enc(n + " 0 obj\n" + head));
      if (stream) { push(enc("stream\n")); push(stream); push(enc("\nendstream")); }
      push(enc("\nendobj\n"));
    };
    push(enc("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"));
    obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
    obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
    obj(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + pw + " " + ph + "] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>");
    obj(4, "<< /Type /XObject /Subtype /Image /Width " + width + " /Height " + height + " /ColorSpace /DeviceGray /BitsPerComponent 1 /Interpolate false /Length " + img.length + " >>\n", img);
    var c = enc(content);
    obj(5, "<< /Length " + c.length + " >>\n", c);
    var xref = size, lines = ["xref", "0 6", "0000000000 65535 f "];
    for (var n = 1; n <= 5; n++) lines.push(("0000000000" + offsets[n]).slice(-10) + " 00000 n ");
    push(enc(lines.join("\n") + "\ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n"));
    var out = new Uint8Array(size), at = 0;
    parts.forEach(function (b) { out.set(b, at); at += b.length; });
    return out;
  }

  var chain = Promise.resolve();
  /* Imprime la página en un iframe OCULTO (sin pestañas nuevas). Una impresión a la vez. Devuelve una promesa que se cumple cuando el navegador termina con el cuadro o con el envío
     (`afterprint`) y falla si no se pudo ni armar la página. */
  /* Sin cuadro (`opts.pdf` = {bitmap, width, height, mirror}): el PDF de la etiqueta en un iframe fuera de la pantalla, del tamaño de la hoja; se espera a que el visor cargue y se imprime. El visor
     no avisa al terminar (`afterprint`): con --kiosk-printing el envío es inmediato, así que se da por enviada a los `PDF_SETTLE_MS` (una impresión a la vez: los trabajos esperan en fila). */
  function printPdf(spec, opts) {
    return new Promise(function (resolve, reject) {
      var doc = root.document, bytes;
      try { bytes = pdfFromBitmap(opts.pdf.bitmap, opts.pdf.width, opts.pdf.height, spec, opts.pdf.mirror); } catch (e) { reject(e); return; }
      var url = root.URL.createObjectURL(new root.Blob([bytes], { type: "application/pdf" }));
      var frame = doc.createElement("iframe");
      frame.setAttribute("aria-hidden", "true");
      frame.style.cssText = "position:fixed;left:-10000px;top:0;border:0;width:" + spec.pageWidthMm + "mm;height:" + spec.pageHeightMm + "mm";
      var done = false;
      function finish(err) {
        if (done) return; done = true;
        setTimeout(function () { try { frame.remove(); } catch (e) { /* ya quitado */ } try { root.URL.revokeObjectURL(url); } catch (e) { /* ya liberada */ } }, 1500);
        if (err) reject(err); else resolve({ printed: true, pdf: true });
      }
      var tries = 0;
      function go() {
        try { frame.contentWindow.focus(); frame.contentWindow.print(); setTimeout(function () { finish(); }, api.PDF_SETTLE_MS); }
        catch (e) { if (++tries < 5) setTimeout(go, 400); else finish(e); }       // el visor de PDF aún no cargó: se reintenta
      }
      frame.onload = function () { setTimeout(go, api.PDF_VIEWER_WAIT_MS); };
      setTimeout(function () { if (!done && tries === 0) finish(new Error("El visor de PDF no cargó la etiqueta.")); }, (opts && opts.timeoutMs) || 20000);
      frame.src = url;
      doc.body.appendChild(frame);
    });
  }

  function printPage(spec, imageUrl, opts) {
    if (opts && opts.pdf) {
      var runPdf = chain.then(function () { return printPdf(spec, opts); });
      chain = runPdf.catch(function () { /* la siguiente impresión no hereda el fallo */ });
      return runPdf;
    }
    var run = chain.then(function () {
      return new Promise(function (resolve, reject) {
        var doc = root.document;
        var frame = doc.createElement("iframe");
        frame.setAttribute("aria-hidden", "true");
        frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
        var done = false, timer = null;
        function finish(err) {
          if (done) return; done = true; clearTimeout(timer);
          setTimeout(function () { try { frame.remove(); } catch (e) { /* ya quitado */ } }, 1000);
          if (err) reject(err); else resolve({ printed: true });
        }
        frame.onload = function () {
          var w = frame.contentWindow;
          var img = w.document.querySelector("img");
          var go = function () {
            try {
              w.focus();
              w.addEventListener("afterprint", function () { finish(); });
              timer = setTimeout(function () { finish(); }, (opts && opts.timeoutMs) || api.PRINT_TIMEOUT_MS);          // sin «afterprint» (algunas versiones): se da por enviada
              w.print();
            } catch (e) { finish(e); }
          };
          if (img && img.decode) img.decode().then(go, go); else go();
        };
        frame.srcdoc = pageHtml(spec, imageUrl);
        doc.body.appendChild(frame);
      });
    });
    chain = run.catch(function () { /* la siguiente impresión no hereda el fallo */ });
    return run;
  }

  var api = { PRINT_TIMEOUT_MS: 120000, PDF_SETTLE_MS: 2500, PDF_VIEWER_WAIT_MS: 600, pdfFromBitmap: pdfFromBitmap, DPI: DPI, MODES: MODES, MODE_LABELS: MODE_LABELS, MODE_KEY: MODE_KEY, PAGE_KEY: PAGE_KEY, KIOSK_KEY: KIOSK_KEY, getMode: getMode, setMode: setMode, getPageWidthMm: getPageWidthMm, setPageWidthMm: setPageWidthMm, getOffsets: getOffsets, setOffsets: setOffsets,
              kioskFromUrl: kioskFromUrl, mmOfDots: mmOfDots, pageSpec: pageSpec, pageHtml: pageHtml, kioskUrl: kioskUrl, launcherCommand: launcherCommand, launcherBat: launcherBat,
              bitmapToDataUrl: bitmapToDataUrl, printPage: printPage };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.DriverPrint = api;
})(typeof window !== "undefined" ? window : this);
