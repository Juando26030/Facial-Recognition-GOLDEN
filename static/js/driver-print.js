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

  var chain = Promise.resolve();
  /* Imprime la página en un iframe OCULTO (sin pestañas nuevas). Una impresión a la vez. Devuelve una promesa que se cumple cuando el navegador termina con el cuadro o con el envío
     (`afterprint`) y falla si no se pudo ni armar la página. */
  function printPage(spec, imageUrl, opts) {
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

  var api = { PRINT_TIMEOUT_MS: 120000, DPI: DPI, MODES: MODES, MODE_LABELS: MODE_LABELS, MODE_KEY: MODE_KEY, PAGE_KEY: PAGE_KEY, KIOSK_KEY: KIOSK_KEY, getMode: getMode, setMode: setMode, getPageWidthMm: getPageWidthMm, setPageWidthMm: setPageWidthMm, getOffsets: getOffsets, setOffsets: setOffsets,
              kioskFromUrl: kioskFromUrl, mmOfDots: mmOfDots, pageSpec: pageSpec, pageHtml: pageHtml, kioskUrl: kioskUrl, launcherCommand: launcherCommand, launcherBat: launcherBat,
              bitmapToDataUrl: bitmapToDataUrl, printPage: printPage };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.DriverPrint = api;
})(typeof window !== "undefined" ? window : this);
