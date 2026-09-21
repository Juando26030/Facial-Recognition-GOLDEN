/* Renderizado de UNA escarapela a partir de una plantilla (BadgeTemplate/SavedBadgeTemplate) +
   los datos de una persona — compartido entre el editor (badge_editor.html, con datos de
   muestra o vacíos) y la impresión real (badge_print.html, con los datos reales de quien se
   acaba de registrar). Mismo código en los dos lados a propósito: así el editor SIEMPRE muestra
   fielmente cómo va a quedar impreso. El editor le agrega arrastre/selección ENCIMA de lo que
   esto devuelve — este módulo solo sabe dibujar, no sabe de edición. */
(function () {
  const FONT_STACK_FALLBACK = 'sans-serif';

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

  function renderTextElement(div, el, data) {
    const content = el.type === 'text_static' ? (el.content || '') : resolveVariable(el.variable, data);
    div.style.fontFamily = `'${el.font_family || 'Roboto'}', ${FONT_STACK_FALLBACK}`;
    div.style.fontSize = `${el.font_size || 12}pt`;
    div.style.color = el.font_color || '#000000';
    div.style.fontWeight = el.font_weight || 'normal';
    div.style.display = 'flex';
    div.style.alignItems = 'center';
    div.style.justifyContent = el.align === 'center' ? 'center' : el.align === 'right' ? 'flex-end' : 'flex-start';
    div.style.textAlign = el.align || 'left';
    div.style.overflow = 'hidden';
    div.style.whiteSpace = 'nowrap';
    div.style.lineHeight = '1.1';
    div.innerText = content;
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
    div.style.cssText = `position:absolute; left:${el.x}mm; top:${el.y}mm; width:${el.width}mm; height:${el.height}mm; transform:rotate(${el.rotation || 0}deg); z-index:${el.z_index || 1}; box-sizing:border-box;`;

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

  window.BadgeRender = { resolveVariable, renderElement, renderBadge };

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
  function maybeAutoPrint(userId) {
    if (!window.EVENT_AUTO_PRINT) return;
    logPrint(userId).then(() => {
      window.open(printWindowUrl(userId), '_blank', 'width=480,height=720,noopener');
    });
  }

  window.BadgePrint = { printWindowUrl, openPrintWindow, maybeAutoPrint };
})();
