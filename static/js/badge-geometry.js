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

  /* Vertical ↔ horizontal. La etiqueta pasa de W×H a H×W y cada elemento GIRA con ella 270° (sentido horario) — su posición y su tamaño — pero su contenido queda derecho (se edita siempre derecho).
     Al imprimir, la rotación automática de la impresora (ql-usb.js `layout`: lo apaisado se gira 90°) lo deja a lo largo de la cinta: NO se gira aquí una segunda vez.
     Vertical → horizontal: x' = y, y' = W − x − w, w' = h, h' = w.   Horizontal → vertical es la inversa exacta (ida y vuelta devuelve las mismas posiciones). */
  function convertOrientation(template, toHorizontal) {
    const W = template.width_mm, H = template.height_mm;
    const nw = H, nh = W;
    const elements = (template.elements || []).map((o) => {
      const e = Object.assign({}, o);
      const x = Number(o.x) || 0, y = Number(o.y) || 0, w = Number(o.width) || 0, h = Number(o.height) || 0;
      if (toHorizontal) { e.x = y; e.y = W - x - w; } else { e.x = H - y - h; e.y = x; }
      e.width = h; e.height = w;
      // lo que cabe pero quedó medio fuera, se mete; lo que es más grande que la etiqueta se deja (se avisa)
      const b = bounds(e);
      if (b.width <= nw + EPS) { if (b.left < 0) e.x -= b.left; else if (b.right > nw) e.x -= b.right - nw; }
      if (b.height <= nh + EPS) { if (b.top < 0) e.y -= b.top; else if (b.bottom > nh) e.y -= b.bottom - nh; }
      e.x = round(e.x, 3); e.y = round(e.y, 3);
      return e;
    });
    const doesNotFit = elements.filter((e) => isOutside(e, nw, nh)).map((e) => e.id);
    return { width_mm: nw, height_mm: nh, orientation: toHorizontal ? 'horizontal' : 'vertical', elements, doesNotFit };
  }

  return { bounds, isOutside, targets, snapMove, snapPoint, snapAxis, align, snapAngle, angleFromPointer, resizeRotated, convertOrientation, normAngle, EPS };
});
