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

  /* ---------- Espacio libre debajo de un texto (19-nov-2026): si el texto no cabe en su caja, puede seguir hacia abajo por el espacio que dejó la persona hasta el siguiente elemento que
     queda debajo y se cruza con él a lo ancho (o hasta el borde de la etiqueta). PURO; se prueba en tests/js/badge_text_fit_check.js. Solo textos sin girar. Devuelve milímetros (≥ 0). */
  const ROOM_GAP_MM = 0.5;
  function roomBelow(el, elements, labelHeightMm) {
    if (((Number(el.rotation) || 0) % 360 + 360) % 360 !== 0) return 0;
    const bottom = (el.y || 0) + (el.height || 0), left = el.x || 0, right = left + (el.width || 0);
    let limit = Number(labelHeightMm) > 0 ? Number(labelHeightMm) : bottom;
    (elements || []).forEach((o) => {
      if (o === el || o.id === el.id) return;
      const oTop = o.y || 0, oLeft = o.x || 0, oRight = oLeft + (o.width || 0);
      if (oTop > (el.y || 0) + 0.01 && oLeft < right - 0.01 && oRight > left + 0.01 && oTop < limit) limit = oTop;
    });
    return Math.max(0, limit - bottom - ROOM_GAP_MM);
  }

  /* ---------- Mayúsculas / minúsculas de cada texto (25-oct-2026): SOLO presentación; los datos de la base y los reportes no cambian. ----------
     text_case: «as_is» (como está en la base, por defecto y en las plantillas viejas) | «upper» | «lower» | «title» (Altas y Bajas).
     Se aplica ANTES del ajuste de texto, así el ajuste mide lo que de verdad se imprime. Puro: se prueba en tests/js/badge_text_case_check.js. */
  // Siglas que se quedan en MAYÚSCULA en «Altas y Bajas». Para agregar una, escríbela aquí (sin importar mayúsculas o puntos).
  const SIGLAS = ['SAS', 'S.A.S.', 'S.A.', 'LTDA', 'ONG', 'EPS', 'IPS', 'DIAN', 'ESAP', 'UNAD', 'DNP'];
  // Partículas que van en minúscula en «Altas y Bajas» (salvo si son la primera palabra).
  const PARTICULAS = ['de', 'del', 'la', 'las', 'los', 'el', 'y', 'e', 'o', 'u'];
  const ROMANOS = /^(?:II|III|IV|VI|VII|VIII|IX|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)$/i;      // los de nombres y cargos (Juan Pablo II, Fase III)
  const TEXT_CASES = ['as_is', 'upper', 'lower', 'title'];
  const up = (t) => t.toLocaleUpperCase('es'), low = (t) => t.toLocaleLowerCase('es');
  const SIGLAS_SET = new Set(SIGLAS.map((x) => up(x).replace(/\./g, '')));
  const PARTICULAS_SET = new Set(PARTICULAS);

  function capitalizeSegment(seg) {                       // primera LETRA en mayúscula, el resto en minúscula (respeta signos al inicio: «(», «¿», comillas)
    const lower = low(seg);
    const i = lower.search(/\p{L}/u);
    return i < 0 ? lower : lower.slice(0, i) + up(lower[i]) + lower.slice(i + 1);
  }
  function titleWord(word, first) {
    const core = word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}.]+$/gu, '');          // sin signos alrededor (se conserva el punto final de «S.A.S.»)
    if (/\p{L}\.\p{L}/u.test(core)) return up(word);                                // con puntos intercalados: S.A.S., S.A., E.U.
    if (SIGLAS_SET.has(up(core).replace(/\./g, ''))) return up(word);                // siglas de la lista
    if (ROMANOS.test(core)) return up(word);                                            // números romanos
    if (!first && PARTICULAS_SET.has(low(core))) return low(word);
    return word.split(/([-'’])/).map((part, i) => (i % 2 ? part : capitalizeSegment(part))).join('');      // José-Luis, O'Brien
  }
  function applyTextCase(text, mode) {
    const raw = text == null ? '' : String(text);
    if (!mode || mode === 'as_is' || TEXT_CASES.indexOf(mode) < 0) return raw;
    const clean = raw.replace(/\s+/g, ' ').trim();                                       // espacios repetidos y en los bordes, fuera
    if (mode === 'upper') return up(clean);
    if (mode === 'lower') return low(clean);
    return clean.split(' ').map((w, i) => titleWord(w, i === 0)).join(' ');
  }
  function textContent(el, data) {                       // lo que se dibuja: el dato (o el texto fijo) con su modo de mayúsculas
    const content = el.type === 'text_static' ? (el.content || '') : resolveVariable(el.variable, data);
    return applyTextCase(content, el.text_case);
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
    const content = textContent(el, data);
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
  function renderTextElement(div, el, data, room) {
    const content = textContent(el, data);                 // con su modo de mayúsculas, ANTES de ajustar (se mide lo que se imprime)
    const meas = canvasMeasurer(el.font_family, el.font_weight), sizePx = (el.font_size || 12) * PX_PER_PT;
    let fit = fitText(content, (el.width || 0) * PX_PER_MM, (el.height || 0) * PX_PER_MM, sizePx, meas);
    let grown = 0;
    if ((fit.shrunk || fit.truncated) && room > 0) {       // no cabe en su caja: usa primero el espacio libre de abajo (más líneas) y solo si aún no alcanza, achica la letra
      const fit2 = fitText(content, (el.width || 0) * PX_PER_MM, ((el.height || 0) + room) * PX_PER_MM, sizePx, meas);
      fit = fit2;
      grown = Math.max(0, Math.min(room, (fit2.lines.length * fit2.size * LINE_HEIGHT) / PX_PER_MM - (el.height || 0)));
    }
    if (grown > 0) { div.style.height = `${(el.height || 0) + grown}mm`; div.dataset.grown = grown.toFixed(1); }
    div.style.fontFamily = `'${el.font_family || 'Roboto'}', ${FONT_STACK_FALLBACK}`;
    div.style.fontSize = `${fit.size}px`;
    div.style.color = el.font_color || '#000000';
    div.style.fontWeight = el.font_weight || 'normal';
    div.style.display = 'flex';
    div.style.alignItems = grown > 0 ? 'flex-start' : 'center';
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

  /* Fase 10 (C): el QR de la escarapela es una vCard (nombre, teléfono si el dato viene, y en NOTE el código de siempre) para poder guardar el contacto al escanear con el celular.
     Los lectores de Golden (qr.js) sacan el código de NOTE y siguen aceptando el formato anterior. Nivel de corrección «L» (la vCard es más larga y así el QR queda en una versión más chica);
     el tamaño del elemento y de la etiqueta NO cambia. Sin vcard.js cargado se dibuja el formato anterior. UTF-8 para las tildes y la ñ. */
  /* 19-nov-2026: cada QR elige qué datos lleva su vCard (propiedad `vcard_fields` del elemento; el nombre va siempre). Sin la propiedad: nombre y teléfono, como antes de agregar correo, empresa y rol.
     `vcard: false` = QR solo con el código (sin vCard): el más chico y el que mejor lee el lector. Cuantos más datos, más cuadritos (versión más alta): ver qrDensity. */
  const VCARD_FIELDS = ['org', 'title', 'phone', 'email', 'categories'];
  const DEFAULT_VCARD_FIELDS = ['phone'];
  /* 18-nov-2026: cada QR elige CÓMO se arma (propiedad `qr_mode` del elemento; sin ella: vCard, y `vcard: false` de antes = solo el código):
       vcard   contacto completo (los datos que se marquen en `vcard_fields`)      mecard  contacto corto (nombre, teléfono, correo)
       link    solo el enlace a la tarjeta de la persona (QR chico, sin límite de datos; los datos salen solo si ella aceptó compartirlos)
       code    solo el código (el más chico y el que mejor lee el lector de la puerta)
     Dos QR en la misma escarapela = dos elementos «Código QR», cada uno con su modo. Si un modo no se puede armar (sin vcard.js, sin enlace público) se cae a «solo el código». */
  const QR_MODES = ['vcard', 'mecard', 'link', 'code'];
  function qrMode(el) { return el && QR_MODES.indexOf(el.qr_mode) >= 0 ? el.qr_mode : (el && el.vcard === false ? 'code' : 'vcard'); }
  function qrText(el, payload, person) {
    const V = (window && window.GWVcard) || (typeof globalThis !== 'undefined' ? globalThis.GWVcard : null) || null;
    const mode = qrMode(el), p = person || {};
    if (!V || mode === 'code') return { text: payload, card: false, level: 'M' };
    if (mode === 'link') {
      if (!p.card_url) return { text: payload, card: false, level: 'M' };
      return { text: V.buildLink(p.card_url, payload), card: false, level: 'M' };
    }
    const fields = el && Array.isArray(el.vcard_fields) ? el.vcard_fields : DEFAULT_VCARD_FIELDS, has = (k) => fields.indexOf(k) >= 0;
    if (mode === 'mecard') return { card: true, level: V.QR_LEVEL, text: V.buildMecard({ first_name: p.first_name, last_name: p.last_name, phone: has('phone') ? p.phone : '', email: has('email') ? p.email : '', note: payload }) };
    return { card: true, level: V.QR_LEVEL, text: V.build({ first_name: p.first_name, last_name: p.last_name, phone: has('phone') ? p.phone : '', email: has('email') ? p.email : '', org: has('org') ? p.entity : '',
      title: has('title') ? p.role : '', categories: has('categories') ? p.categories : '', note: payload }) };
  }
  /* Qué tan apretado queda un QR: versión (1-40) y cuadritos por lado. Hasta la 8 se lee bien en la etiqueta; de la 11 en adelante, mal en celulares y lectores. `level` = nivel de corrección ('L'|'M'); true = 'L'. */
  function qrDensity(text, level) {
    if (typeof qrcode === 'undefined') return null;
    const lv = level === true ? 'L' : (level === false || !level ? 'M' : level);
    const prev = qrcode.stringToBytes;
    if (qrcode.stringToBytesFuncs && qrcode.stringToBytesFuncs['UTF-8']) qrcode.stringToBytes = qrcode.stringToBytesFuncs['UTF-8'];
    try { const q = qrcode(0, lv); q.addData(text); q.make(); const n = q.getModuleCount(); return { version: (n - 17) / 4, modules: n, level: n <= 45 ? 'good' : n <= 53 ? 'ok' : 'dense' }; }
    catch (e) { return null; } finally { qrcode.stringToBytes = prev; }
  }
  function drawQr(holder, payload, person, el) {
    const t = qrText(el, payload, person), text = t.text;
    const prev = qrcode.stringToBytes;
    if (qrcode.stringToBytesFuncs && qrcode.stringToBytesFuncs['UTF-8']) qrcode.stringToBytes = qrcode.stringToBytesFuncs['UTF-8'];
    try {
      const qr = qrcode(0, t.level || 'M');
      qr.addData(text);
      qr.make();
      holder.innerHTML = qr.createSvgTag({ scalable: true });
    } finally { qrcode.stringToBytes = prev; }
    const svg = holder.querySelector('svg');
    if (svg) { svg.style.width = '100%'; svg.style.height = '100%'; }
  }

  function renderQr(div, el, data, opts) {
    const holder = document.createElement('div');
    holder.setAttribute('data-gw-qr', '1'); holder._gwEl = el; holder._gwData = data;          // la escarapela digital vuelve a dibujar este QR con cada código nuevo (redrawQrs)
    holder.style.cssText = 'width:100%; height:100%; display:flex; align-items:center; justify-content:center;';
    div.appendChild(holder);
    const variables = (el.variables && el.variables.length ? el.variables : ['id']);
    const value = (opts && typeof opts.qrPayload === 'function' ? opts.qrPayload(el) : '') || variables.map(v => resolveVariable(v, data)).join('|') || 'PREVIEW';
    if (typeof qrcode === 'undefined') { holder.innerText = 'QR'; return; }
    try {
      drawQr(holder, value, data, el);
    } catch (e) {
      holder.innerText = 'QR';
    }
  }

  /* Escarapela digital: los QR de la plantilla llevan el código DINÁMICO (cambia cada 30 s) con el mismo modo del diseño (vCard, MECARD, enlace, solo código). Devuelve cuántos QR volvió a dibujar. */
  function redrawQrs(root, payload) {
    let n = 0;
    root.querySelectorAll('[data-gw-qr]').forEach((h) => { try { drawQr(h, payload, h._gwData, h._gwEl); n++; } catch (e) { /* queda el anterior */ } });
    return n;
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

    if (el.type === 'text_static' || el.type === 'text_variable') renderTextElement(div, el, data, opts.room || 0);
    else if (el.type === 'image_static') renderImageStatic(div, el, opts);
    else if (el.type === 'image_variable') renderImageVariable(div, el, data, opts);
    else if (el.type === 'qr') renderQr(div, el, data, opts);
    else if (el.type === 'barcode') renderBarcode(div, el, data);

    /* Un elemento GIRADO no recorta lo que sobresale (25-oct-2026, QL-800: «DRÍGL», «LAMIZ»): html2canvas 1.4.1 aplica el `overflow: hidden` de un elemento con `transform`
       usando la caja SIN girar, así que la impresión cortaba lo que la pantalla mostraba completo. El ajuste de texto (fitText) ya garantiza que el contenido cabe en su caja,
       calculado en los ejes del propio elemento antes de girarlo; el recorte no hace falta. */
    if (((Number(el.rotation) || 0) % 360 + 360) % 360 !== 0) div.style.overflow = 'visible';
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
    const all = template.elements || [];
    sorted.forEach(el => container.appendChild(renderElement(el, data, Object.assign({}, opts, { room: (el.type === 'text_static' || el.type === 'text_variable') ? roomBelow(el, all, template.height_mm) : 0 }))));
  }

  /* Espera a que las tipografías de la plantilla (normal y negrita) estén cargadas ANTES de dibujar o imprimir: si no, el navegador usa una de respaldo y la etiqueta impresa cambia de tipografía. */
  function loadFonts(template) {
    if (!(typeof document !== 'undefined' && document.fonts && document.fonts.load)) return Promise.resolve();
    const fams = Array.from(new Set((template.elements || []).filter(e => e.font_family).map(e => String(e.font_family).replace(/'/g, ''))));
    const loads = [];
    fams.forEach(f => { loads.push(document.fonts.load(`400 16px '${f}'`)); loads.push(document.fonts.load(`700 16px '${f}'`)); });
    return Promise.all(loads).then(() => undefined, () => undefined);
  }

  /* La plantilla VIGENTE, siempre pedida al servidor (25-oct-2026: tras cambiar la orientación en el diseñador, la primera etiqueta de un Registro ya abierto pudo salir con la
     geometría anterior). Sin caché del navegador (`no-store`) y con un parámetro único para que ningún intermediario devuelva una copia; el servidor también responde `no-store`.
     Quien imprime arma la etiqueta y calcula el giro automático con ESTA misma plantilla (su `updated_at` queda en la respuesta). */
  function fetchTemplate(eventId, category, extra) {
    const qs = new URLSearchParams();
    if (category) qs.set('category', category);
    Object.keys(extra || {}).forEach((k) => qs.set(k, extra[k]));
    qs.set('_', String(Date.now()));
    return fetch(`/api/events/${eventId}/badge-template?${qs.toString()}`, { cache: 'no-store' });
  }

  window.BadgeRender = { resolveVariable, renderElement, renderBadge, loadFonts, fetchTemplate, applyTextCase, textContent, SIGLAS, PARTICULAS, TEXT_CASES, fitText, wrapWords, roomBelow, qrText, qrMode, QR_MODES, qrDensity, redrawQrs, VCARD_FIELDS, DEFAULT_VCARD_FIELDS, textHeightMm, LINE_HEIGHT, MIN_RATIO };

  /* Disparo de impresión (Historia 2.2) — compartido por los 4 puntos donde un registro puede
     terminar exitosamente (escáner facial, cédula, alta manual, botón "Acreditar" del
     Directorio): abre badge_print.html en una ventana aparte para no sacar al digitador de la
     pantalla de Registro. `window.EVENT_AUTO_PRINT` lo inyecta kiosk_registro.html — si está
     activo, se abre SOLA; si no, queda disponible el botón "Imprimir Escarapela" de siempre
     (la impresión NUNCA es automática por defecto, ver CLAUDE.md/brief de Sprint 2). */
  function printWindowUrl(userId) {
    return `/kiosk/${window.EVENT_ID}/escarapela/imprimir/${encodeURIComponent(userId)}`;
  }
  function printBatchUrl(userIds) {                       // UNA ventana con una hoja por escarapela (hasta 50)
    const ids = userIds.map(String);
    return `/kiosk/${window.EVENT_ID}/escarapela/imprimir/${encodeURIComponent(ids[0])}?users=${ids.map(encodeURIComponent).join(',')}`;
  }
  /* Ventana de impresión con NOMBRE FIJO (29-oct-2026, celular: cada impresión dejaba una ventana abierta y se acumulaban). `window.open(url, 'goldenweb_print', …)` reutiliza la misma ventana
     y, si el navegador abre otra, se cierra la anterior antes. SIN `noopener`: con él el navegador ignora el nombre (siempre una nueva) y no se puede cerrar la anterior; la página de impresión
     es nuestra (mismo origen). La propia página se cierra al terminar (afterprint) y por tiempo máximo (templates/badge_print.html). */
  const PRINT_WINDOW = 'goldenweb_print';
  let printWin = null;
  /* Ventana "preparada" (PR3, causa C de docs/etapa/0A): `primeWindow()` abre la ventana de impresión EN BLANCO dentro del gesto del usuario (clic/Enter/lector), antes de cualquier llamada de
     red, y `openPrintTab(url)` la navega después. Así el navegador no la toma por emergente bloqueada aunque la red tarde más de ~5 s. Mismo nombre fijo `goldenweb_print` y mismas medidas. Si el
     flujo no termina en una impresión, `cancelPrimed()` la cierra; un temporizador de seguridad la cierra a los 25 s. */
  let primed = null, primedKeep = false, primedTimer = null;
  function dropPrimed() {
    if (primedTimer) clearTimeout(primedTimer);
    primedTimer = null;
    const w = primed;
    primed = null; primedKeep = false;
    try { if (w && !w.closed) w.close(); } catch (e) { /* ya cerrada */ }
  }
  function primeWindow() {
    if (!window.EVENT_AUTO_PRINT) return null;                 // solo si se va a imprimir (la bandera se refresca con cada sondeo del directorio)
    if (primed && !primed.closed) return primed;
    let w = null;
    try { w = window.open('about:blank', PRINT_WINDOW, 'width=480,height=720'); } catch (e) { w = null; }
    primed = w || null; primedKeep = false;
    if (primed) primedTimer = setTimeout(dropPrimed, 25000);
    return primed;
  }
  function holdPrimed() { if (primed) primedKeep = true; }
  function cancelPrimed() { if (!primedKeep) dropPrimed(); }          // el flujo terminó sin pedir impresión: se cierra la ventana en blanco (si maybeAutoPrint ya la tomó, se respeta)
  function openPrintTab(url) {
    if (primed && !primed.closed) {                             // la ventana abierta en el gesto: se navega a la página de impresión
      const w = primed;
      if (primedTimer) clearTimeout(primedTimer);
      primedTimer = null; primed = null; primedKeep = false;
      try { w.location.href = url; printWin = w; return w; } catch (e) { /* no se pudo navegar: se abre de la forma de siempre */ }
    }
    try { if (printWin && !printWin.closed) printWin.close(); } catch (e) { /* otra referencia: se sigue */ }
    let w = null;
    try { w = window.open(url, PRINT_WINDOW, 'width=480,height=720'); } catch (e) { w = null; }
    printWin = w;
    return w;
  }

  async function logPrint(userId) {
    try {
      await (window.gwFetch || fetch)(`/api/users/${encodeURIComponent(userId)}/print-log?event_id=${window.EVENT_ID}`, { method: 'POST' }, 'Impresión de escarapela');          // sin red se anota y se envía al volver la conexión
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
        if (countData.blocked) { if (typeof showToast === 'function') showToast(countData.blocked, 'error'); return; }          // p. ej. «aún no está registrado»: no se abre la ventana
        let approved = false;
        if (countData.times_printed > 0 && window.GWReprint) {          // Fase 1B: reimpresión deshabilitada → «No se puede reimprimir» + «Solicitar permiso» (static/js/reprint.js)
          const g = await window.GWReprint.check(userId, countData);
          if (!g.ok) return;
          approved = g.approved;
        }
        if (countData.times_printed > 0 && !approved) {
          const timesText = `${countData.times_printed} ${countData.times_printed === 1 ? 'vez' : 'veces'}`;
          const proceed = await window.showConfirm(
            `⚠️ Ya se ha realizado impresión de esta escarapela (${timesText}).<br><br>¿Deseas imprimir de nuevo?`,
            { variant: 'warning', confirmLabel: 'Sí, imprimir de nuevo' }
          );
          if (!proceed) return;
        }
      }
    } catch (e) { /* si falla la consulta del conteo, no bloquea la impresión */ }
    if (window.GWReprint && !(await window.GWReprint.use(userId))) return;          // Fase 1B: gasta el permiso aprobado (solo si el evento tiene la reimpresión deshabilitada)
    await logPrint(userId);
    openPrintTab(printWindowUrl(userId));
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
  const lockReleasers = new Map();               // key -> función que suelta el candado del navegador de ESTA pestaña
  /* PR3 (causa B): el candado se CONFIRMA después del éxito. `claimTicket` lo toma de forma provisional (misma ventana de 30 s, para que dos llamadas casi simultáneas no impriman las dos) y
     devuelve `{commit, release}` o `null` si otra llamada ya lo tiene: `commit()` lo deja firme desde el momento del éxito; `release()` lo suelta (la comprobación falló, la ventana se bloqueó, el
     servidor no confirmó o la acreditación se deshizo) para que el reintento no quede bloqueado en silencio. */
  function claimTicket(userId) {
    const key = `${window.EVENT_ID}:${userId}`;
    const now = Date.now();
    if ((claims.get(key) || 0) > now) return Promise.resolve(null);
    const until = now + CLAIM_MS;
    claims.set(key, until);
    const ticket = {
      commit() { claims.set(key, Date.now() + CLAIM_MS); },
      release() { claims.delete(key); const r = lockReleasers.get(key); if (r) { lockReleasers.delete(key); r(); } },
    };
    if (!(window.navigator && navigator.locks)) return Promise.resolve(ticket);
    return new Promise((resolve) => {
      navigator.locks.request(`gw-print-${key}`, { ifAvailable: true }, (lock) => {
        if (!lock) { claims.delete(key); resolve(null); return null; }
        resolve(ticket);
        return new Promise((release) => { lockReleasers.set(key, release); setTimeout(release, CLAIM_MS); });          // el candado dura la ventana, se suelta solo o con release()
      }).catch(() => resolve(ticket));
    });
  }
  function claim(userId) { return claimTicket(userId).then((t) => { if (t) t.commit(); return !!t; }); }       // forma de siempre: toma y confirma de una vez
  function releaseClaim(userId) {                // «Deshacer» una acreditación: la misma persona puede volver a imprimirse sola enseguida
    const key = `${window.EVENT_ID}:${userId}`;
    claims.delete(key);
    const r = lockReleasers.get(key);
    if (r) { lockReleasers.delete(key); r(); }
  }
  const manualBusy = new Set();
  function beginManual(userId) {                  // el botón «Imprimir»: un toque a la vez por persona (3 s)
    if (manualBusy.has(userId)) return false;
    manualBusy.add(userId);
    setTimeout(() => manualBusy.delete(userId), 3000);
    return true;
  }
  async function printNow(userId) {
    if (window.GWReprint && !(await window.GWReprint.auto(userId))) return null;     // Fase 1B: reimpresión deshabilitada → la autoimpresión no repite sola a quien ya se imprimió (null = no se imprimió)
    await logPrint(userId);
    return openPrintTab(printWindowUrl(userId));                                     // devuelve la ventana (null = el navegador la bloqueó)
  }
  /* Banderas del evento que decide el SERVIDOR (PR3, causa A): `window.EVENT_AUTO_PRINT` ya no es la verdad (la página lo escribe una vez al cargar). Cada respuesta de checkin-cedula, register, PATCH
     status y undo trae `auto_print`/`auto_register`, y cada sondeo del directorio (/users/changes) trae `flags`: aquí se copian a las variables de la página y se avisa (gw:flags) para repintar
     los interruptores del coordinador. */
  function setFlags(flags) {
    if (!flags || typeof flags !== 'object') return;
    let changed = false;
    const auto_print = flags.auto_print !== undefined ? flags.auto_print : flags.autoPrint;
    const auto_register = flags.auto_register !== undefined ? flags.auto_register : flags.autoRegister;
    if (typeof auto_print === 'boolean' && window.EVENT_AUTO_PRINT !== auto_print) { window.EVENT_AUTO_PRINT = auto_print; changed = true; }
    if (typeof auto_register === 'boolean' && window.EVENT_AUTO_REGISTER !== auto_register) { window.EVENT_AUTO_REGISTER = auto_register; changed = true; }
    if (changed && typeof window.dispatchEvent === 'function' && typeof window.CustomEvent === 'function') { try { window.dispatchEvent(new window.CustomEvent('gw:flags', { detail: { auto_print, auto_register } })); } catch (e) { /* sin evento */ } }
  }
  /* ¿Se imprime solo? Manda la respuesta del servidor (`opts.auto`); sin ella (escáner facial, que no la trae) vale la bandera de la página, que se mantiene al día con cada sondeo. */
  function resolveAuto(opts) {
    if (opts && typeof opts.auto === 'boolean') { setFlags({ auto_print: opts.auto }); return opts.auto && !opts.skip; }          // `skip`: la categoría de esta persona tiene apagada la impresión automática (la bandera del evento no cambia)
    return !!window.EVENT_AUTO_PRINT;
  }
  /* Impresión automática por CATEGORÍA (formulario por categoría): si la respuesta del servidor ya trae la decisión (`opts.auto` booleano) se usa; si no (escáner facial) y alguna categoría tiene la
     impresión automática apagada (`window.EVENT_AUTOPRINT_RULES`), se pregunta al servidor por esta persona. Sin reglas no hay consulta alguna. */
  function categorySkips(userId, opts) {
    if (opts && typeof opts.auto === 'boolean') return Promise.resolve(!!opts.skip);
    if (!window.EVENT_AUTOPRINT_RULES || typeof fetch !== 'function') return Promise.resolve(false);
    return fetch(`/api/events/${window.EVENT_ID}/users/${encodeURIComponent(userId)}/print-flow`, { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : {})).then((d) => !!d.auto_print_skip).catch(() => false);
  }
  function maybeAutoPrint(userId, opts) {
    if (!resolveAuto(opts)) { cancelPrimed(); return Promise.resolve(false); }
    primedKeep = true;                                           // esta llamada se queda con la ventana preparada
    return categorySkips(userId, opts).then((skip) => (skip ? null : claimTicket(userId))).then(async (ticket) => {
      if (!ticket) { dropPrimed(); return false; }
      let w;
      try { w = await printNow(userId); } catch (e) { w = null; }
      if (w === null) { ticket.release(); dropPrimed(); return false; }         // la ventana se bloqueó: el candado no se gasta
      ticket.commit();
      return true;
    });
  }

  window.BadgePrint = { printWindowUrl, printBatchUrl, openPrintTab, openPrintWindow, openNow, maybeAutoPrint, claim, claimTicket, releaseClaim, beginManual, printNow, primeWindow, holdPrimed, cancelPrimed, dropPrimed, setFlags, resolveAuto };
  if (typeof module === 'object' && module.exports) module.exports = window.BadgeRender;           // node: tests/js/badge_text_fit_check.js
})(typeof window !== 'undefined' ? window : globalThis);
