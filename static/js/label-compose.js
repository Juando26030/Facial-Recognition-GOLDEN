/* La etiqueta COMPUESTA, una sola vez para todas las salidas (27-oct-2026). La impresión directa por USB (static/js/shared-print.js) y la ventana de impresión del navegador (templates/badge_print.html)
   parten del MISMO bitmap: la plantilla dibujada a 300 dpi, con el giro, el centrado en la cinta, el recorte y «invertir» que resuelve QLUsb (static/js/ql-usb.js) a partir de los valores de impresión
   (los del evento en Parámetros y lo que se ajustó en ⚙️ de este equipo). Así, cambiar el recorte, el margen o el giro cambia las dos salidas igual.
   Es el mismo código que antes vivía en shared-print.js (`renderTemplate` y `composeJob`), sin cambios en la composición: solo se movió aquí para compartirlo.

   - renderShot(stage, template, data, eventId): dibuja la plantilla con BadgeRender y la captura con html2canvas a 300 dpi.
   - composeBitmap(shot, tplW, tplH, p): {bitmap, tapeDots, height, layout, cropped, widthMm, heightMm} (bitmap: Uint8Array tapeDots × height, 1 = tinta).
   - pageSpec(out, mirror): la hoja del navegador para ese bitmap: mide EXACTAMENTE puntos × 25,4 / 300 mm, sin márgenes ni escalado (se centra a lo ancho porque la hoja es del ancho de la imagen). */
(function (root, factory) {
  var api = factory(root);
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.LabelCompose = api;
})(typeof window !== "undefined" ? window : this, function (root) {
  "use strict";
  var DPM = 300 / 25.4;                       // puntos por mm de la QL-800

  async function renderShot(stage, template, data, eventId, holderScale) {
    var BadgeRender = root.BadgeRender, doc = root.document;
    var holder = doc.createElement("div");
    stage.appendChild(holder);
    try {
      await BadgeRender.loadFonts(template);                         // la tipografía elegida ya cargada: la etiqueta impresa no cambia de letra
      BadgeRender.renderBadge(holder, template, data, { eventId: eventId });
      if (doc.fonts && doc.fonts.ready) await doc.fonts.ready;
      await Promise.all(Array.from(holder.querySelectorAll("img")).map(function (img) { return img.decode ? img.decode().catch(function () {}) : null; }));
      // con el ancho REAL (con decimales) de la caja: offsetWidth redondea a px enteros y la etiqueta salía 2-3 puntos más ancha y estirada (25-oct-2026)
      var box = holder.getBoundingClientRect();
      return await root.html2canvas(holder, { width: box.width, height: box.height, scale: (template.width_mm * DPM) / box.width * (holderScale || 1), useCORS: true, backgroundColor: "#ffffff", logging: false });
    } finally {
      holder.remove();
    }
  }

  /* De la plantilla ya dibujada (canvas a 300 dpi) al bitmap de la cinta: tamaño REAL (sin estirar al ancho de la cinta), giro, centrado, recorte e invertir. */
  function composeBitmap(shot, tplW, tplH, p) {
    var QLUsb = root.QLUsb;
    var lay = QLUsb.layout(p, tplW, tplH);
    var w = Math.max(1, Math.round(tplW * DPM * lay.scale)), h = Math.max(1, Math.round(tplH * DPM * lay.scale));
    var canvas = root.document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h);
    ctx.drawImage(shot, 0, 0, w, h);
    var bm = QLUsb.bitmapFromRGBA(ctx.getImageData(0, 0, w, h).data, w, h, 140, false);
    var prep = QLUsb.prepareBitmap(bm, w, h, p, lay);
    var tapeDots = QLUsb.MEDIA[p.tapeWidth].printable;
    return { bitmap: prep.bitmap, tapeDots: tapeDots, height: prep.height, layout: lay, cropped: prep.cropped, widthMm: tplW, heightMm: tplH };
  }

  function round2(n) { return Math.round(n * 100) / 100; }
  function pageSpec(out) {
    var w = round2(out.tapeDots / DPM), h = round2(out.height / DPM);
    return { pageWidthMm: w, pageHeightMm: h, imageWidthMm: w, imageHeightMm: h, pageCss: "@page { size: " + w + "mm " + h + "mm; margin: 0 }" };
  }

  /* El bitmap como imagen PNG en blanco y negro (`mirror`: reflejar a lo ancho, el «Espejo» elegido a propósito). */
  function bitmapToDataUrl(bitmap, width, height, mirror) {
    var canvas = root.document.createElement("canvas");
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

  return { DPM: DPM, renderShot: renderShot, composeBitmap: composeBitmap, pageSpec: pageSpec, bitmapToDataUrl: bitmapToDataUrl };
});
