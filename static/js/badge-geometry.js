/* Geometría PURA del diseñador de escarapelas (sin navegador; se prueba en tests/js/badge_geometry_check.js): imán/alineación, rotación y paso entre vertical y horizontal.
   Todo en milímetros de la etiqueta. Un elemento es {x, y, width, height, rotation} y gira alrededor de su centro (igual que el `transform: rotate()` con que se dibuja y se imprime). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BadgeGeometry = factory();
})(typeof window !== 'undefined' ? window : this, function () {
  const EPS = 0.01;
  const SNAP_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315];
  const rad = (deg) => (deg * Math.PI) / 180;
  const round = (n, d) => { const f = Math.pow(10, d == null ? 2 : d); return Math.round(n * f) / f; };

  function normAngle(a) { a = Number(a); if (!isFinite(a)) return 0; a = ((a % 360) + 360) % 360; return round(a, 1) === 360 ? 0 : round(a, 1); }

  /* Cuadro que envuelve al elemento YA girado: lo que de verdad ocupa en la etiqueta (para imán, alineación, «fuera de la etiqueta» y recorte). */
  function bounds(el) {
    const w = Number(el.width) || 0, h = Number(el.height) || 0, a = rad(Number(el.rotation) || 0);
    const cos = Math.abs(Math.cos(a)), sin = Math.abs(Math.sin(a));
    const bw = w * cos + h * sin, bh = w * sin + h * cos;
    const cx = (Number(el.x) || 0) + w / 2, cy = (Number(el.y) || 0) + h / 2;
    return { left: cx - bw / 2, right: cx + bw / 2, top: cy - bh / 2, bottom: cy + bh / 2, cx, cy, width: bw, height: bh };
  }

  function isOutside(el, widthMm, heightMm) {
    const b = bounds(el);
    return b.left < -EPS || b.top < -EPS || b.right > widthMm + EPS || b.bottom > heightMm + EPS;
  }

  /* Líneas a las que se pega: centro y bordes de la etiqueta + centro y bordes (ya girados) de los demás elementos. */
  function targets(template, excludeId) {
    const W = template.width_mm, H = template.height_mm;
    const xs = [{ pos: 0, kind: 'label' }, { pos: W / 2, kind: 'label' }, { pos: W, kind: 'label' }];
    const ys = [{ pos: 0, kind: 'label' }, { pos: H / 2, kind: 'label' }, { pos: H, kind: 'label' }];
    (template.elements || []).forEach((o) => {
      if (o.id === excludeId) return;
      const b = bounds(o);
      [b.left, b.cx, b.right].forEach((p) => xs.push({ pos: p, kind: 'element' }));
      [b.top, b.cy, b.bottom].forEach((p) => ys.push({ pos: p, kind: 'element' }));
    });
    return { xs, ys };
  }

  /* El candidato (borde o centro del elemento que se mueve) más cercano a una línea, si está a menos de `thr` mm. Devuelve el desplazamiento y TODAS las líneas que quedan alineadas. */
  function snapAxis(candidates, lines, thr) {
    let best = null;
    candidates.forEach((c) => lines.forEach((t) => {
      const d = t.pos - c;
      if (Math.abs(d) <= thr && (best === null || Math.abs(d) < Math.abs(best))) best = d;
    }));
    if (best === null) return { delta: 0, guides: [] };
    const guides = [];
    lines.forEach((t) => {
      if (candidates.some((c) => Math.abs(c + best - t.pos) < EPS) && !guides.some((g) => Math.abs(g - t.pos) < EPS)) guides.push(t.pos);
    });
    return { delta: best, guides };
  }

  /* Mover: devuelve cuánto hay que correr el elemento (dx, dy en mm) para que se pegue, y las líneas guía (x: verticales, y: horizontales). `thr` en mm (≈ 6 px en pantalla / px por mm). */
  function snapMove(el, template, thr) {
    const b = bounds(el), t = targets(template, el.id);
    const sx = snapAxis([b.left, b.cx, b.right], t.xs, thr), sy = snapAxis([b.top, b.cy, b.bottom], t.ys, thr);
    return { dx: sx.delta, dy: sy.delta, guides: { x: sx.guides, y: sy.guides } };
  }

  /* Redimensionar: se pega el punto que se arrastra (esquina), no el centro. Devuelve el punto ya pegado y las guías. */
  function snapPoint(px, py, template, excludeId, thr) {
    const t = targets(template, excludeId);
    const sx = snapAxis([px], t.xs, thr), sy = snapAxis([py], t.ys, thr);
    return { x: px + sx.delta, y: py + sy.delta, guides: { x: sx.guides, y: sy.guides } };
  }

  /* Botones de alinear respecto a la etiqueta (usan el cuadro ya girado). Devuelve la nueva {x, y}. */
  function align(el, template, mode) {
    const b = bounds(el), W = template.width_mm, H = template.height_mm;
    let dx = 0, dy = 0;
    if (mode === 'left') dx = -b.left;
    else if (mode === 'center') dx = W / 2 - b.cx;
    else if (mode === 'right') dx = W - b.right;
    else if (mode === 'top') dy = -b.top;
    else if (mode === 'middle') dy = H / 2 - b.cy;
    else if (mode === 'bottom') dy = H - b.bottom;
    return { x: round((Number(el.x) || 0) + dx, 3), y: round((Number(el.y) || 0) + dy, 3) };
  }

  /* Rotación: pega a 0/45/90/135/180/225/270/315° con tolerancia de 3°; con Mayús, pasos de 15°. */
  function snapAngle(raw, opts) {
    opts = opts || {};
    const a = normAngle(raw);
    if (opts.shift) return normAngle(Math.round(a / 15) * 15);
    const tol = opts.tol == null ? 3 : opts.tol;
    for (const s of SNAP_ANGLES.concat([360])) if (Math.abs(a - s) <= tol) return normAngle(s);
    return a;
  }
  /* Ángulo (0° = manija arriba, horario) desde el centro del elemento hasta el puntero. */
  function angleFromPointer(cx, cy, px, py) { return normAngle((Math.atan2(py - cy, px - cx) * 180) / Math.PI + 90); }

  /* Cambio de tamaño con el elemento girado: la esquina inferior derecha sigue al puntero y la superior izquierda se queda quieta en la etiqueta. Devuelve {x, y, width, height}. */
  function resizeRotated(el, px, py, minMm) {
    const a = rad(Number(el.rotation) || 0), cos = Math.cos(a), sin = Math.sin(a);
    const w0 = Number(el.width), h0 = Number(el.height);
    const cx0 = el.x + w0 / 2, cy0 = el.y + h0 / 2;
    const ax = cx0 + (-w0 / 2) * cos - (-h0 / 2) * sin, ay = cy0 + (-w0 / 2) * sin + (-h0 / 2) * cos;       // esquina superior izquierda, ya girada
    const dx = px - ax, dy = py - ay;
    const w = Math.max(minMm || 3, dx * cos + dy * sin), h = Math.max(minMm || 3, -dx * sin + dy * cos);
    const cx = ax + (w / 2) * cos - (h / 2) * sin, cy = ay + (w / 2) * sin + (h / 2) * cos;
    return { x: cx - w / 2, y: cy - h / 2, width: w, height: h };
  }

  /* ---------- Vertical ↔ horizontal y «Ajustar a la cinta» (25-oct-2026: la versión anterior intercambiaba ancho y alto de cada caja y los textos quedaban altos y angostos) ----------
     Cada elemento se REUBICA POR PROPORCIÓN: su centro y su ancho se escalan según la relación entre el lienzo viejo y el nuevo (lo centrado sigue centrado); el alto de un texto se
     recalcula según su contenido (`measure(el, anchoMm)`, en el editor con el mismo ajuste de texto que se imprime); fotos, QR y códigos conservan su proporción y solo se achican
     si no caben. Después se corrige lo que quede superpuesto (se baja) y, si aun así algo se sale, se reacomoda en una o dos columnas.
     Cada orientación RECUERDA cómo quedó (`el.layouts`): ida y vuelta sin tocar nada devuelve exactamente el diseño original.
     No se gira nada aquí: al imprimir, la rotación automática (ql-usb.js `layout`: lo apaisado se gira 90°) pone lo horizontal a lo largo de la cinta. */
  const MARGIN = 2, GAP = 1;
  const isText = (e) => e.type === 'text_static' || e.type === 'text_variable';
  const r3 = (n) => round(n, 3);
  const overlaps = (a, b) => a.left < b.right - EPS && b.left < a.right - EPS && a.top < b.bottom - EPS && b.top < a.bottom - EPS;

  function placeCenter(e, cx, cy) { e.x = r3(cx - e.width / 2); e.y = r3(cy - e.height / 2); }
  function clampInside(e, W, H) {
    const b = bounds(e);
    if (b.width <= W + EPS) { if (b.left < 0) e.x -= b.left; else if (b.right > W) e.x -= b.right - W; }
    if (b.height <= H + EPS) { if (b.top < 0) e.y -= b.top; else if (b.bottom > H) e.y -= b.bottom - H; }
    e.x = r3(e.x); e.y = r3(e.y);
  }

  function proportional(o, W, H, nW, nH, measure) {
    const e = Object.assign({}, o);
    const sx = nW / W, sy = nH / H;
    const cx = (o.x + o.width / 2) * sx, cy = (o.y + o.height / 2) * sy;
    if (isText(o)) {
      e.width = Math.min(nW, o.width * sx);
      const need = measure ? measure(e, e.width) : 0;
      e.height = Math.min(nH, Math.max(need, Math.min(o.height, o.height * sy)));
    } else {
      let s = Math.min(1, Math.sqrt(sx * sy));                                // misma superficie de lienzo = mismo tamaño; nunca se agranda
      s = Math.min(s, nW / o.width, nH / o.height);
      e.width = o.width * s; e.height = o.height * s;
    }
    e.width = r3(e.width); e.height = r3(e.height);
    placeCenter(e, cx, cy);
    clampInside(e, nW, nH);
    return e;
  }

  /* Lo que quede encima de otro baja hasta debajo (de arriba a abajo). Devuelve si todo quedó dentro. */
  function unstack(list, H) {
    const placed = [];
    list.slice().sort((a, b) => bounds(a).top - bounds(b).top || bounds(a).left - bounds(b).left).forEach((e) => {
      for (let guard = 0; guard < list.length + 1; guard++) {
        const be = bounds(e);
        const hit = placed.find((p) => overlaps(be, bounds(p)));
        if (!hit) break;
        e.y = r3(e.y + (bounds(hit).bottom + GAP - be.top));
      }
      placed.push(e);
    });
    return list.every((e) => bounds(e).bottom <= H + EPS);
  }

  /* Si al bajar algo se sale: textos apilados en una columna y, en una etiqueta apaisada, fotos/QR/códigos en una columna a la derecha. Lo que no alcanza se achica parejo. */
  function columns(list, nW, nH, measure) {
    const order = list.slice().sort((a, b) => bounds(a).top - bounds(b).top);
    const texts = order.filter(isText), media = order.filter((e) => !isText(e));
    const side = nW > nH && media.length && texts.length;
    const colW = side ? Math.min(nW * 0.4, Math.max(...media.map((e) => e.width))) : 0;
    const avail = nH - 2 * MARGIN;
    const stack = (items, x0, width) => {
      const heights = items.map((e) => e.height);
      const total = heights.reduce((a, h) => a + h, 0) + GAP * Math.max(0, items.length - 1);
      const f = total > avail ? (avail - GAP * Math.max(0, items.length - 1)) / heights.reduce((a, h) => a + h, 0) : 1;
      let y = MARGIN;
      items.forEach((e) => {
        if (isText(e)) { e.width = r3(width); e.height = r3(Math.max(2, (measure ? Math.max(measure(e, e.width), e.height) : e.height) * f)); }
        else { const s = Math.min(f, width / e.width); e.width = r3(e.width * s); e.height = r3(e.height * s); }
        placeCenter(e, x0 + width / 2, y + e.height / 2);
        y += e.height + GAP;
      });
      const spare = avail - (y - GAP - MARGIN);                               // la columna queda centrada a lo alto
      if (spare > EPS) items.forEach((e) => { e.y = r3(e.y + spare / 2); });
    };
    if (side) {
      stack(media, nW - MARGIN - colW, colW);
      stack(texts, MARGIN, nW - 3 * MARGIN - colW);
    } else stack(order, MARGIN, nW - 2 * MARGIN);
    list.forEach((e) => clampInside(e, nW, nH));
  }

  function relayout(template, nW, nH, measure) {
    const W = template.width_mm, H = template.height_mm;
    const list = (template.elements || []).map((o) => proportional(o, W, H, nW, nH, measure));
    if (!unstack(list, nH) || list.some((e) => isOutside(e, nW, nH))) {
      columns(list, nW, nH, measure);
      unstack(list, nH);
    }
    return list;
  }

  const sameSize = (a, b) => Math.abs(a - b) < 0.05;
  /* opts.acrossMm: lo que la cinta imprime a lo ancho (p. ej. 58,9 mm): la dimensión que va a lo ancho de la cinta queda de esa medida (sin encogerse al imprimir).
     opts.measure(el, anchoMm) → alto (mm) que necesita el texto. */
  function convertOrientation(template, toHorizontal, opts) {
    opts = opts || {};
    const W = template.width_mm, H = template.height_mm, from = toHorizontal ? 'vertical' : 'horizontal', to = toHorizontal ? 'horizontal' : 'vertical';
    let nW = Math.max(W, H), nH = Math.min(W, H);
    if (!toHorizontal) { const t = nW; nW = nH; nH = t; }
    if (opts.acrossMm) { if (toHorizontal) nH = opts.acrossMm; else nW = opts.acrossMm; }      // horizontal: el alto va a lo ancho de la cinta; vertical: el ancho
    const els = template.elements || [];
    const remember = (o) => Object.assign({}, o.layouts || {}, { [from]: { x: o.x, y: o.y, width: o.width, height: o.height, w: W, h: H } });
    const saved = els.length && els.every((o) => o.layouts && o.layouts[to] && sameSize(o.layouts[to].w, nW) && sameSize(o.layouts[to].h, nH));
    let elements;
    if (saved) {                                                             // ida y vuelta: lo que el usuario tenía en esa orientación
      elements = els.map((o) => { const l = o.layouts[to]; return Object.assign({}, o, { x: l.x, y: l.y, width: l.width, height: l.height, layouts: remember(o) }); });
    } else {
      elements = relayout(template, nW, nH, opts.measure).map((e, i) => Object.assign(e, { layouts: remember(els[i]) }));
    }
    const doesNotFit = elements.filter((e) => isOutside(e, nW, nH)).map((e) => e.id);
    return { width_mm: r3(nW), height_mm: r3(nH), orientation: to, elements, doesNotFit, restored: !!saved };
  }

  /* «Ajustar a la cinta»: la dimensión que va a lo ancho de la cinta pasa a `acrossMm` y el diseño se reacomoda igual que al cambiar la orientación. */
  function fitToTape(template, acrossMm, opts) {
    opts = opts || {};
    const horizontal = template.width_mm > template.height_mm;
    const nW = horizontal ? template.width_mm : acrossMm, nH = horizontal ? acrossMm : template.height_mm;
    const elements = relayout(template, nW, nH, opts.measure).map((e) => { delete e.layouts; return e; });   // las medidas cambiaron: lo recordado de cada orientación ya no aplica
    return { width_mm: r3(nW), height_mm: r3(nH), elements, doesNotFit: elements.filter((e) => isOutside(e, nW, nH)).map((e) => e.id) };
  }

  /* ---------- Manijas como en PowerPoint (25-oct-2026): cuatro esquinas, cuatro lados y la de giro. En los ejes del PROPIO elemento (si está girado, las manijas giran con él).
     Esquinas: ancho y alto a la vez (con `keepAspect`, en proporción; fotos, QR y códigos siempre). Lados: solo el alto (arriba/abajo) o solo el ancho (izquierda/derecha).
     El lado (o la esquina) opuesto al que se arrastra queda fijo. */
  const HANDLES = { nw: [-1, -1], n: [0, -1], ne: [1, -1], e: [1, 0], se: [1, 1], s: [0, 1], sw: [-1, 1], w: [-1, 0] };
  const KEEP_ASPECT_TYPES = { image_static: true, image_variable: true, qr: true, barcode: true };

  function toWorld(el, lx, ly) {                         // de los ejes del elemento (origen en su centro) a la etiqueta
    const a = rad(Number(el.rotation) || 0), cos = Math.cos(a), sin = Math.sin(a);
    const cx = el.x + el.width / 2, cy = el.y + el.height / 2;
    return { x: cx + lx * cos - ly * sin, y: cy + lx * sin + ly * cos };
  }
  function toLocal(el, px, py, ox, oy) {                 // de la etiqueta a los ejes del elemento, relativo al punto (ox, oy)
    const a = rad(Number(el.rotation) || 0), cos = Math.cos(a), sin = Math.sin(a);
    const dx = px - ox, dy = py - oy;
    return { x: dx * cos + dy * sin, y: -dx * sin + dy * cos };
  }

  /* Dónde va cada manija (mm de la etiqueta). `rotateOffsetMm`: cuánto por encima del borde superior va la de giro. */
  function handlePoints(el, rotateOffsetMm) {
    const out = {};
    Object.keys(HANDLES).forEach((k) => { const [hx, hy] = HANDLES[k]; out[k] = toWorld(el, hx * el.width / 2, hy * el.height / 2); });
    out.rotate = toWorld(el, 0, -el.height / 2 - (rotateOffsetMm || 0));
    return out;
  }

  /* ¿Qué manija del elemento SELECCIONADO hay bajo el puntero? La más cercana dentro de `radiusMm` (zona táctil), o null. Se consulta ANTES que cualquier elemento:
     una manija nunca cede el clic al elemento que esté debajo. */
  function hitHandle(px, py, el, radiusMm, rotateOffsetMm) {
    if (!el) return null;
    const pts = handlePoints(el, rotateOffsetMm);
    let best = null, bestD = Infinity;
    Object.keys(pts).forEach((k) => {
      const d = Math.hypot(pts[k].x - px, pts[k].y - py);
      if (d <= radiusMm + EPS && d < bestD - EPS) { best = k; bestD = d; }
    });
    return best;
  }

  /* Nuevo {x, y, width, height} al arrastrar la manija `handle` hasta el punto (px, py) de la etiqueta. */
  function resizeFromHandle(orig, handle, px, py, opts) {
    opts = opts || {};
    const hv = HANDLES[handle];
    if (!hv) return { x: orig.x, y: orig.y, width: orig.width, height: orig.height };
    const [hx, hy] = hv, min = opts.min || 3, w0 = Number(orig.width), h0 = Number(orig.height);
    const anchor = toWorld(orig, -hx * w0 / 2, -hy * h0 / 2);                  // lo opuesto: queda fijo
    const d = toLocal(orig, px, py, anchor.x, anchor.y);
    let w = hx ? Math.max(min, hx * d.x) : w0, h = hy ? Math.max(min, hy * d.y) : h0;
    if (opts.keepAspect || KEEP_ASPECT_TYPES[orig.type]) {
      const s = hx && hy ? Math.max(w / w0, h / h0) : (hx ? w / w0 : h / h0);
      const sMin = Math.max(min / w0, min / h0);
      const k = Math.max(s, sMin);
      w = w0 * k; h = h0 * k;
    }
    const a = rad(Number(orig.rotation) || 0), cos = Math.cos(a), sin = Math.sin(a);
    const ox = hx * w / 2, oy = hy * h / 2;                                       // del punto fijo al centro nuevo, en los ejes del elemento
    const cx = anchor.x + ox * cos - oy * sin, cy = anchor.y + ox * sin + oy * cos;
    return { x: r3(cx - w / 2), y: r3(cy - h / 2), width: r3(w), height: r3(h) };
  }

  return { bounds, isOutside, targets, snapMove, snapPoint, snapAxis, align, snapAngle, angleFromPointer, resizeRotated, convertOrientation, fitToTape, relayout, handlePoints, hitHandle, resizeFromHandle, HANDLES, normAngle, EPS };
});
