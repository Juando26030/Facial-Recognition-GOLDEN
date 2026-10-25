/* Renderizado de UNA escarapela a partir de una plantilla (BadgeTemplate/SavedBadgeTemplate) +
   los datos de una persona — compartido entre el editor (badge_editor.html, con datos de
   muestra o vacíos) y la impresión real (badge_print.html, con los datos reales de quien se
   acaba de registrar). Mismo código en los dos lados a propósito: así el editor SIEMPRE muestra
   fielmente cómo va a quedar impreso. El editor le agrega arrastre/selección ENCIMA de lo que
   esto devuelve — este módulo solo sabe dibujar, no sabe de edición. */
(function (window) {
  const FONT_STACK_FALLBACK = 'sans-serif';
  const LINE_HEIGHT = 1.15;                   // alto de línea de los textos (el mismo para medir y para dibujar)
  const MIN_RATIO = 0.4;                      // la letra puede bajar hasta el 40 % del tamaño elegido antes de recortar con «…»
  const PX_PER_MM = 96 / 25.4, PX_PER_PT = 96 / 72;

  /* ---------- Ajuste de los textos a su caja (25-oct-2026, «ningún texto se corta»). PURO: recibe cómo medir un texto a un tamaño dado; se prueba en tests/js/badge_text_fit_check.js.
     1) baja de línea por palabras (nunca parte una palabra); 2) si aún no cabe, reduce la letra (hasta MIN_RATIO); 3) solo entonces recorta con «…».
     Devuelve las líneas YA partidas: se dibujan con `white-space: pre`, así el editor, la vista previa y la impresión (html2canvas) muestran exactamente las mismas líneas. */
  function wrapWords(words, maxW, measure) {
    const lines = [];
    let cur = '';
    words.forEach((w) => {
      const cand = cur ? cur + ' ' + w : w;
      if (!cur || measure(cand) <= maxW) cur = cand;
      else { lines.push(cur); cur = w; }
    });
    if (cur) lines.push(cur);
    return lines;
  }
  function fitText(text, boxW, boxH, sizePx, measureAt) {
    const words = String(text == null ? '' : text).trim().split(/\s+/).filter(Boolean);
    if (!words.length || !(boxW > 0) || !(boxH > 0)) return { lines: words.length ? [words.join(' ')] : [], size: sizePx, shrunk: false, truncated: false };
    const tryAt = (px) => {
      const m = (t) => measureAt(t, px);
      if (words.some((w) => m(w) > boxW)) return null;                      // una palabra más ancha que la caja: a este tamaño no cabe
      const lines = wrapWords(words, boxW, m);
      return lines.length * px * LINE_HEIGHT <= boxH + 0.01 ? lines : null;
    };
    let lines = tryAt(sizePx);
    if (lines) return { lines, size: sizePx, shrunk: false, truncated: false };
    const minPx = sizePx * MIN_RATIO;
    if (tryAt(minPx)) {                                                      // el tamaño más grande que cabe (búsqueda binaria)
      let lo = minPx, hi = sizePx;
      for (let i = 0; i < 16; i++) { const mid = (lo + hi) / 2; if (tryAt(mid)) lo = mid; else hi = mid; }
      return { lines: tryAt(lo), size: lo, shrunk: true, truncated: false };
    }
    const px = minPx, m = (t) => measureAt(t, px), ELL = '…';                // ni con la letra mínima: lo que cabe y «…»
    const maxLines = Math.max(1, Math.floor((boxH + 0.01) / (px * LINE_HEIGHT)));
    const all = wrapWords(words, boxW, m);
    const clip = (t) => {                                                    // lo más largo que cabe, con «…» al final
      let c = t;
      while (c.length > 1 && m(c + ELL) > boxW) c = c.slice(0, -1);
      return c.replace(/\s+$/, '') + ELL;
    };
    lines = all.slice(0, maxLines).map((t, i) => ((i === maxLines - 1 && all.length > maxLines) || m(t) > boxW ? clip(t) : t));
    return { lines, size: px, shrunk: true, truncated: true };
  }

  let measureCtx = null;
  function canvasMeasurer(family, weight) {
    if (!measureCtx && typeof document !== 'undefined') measureCtx = document.createElement('canvas').getContext('2d');
    const fam = `'${String(family || 'Roboto').replace(/'/g, '')}', ${FONT_STACK_FALLBACK}`;
    return (t, px) => {
      if (!measureCtx) return t.length * px * 0.6;
      measureCtx.font = `${weight === 'bold' ? 700 : 400} ${px}px ${fam}`;
      return measureCtx.measureText(t).width * 1.02;                         // 2 % de holgura: el navegador y el lienzo redondean distinto
    };
  }
  /* Alto (mm) que necesita un texto a su tamaño elegido con ese ancho (para reacomodar al cambiar la orientación). */
  function textHeightMm(el, widthMm, data) {
    const content = el.type === 'text_static' ? (el.content || '') : resolveVariable(el.variable, data);
    const px = (el.font_size || 12) * PX_PER_PT, m = canvasMeasurer(el.font_family, el.font_weight);
    const words = String(content || '').trim().split(/\s+/).filter(Boolean);
    const lines = words.length ? wrapWords(words, widthMm * PX_PER_MM, (t) => m(t, px)).length : 1;
    return (lines * px * LINE_HEIGHT) / PX_PER_MM + 0.6;
  }

  function resolveVariable(varName, data) {
    if (!varName) return '';
    if (!data) return `{${varName}}`;
    if (varName.startsWith('opcional_')) {
      const extras = data.extra_fields || {};
      return extras[varName] != null ? String(extras[varName]) : '';
    }
    const val = data[varName];
    return val != null ? String(val) : '';
  }

  /* Antes: una sola línea sin saltos (`nowrap`), centrada y con lo que sobra escondido: un nombre o una empresa más largos que la caja se cortaban POR LOS DOS LADOS
     («AN SEBAS», «IGARITA ROJA» en la QL-800, 25-oct-2026). Ahora el texto se ajusta a su caja (fitText) y se dibuja con las líneas ya partidas. */
  function renderTextElement(div, el, data) {
    const content = el.type === 'text_static' ? (el.content || '') : resolveVariable(el.variable, data);
    const fit = fitText(content, (el.width || 0) * PX_PER_MM, (el.height || 0) * PX_PER_MM, (el.font_size || 12) * PX_PER_PT, canvasMeasurer(el.font_family, el.font_weight));
    div.style.fontFamily = `'${el.font_family || 'Roboto'}', ${FONT_STACK_FALLBACK}`;
    div.style.fontSize = `${fit.size}px`;
    div.style.color = el.font_color || '#000000';
    div.style.fontWeight = el.font_weight || 'normal';
    div.style.display = 'flex';
    div.style.alignItems = 'center';
    div.style.justifyContent = el.align === 'center' ? 'center' : el.align === 'right' ? 'flex-end' : 'flex-start';
    div.style.textAlign = el.align || 'left';
    div.style.overflow = 'hidden';
    div.style.lineHeight = String(LINE_HEIGHT);
    div.dataset.fit = fit.truncated ? 'truncated' : fit.shrunk ? 'shrunk' : 'ok';
    const span = document.createElement('span');
    span.style.cssText = `display:block; width:100%; white-space:pre; line-height:${LINE_HEIGHT}; text-align:${el.align || 'left'};`;
    span.textContent = fit.lines.join('\n');
    div.appendChild(span);
  }

  function renderImageStatic(div, el, opts) {
    const img = document.createElement('img');
    img.style.cssText = 'width:100%; height:100%; object-fit:contain; display:block;';
    // opts.assetUrl: la escarapela digital pública (/b/<token>) sirve los recursos por su propio enlace autorizado.
    img.src = el.storage_path ? (opts && opts.assetUrl ? opts.assetUrl(el.storage_path) : `/api/badge-assets/${el.storage_path}`) : '';
    img.alt = '';
    div.appendChild(img);
  }

  function renderImageVariable(div, el, data, opts) {
    const img = document.createElement('img');
    img.style.cssText = 'width:100%; height:100%; object-fit:cover; display:block; border-radius:4px; background:#e9e9e9;';
    img.alt = 'Foto';
    if (data && data.has_photo && opts.photoUrl) {
      img.src = opts.photoUrl(data);
    } else if (data && data.has_photo && opts.eventId && data.id) {
      img.src = `/api/users/${encodeURIComponent(data.id)}/photo?event_id=${opts.eventId}`;
    } else if (opts.samplePhotoUrl) {
      img.src = opts.samplePhotoUrl;
    }
    div.appendChild(img);
  }

  function renderQr(div, el, data) {
    const holder = document.createElement('div');
    holder.style.cssText = 'width:100%; height:100%; display:flex; align-items:center; justify-content:center;';
    div.appendChild(holder);
    const variables = (el.variables && el.variables.length ? el.variables : ['id']);
    const value = variables.map(v => resolveVariable(v, data)).join('|') || 'PREVIEW';
    if (typeof qrcode === 'undefined') { holder.innerText = 'QR'; return; }
    try {
      const qr = qrcode(0, 'M');
      qr.addData(value);
      qr.make();
      holder.innerHTML = qr.createSvgTag({ scalable: true });
      const svg = holder.querySelector('svg');
      if (svg) { svg.style.width = '100%'; svg.style.height = '100%'; }
    } catch (e) {
      holder.innerText = 'QR';
    }
  }

  function renderBarcode(div, el, data) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.style.cssText = 'width:100%; height:100%; display:block;';
    div.appendChild(svg);
    const value = resolveVariable(el.variable || 'id', data) || 'PREVIEW';
    if (typeof JsBarcode === 'undefined') { return; }
    try {
      JsBarcode(svg, value, {
        format: (el.format || 'code128').toUpperCase() === 'CODE39' ? 'CODE39' : 'CODE128',
        displayValue: false, margin: 0, height: 100,
      });
    } catch (e) { /* valor no válido para el formato elegido — se deja el svg vacío */ }
  }

  function renderElement(el, data, opts) {
    opts = opts || {};
    const div = document.createElement('div');
    div.className = 'badge-element badge-element-' + el.type;
    div.dataset.elId = el.id;
    div.style.cssText = `position:absolute; left:${el.x}mm; top:${el.y}mm; width:${el.width}mm; height:${el.height}mm; transform:rotate(${el.rotation || 0}deg); transform-origin:50% 50%; z-index:${el.z_index || 1}; box-sizing:border-box;`;

    if (el.type === 'text_static' || el.type === 'text_variable') renderTextElement(div, el, data);
    else if (el.type === 'image_static') renderImageStatic(div, el, opts);
    else if (el.type === 'image_variable') renderImageVariable(div, el, data, opts);
    else if (el.type === 'qr') renderQr(div, el, data);
    else if (el.type === 'barcode') renderBarcode(div, el, data);

    return div;
  }

  function renderBadge(container, template, data, opts) {
    opts = opts || {};
    container.innerHTML = '';
    container.style.width = `${template.width_mm}mm`;
    container.style.height = `${template.height_mm}mm`;
    container.style.position = 'relative';
    container.style.overflow = 'hidden';
    container.style.boxSizing = 'border-box';
    if (template.background_type === 'image' && template.background_value) {
      container.style.backgroundImage = `url(${opts.assetUrl ? opts.assetUrl(template.background_value) : '/api/badge-assets/' + template.background_value})`;
      container.style.backgroundSize = 'cover';
      container.style.backgroundPosition = 'center';
      container.style.backgroundColor = '#ffffff';
    } else {
      container.style.backgroundImage = 'none';
      container.style.backgroundColor = template.background_value || '#ffffff';
    }
    const sorted = (template.elements || []).slice().sort((a, b) => (a.z_index || 0) - (b.z_index || 0));
    sorted.forEach(el => container.appendChild(renderElement(el, data, opts)));
  }

  /* Espera a que las tipografías de la plantilla (normal y negrita) estén cargadas ANTES de dibujar o imprimir: si no, el navegador usa una de respaldo y la etiqueta impresa cambia de tipografía. */
  function loadFonts(template) {
    if (!(typeof document !== 'undefined' && document.fonts && document.fonts.load)) return Promise.resolve();
    const fams = Array.from(new Set((template.elements || []).filter(e => e.font_family).map(e => String(e.font_family).replace(/'/g, ''))));
    const loads = [];
    fams.forEach(f => { loads.push(document.fonts.load(`400 16px '${f}'`)); loads.push(document.fonts.load(`700 16px '${f}'`)); });
    return Promise.all(loads).then(() => undefined, () => undefined);
  }

  window.BadgeRender = { resolveVariable, renderElement, renderBadge, loadFonts, fitText, wrapWords, textHeightMm, LINE_HEIGHT, MIN_RATIO };

  /* Disparo de impresión (Historia 2.2) — compartido por los 4 puntos donde un registro puede
     terminar exitosamente (escáner facial, cédula, alta manual, botón "Acreditar" del
     Directorio): abre badge_print.html en una ventana aparte para no sacar al digitador de la
     pantalla de Registro. `window.EVENT_AUTO_PRINT` lo inyecta kiosk_registro.html — si está
     activo, se abre SOLA; si no, queda disponible el botón "Imprimir Escarapela" de siempre
     (la impresión NUNCA es automática por defecto, ver CLAUDE.md/brief de Sprint 2). */
  function printWindowUrl(userId) {
    return `/kiosk/${window.EVENT_ID}/escarapela/imprimir/${encodeURIComponent(userId)}`;
  }

  async function logPrint(userId) {
    try {
      await fetch(`/api/users/${encodeURIComponent(userId)}/print-log?event_id=${window.EVENT_ID}`, { method: 'POST' });
    } catch (e) { /* no bloquea la impresión si falla el registro del log */ }
  }

  /* Aviso de reimpresión (Sprint 2.4 Fase 3, pedido explícito): antes de abrir la ventana de
     impresión se consulta cuántas veces se imprimió antes esta escarapela EN ESTE evento — si ya
     se imprimió, se avisa con el conteo y el operador decide si de todas formas imprime de nuevo.
     Cada impresión (haya habido aviso o no) se registra vía POST print-log para que el próximo
     conteo sea correcto. SOLO para el botón manual — ver maybeAutoPrint abajo para la
     autoimpresión, que nunca debe pasar por este confirm. */
  async function openPrintWindow(userId) {
    if (!beginManual(userId)) return;
    return openNow(userId);
  }

  async function openNow(userId) {            // lo mismo sin el guardián de doble toque (lo usa el despachador de la impresión compartida, que ya lo aplicó)
    try {
      const countRes = await fetch(`/api/users/${encodeURIComponent(userId)}/print-count?event_id=${window.EVENT_ID}`);
      if (countRes.ok) {
        const countData = await countRes.json();
        if (countData.times_printed > 0) {
          const timesText = `${countData.times_printed} ${countData.times_printed === 1 ? 'vez' : 'veces'}`;
          const proceed = await window.showConfirm(
            `⚠️ Ya se ha realizado impresión de esta escarapela (${timesText}).<br><br>¿Deseas imprimir de nuevo?`,
            { variant: 'warning', confirmLabel: 'Sí, imprimir de nuevo' }
          );
          if (!proceed) return;
        }
      }
    } catch (e) { /* si falla la consulta del conteo, no bloquea la impresión */ }
    await logPrint(userId);
    window.open(printWindowUrl(userId), '_blank', 'width=480,height=720,noopener');
  }

  /* Bug real corregido (2026-09-17, "el módulo de autoimpresión no está sirviendo"): maybeAutoPrint
     llamaba a openPrintWindow, que desde la Fase 3 pregunta "¿deseas imprimir de nuevo?" si la
     persona ya se había impreso antes — un modal que nadie está mirando para confirmar, así que la
     autoimpresión se quedaba esperando en silencio para siempre y nunca abría nada. La
     autoimpresión, por definición, NUNCA debe preguntar nada: si el switch está prendido, se
     imprime directo (se registra el conteo igual, para que el próximo conteo/aviso manual sea
     correcto). Dos escenarios reales (pedido explícito):
     1) auto_print_badge + auto_register: un escaneo con match acredita solo (auto_register) y acá
        se imprime solo también, ambos activados.
     2) auto_print_badge sin auto_register: cualquier acción que deje a alguien "Registrado" —
        escanear y confirmar, alta manual, "Acreditar" en el Directorio, o cambiar el estado a
        "Registrado" desde el modal de Editar — debe imprimir sola apenas eso pasa. Los 5 puntos
        donde el estado puede pasar a "Registrado" ya llaman a esta función (ver app.js y
        directory.js); el fix real estaba acá, no en cuántos sitios la llaman. */
  /* Una impresión automática por persona (23-oct-2026, «doble impresión» del evento): varios caminos de registro pueden llamar a maybeAutoPrint para la MISMA persona casi a la vez (un doble
     clic en «Acreditar», una lectura repetida del lector, dos pestañas del mismo equipo, un refresco). `claim` deja pasar solo la primera en una ventana de 30 s: en memoria (esta pestaña) y con un
     candado del navegador (Web Locks) entre pestañas del mismo equipo. Una reimpresión del botón o de la Cola NO pasa por aquí: es explícita. En el servidor, la impresión compartida tiene su propia
     ventana (print-jobs). */
  const CLAIM_MS = 30000;
  const claims = new Map();
  function claim(userId) {
    const key = `${window.EVENT_ID}:${userId}`;
    const now = Date.now();
    if ((claims.get(key) || 0) > now) return Promise.resolve(false);
    claims.set(key, now + CLAIM_MS);
    if (!(window.navigator && navigator.locks)) return Promise.resolve(true);
    return new Promise((resolve) => {
      navigator.locks.request(`gw-print-${key}`, { ifAvailable: true }, (lock) => {
        if (!lock) { resolve(false); return null; }
        resolve(true);
        return new Promise((release) => setTimeout(release, CLAIM_MS));          // el candado dura la ventana y se suelta solo
      }).catch(() => resolve(true));
    });
  }
  const manualBusy = new Set();
  function beginManual(userId) {                  // el botón «Imprimir»: un toque a la vez por persona (3 s)
    if (manualBusy.has(userId)) return false;
    manualBusy.add(userId);
    setTimeout(() => manualBusy.delete(userId), 3000);
    return true;
  }
  function printNow(userId) {
    return logPrint(userId).then(() => {
      window.open(printWindowUrl(userId), '_blank', 'width=480,height=720,noopener');
    });
  }
  function maybeAutoPrint(userId) {
    if (!window.EVENT_AUTO_PRINT) return;
    claim(userId).then((ok) => { if (ok) printNow(userId); });
  }

  window.BadgePrint = { printWindowUrl, openPrintWindow, openNow, maybeAutoPrint, claim, beginManual, printNow };
  if (typeof module === 'object' && module.exports) module.exports = window.BadgeRender;           // node: tests/js/badge_text_fit_check.js
})(typeof window !== 'undefined' ? window : globalThis);
