/* Renderizado de UNA escarapela a partir de una plantilla (BadgeTemplate/SavedBadgeTemplate) +
   los datos de una persona — compartido entre el editor (badge_editor.html, con datos de
   muestra o vacíos) y la impresión real (badge_print.html, con los datos reales de quien se
   acaba de registrar). Mismo código en los dos lados a propósito: así el editor SIEMPRE muestra
   fielmente cómo va a quedar impreso. El editor le agrega arrastre/selección ENCIMA de lo que
   esto devuelve — este módulo solo sabe dibujar, no sabe de edición. */
(function (window) {
  const FONT_STACK_FALLBACK = 'sans-serif';
  const LINE_HEIGHT = 1.15;                   // alto de línea de los textos (el mismo para medir y para dibujar)
  const MIN_RATIO = 0.6;                      // la letra puede bajar hasta el 60 % del tamaño elegido antes de recortar con «…» (era 40 %: demasiado)
  const FIT_MODES = ['grow', 'shrink', 'single'];     // «Ajuste» por texto: crecer hacia abajo | reducir para caber | una línea
  const PX_PER_MM = 96 / 25.4, PX_PER_PT = 96 / 72;

  /* ---------- Ajuste de los textos a su caja (25-oct-2026: «ningún texto se corta», y el orden nuevo del mismo día). PURO: recibe cómo medir un texto a un tamaño dado; se prueba en
     tests/js/badge_text_fit_check.js. Orden: (a) partir por palabras en varias líneas con el tamaño DISEÑADO; (b) si no cabe, dejar CRECER la caja hacia abajo hasta el espacio libre
     (`opts.maxH`: el siguiente elemento que estorbe o el borde de la etiqueta); (c) solo entonces reducir la letra, con piso del 60 % (y el que ponga `opts.floorPx`); (d) «…» solo como
     último recurso (`truncated`, para avisar). Modos por texto (`fit_mode`): «grow» (crecer; lo normal en los textos variables), «shrink» (reducir para caber en su caja) y «single» (una línea).
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
  function fitText(text, boxW, boxH, sizePx, measureAt, opts) {
    opts = opts || {};
    const mode = FIT_MODES.indexOf(opts.mode) >= 0 ? opts.mode : 'shrink';
    const words = String(text == null ? '' : text).trim().split(/\s+/).filter(Boolean);
    const base = { size: sizePx, shrunk: false, truncated: false, grown: false, heightPx: boxH, ratio: 1, mode };
    if (!words.length || !(boxW > 0) || !(boxH > 0)) return Object.assign(base, { lines: words.length ? [words.join(' ')] : [] });
    const growLimit = mode === 'grow' ? Math.max(boxH, opts.maxH || boxH) : boxH;
    const startPx = opts.fixedPx || sizePx;
    const minPx = opts.fixedPx ? opts.fixedPx : Math.min(sizePx, Math.max(sizePx * MIN_RATIO, opts.floorPx || 0));
    const tryAt = (px, limitH) => {
      const m = (t) => measureAt(t, px);
      let lines;
      if (mode === 'single') { lines = [words.join(' ')]; if (m(lines[0]) > boxW) return null; }
      else {
        if (words.some((w) => m(w) > boxW)) return null;                    // una palabra más ancha que la caja: a este tamaño no cabe
        lines = wrapWords(words, boxW, m);
      }
      return lines.length * px * LINE_HEIGHT <= limitH + 0.01 ? lines : null;
    };
    const done = (lines, px, extra) => Object.assign(base, { lines, size: px, ratio: px / sizePx, shrunk: px < sizePx - 1e-9 }, extra || {});
    let lines = tryAt(startPx, boxH);
    if (lines) return done(lines, startPx);                                  // (a) cabe tal cual
    if (mode === 'grow' && growLimit > boxH && (lines = tryAt(startPx, growLimit))) return done(lines, startPx, { grown: true, heightPx: lines.length * startPx * LINE_HEIGHT });      // (b) la caja crece
    if (minPx < startPx && tryAt(minPx, growLimit)) {                        // (c) el tamaño más grande que cabe (búsqueda binaria)
      let lo = minPx, hi = startPx;
      for (let i = 0; i < 16; i++) { const mid = (lo + hi) / 2; if (tryAt(mid, growLimit)) lo = mid; else hi = mid; }
      lines = tryAt(lo, growLimit);
      return done(lines, lo, { grown: lines.length * lo * LINE_HEIGHT > boxH + 0.01, heightPx: Math.max(boxH, mode === 'grow' ? lines.length * lo * LINE_HEIGHT : boxH) });
    }
    const px = minPx, m = (t) => measureAt(t, px), ELL = '…';                // (d) ni con la letra mínima: lo que cabe y «…»
    const maxLines = Math.max(1, Math.floor((growLimit + 0.01) / (px * LINE_HEIGHT)));
    const all = mode === 'single' ? [words.join(' ')] : wrapWords(words, boxW, m);
    const clip = (t) => {                                                    // lo más largo que cabe, con «…» al final
      let c = t;
      while (c.length > 1 && m(c + ELL) > boxW) c = c.slice(0, -1);
      return c.replace(/\s+$/, '') + ELL;
    };
    lines = all.slice(0, maxLines).map((t, i) => ((i === maxLines - 1 && all.length > maxLines) || m(t) > boxW ? clip(t) : t));
    return done(lines, px, { truncated: true, grown: lines.length * px * LINE_HEIGHT > boxH + 0.01, heightPx: Math.max(boxH, mode === 'grow' ? lines.length * px * LINE_HEIGHT : boxH) });
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
  const isTextEl = (e) => e.type === 'text_static' || e.type === 'text_variable';
  const fitModeOf = (el) => (FIT_MODES.indexOf(el.fit_mode) >= 0 ? el.fit_mode : (el.type === 'text_variable' ? 'grow' : 'shrink'));          // por defecto, los textos variables crecen hacia abajo
  function boundsOf(e) {                                   // cuadro que envuelve al elemento YA girado (mm)
    const w = Number(e.width) || 0, h = Number(e.height) || 0, a = ((Number(e.rotation) || 0) * Math.PI) / 180;
    const bw = Math.abs(w * Math.cos(a)) + Math.abs(h * Math.sin(a)), bh = Math.abs(w * Math.sin(a)) + Math.abs(h * Math.cos(a));
    const cx = (Number(e.x) || 0) + w / 2, cy = (Number(e.y) || 0) + h / 2;
    return { left: cx - bw / 2, right: cx + bw / 2, top: cy - bh / 2, bottom: cy + bh / 2 };
  }
  /* Espacio libre debajo de un texto (mm): hasta el siguiente elemento que se le cruce por debajo o hasta el borde de la etiqueta menos un margen (el de arriba del primer elemento, mínimo 3 mm). Solo crece un texto SIN giro. */
  const MIN_EDGE_MM = 3;
  function freeHeightMm(el, template) {
    if (Number(el.rotation) % 360) return Number(el.height) || 0;
    const own = boundsOf(el);
    const els = template.elements || [];
    const topMargin = els.length ? Math.max(0, Math.min.apply(null, els.map((o) => boundsOf(o).top))) : 0;
    const edge = Math.max(MIN_EDGE_MM, topMargin);                                       // crecer nunca pega el texto al borde: deja el margen de arriba del primer elemento (mínimo 3 mm)
    let bottom = (Number(template.height_mm) || (own.bottom + edge)) - edge;
    (template.elements || []).forEach((o) => {
      if (o === el || o.id === el.id) return;
      const b = boundsOf(o);
      const overlapsX = b.left < own.right - 0.1 && b.right > own.left + 0.1;
      if (overlapsX && b.top >= own.bottom - 0.5) bottom = Math.min(bottom, b.top - 0.5);          // lo que empieza a partir del final de este texto
    });
    return Math.max(Number(el.height) || 0, bottom - own.top);
  }
  /* PLAN de todos los textos de la plantilla con los datos de UNA persona (25-oct-2026): cada uno se ajusta con su modo, y entre todos se cuida la JERARQUÍA del diseño — un texto cuyo
     tamaño de diseño es mayor que el de otro nunca se imprime menor que ese otro (el nombre nunca queda más chico que «MESA») — y los que comparten tamaño, fuente y peso (nombre y apellido)
     quedan PAREJOS. Devuelve Map(id → resultado de fitText + `ratio`). Es lo que usan el diseñador (con sus avisos), la vista previa, la QL-800 y el controlador. */
  function planText(template, data) {
    const plan = new Map();
    const texts = (template.elements || []).filter(isTextEl);
    const designPx = (e) => (e.font_size || 12) * PX_PER_PT;
    const groups = new Map();
    texts.forEach((e) => { const k = designPx(e) + '|' + (e.font_family || 'Roboto') + '|' + (e.font_weight || 'normal'); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(e); });
    const ordered = Array.from(groups.values()).sort((a, b) => designPx(a[0]) - designPx(b[0]));
    let floorFromSmaller = 0;
    ordered.forEach((members) => {
      const run = (e, fixedPx) => {
        const measure = canvasMeasurer(e.font_family, e.font_weight), mode = fitModeOf(e);
        const go = (floorPx) => fitText(textContent(e, data), (e.width || 0) * PX_PER_MM, (e.height || 0) * PX_PER_MM, designPx(e), measure,
          { mode, maxH: freeHeightMm(e, template) * PX_PER_MM, floorPx, fixedPx });
        const r = go(floorFromSmaller);
        // la jerarquía es un piso BLANDO: si por cuidarla habría que cortar con «…», «…» es el último recurso y se baja hasta el 60 % del diseño
        return r.truncated && floorFromSmaller > designPx(e) * MIN_RATIO && !fixedPx ? go(0) : r;
      };
      let fits = members.map((e) => run(e));
      const common = Math.min.apply(null, fits.map((f) => f.size));
      if (members.length > 1 && fits.some((f) => Math.abs(f.size - common) > 1e-6)) fits = members.map((e) => run(e, common));          // parejos
      members.forEach((e, i) => plan.set(e.id, fits[i]));
      floorFromSmaller = Math.max(floorFromSmaller, common);
    });
    return plan;
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
  function renderTextElement(div, el, data, plan) {
    const content = textContent(el, data);                 // con su modo de mayúsculas, ANTES de ajustar (se mide lo que se imprime)
    const fit = (plan && plan.get(el.id)) || fitText(content, (el.width || 0) * PX_PER_MM, (el.height || 0) * PX_PER_MM, (el.font_size || 12) * PX_PER_PT, canvasMeasurer(el.font_family, el.font_weight), { mode: fitModeOf(el) });
    if (fit.grown) div.style.height = (fit.heightPx / PX_PER_MM) + 'mm';          // la caja creció hacia abajo (había espacio libre)
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
    div.dataset.fit = fit.truncated ? 'truncated' : fit.shrunk ? 'shrunk' : fit.grown ? 'grown' : 'ok';
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

    if (el.type === 'text_static' || el.type === 'text_variable') renderTextElement(div, el, data, opts.plan);
    else if (el.type === 'image_static') renderImageStatic(div, el, opts);
    else if (el.type === 'image_variable') renderImageVariable(div, el, data, opts);
    else if (el.type === 'qr') renderQr(div, el, data);
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
    const withPlan = Object.assign({}, opts, { plan: planText(template, data) });                   // el ajuste de TODOS los textos, con la jerarquía y el espacio libre
    sorted.forEach(el => container.appendChild(renderElement(el, data, withPlan)));
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

  window.BadgeRender = { resolveVariable, renderElement, renderBadge, loadFonts, fetchTemplate, applyTextCase, textContent, SIGLAS, PARTICULAS, TEXT_CASES, planText, fitModeOf, FIT_MODES, fitText, wrapWords, textHeightMm, LINE_HEIGHT, MIN_RATIO };

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
