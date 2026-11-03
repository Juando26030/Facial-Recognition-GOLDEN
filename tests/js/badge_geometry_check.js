// Comprobación de static/js/badge-geometry.js (imán, alinear, girar, vertical ↔ horizontal). Se corre con: node tests/js/badge_geometry_check.js
const assert = require("assert");
const G = require("../../static/js/badge-geometry.js");

const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-6, `${msg || ""} ${a} != ${b}`);
const tpl = (els) => ({ width_mm: 62, height_mm: 100, elements: els });
const el = (id, x, y, w, h, rotation) => ({ id, type: "text_static", x, y, width: w, height: h, rotation });

// ---- cuadro girado: sin ángulo (plantillas viejas) = el mismo cuadro
let b = G.bounds({ x: 5, y: 10, width: 20, height: 10 });
assert.deepStrictEqual([b.left, b.top, b.right, b.bottom], [5, 10, 25, 20]);
b = G.bounds(el("a", 5, 10, 20, 10, 90));                      // 90°: ancho y alto se intercambian alrededor del centro (15, 15)
near(b.left, 10); near(b.right, 20); near(b.top, 5); near(b.bottom, 25);
b = G.bounds(el("a", 0, 0, 10, 10, 45));
near(b.width, Math.SQRT2 * 10);

// ---- imán al mover: centro de la etiqueta, bordes y vecinos (umbral 6 px ≈ 1,6 mm)
const thr = 1.6;
let t = tpl([el("a", 20.8, 20, 20, 10, 0)]);                       // centro x = 30,8; el centro de la etiqueta es 31
let s = G.snapMove(t.elements[0], t, thr);
near(s.dx, 0.2, "centro horizontal de la etiqueta");
assert.deepStrictEqual(s.guides.x, [31]);
t = tpl([el("a", 0.8, 20, 20, 10, 0)]);                            // borde izquierdo a 0,8 mm del borde de la etiqueta
s = G.snapMove(t.elements[0], t, thr); near(s.dx, -0.8); assert.deepStrictEqual(s.guides.x, [0]);
t = tpl([el("a", 41.2, 20, 20, 10, 0)]);                           // borde derecho a 0,8 mm del borde derecho (62)
s = G.snapMove(t.elements[0], t, thr); near(s.dx, 0.8);
t = tpl([el("a", 10, 10, 20, 10, 0)]);                             // lejos de todo: no se pega
s = G.snapMove(t.elements[0], t, thr); assert.strictEqual(s.dy, 0); assert.deepStrictEqual(s.guides.y, []);
t = tpl([el("a", 10, 42.2, 20, 15, 0)]);                           // centro vertical 49,7 → etiqueta 50 (0,3 mm)
s = G.snapMove(t.elements[0], t, thr); near(s.dy, 0.3); assert.deepStrictEqual(s.guides.y, [50]);
// vecinos: el borde derecho de «a» se pega al borde izquierdo de «n» (x = 20)
t = tpl([el("a", 10.8, 5, 10, 10, 0), el("n", 20, 60, 20, 10, 0)]);
s = G.snapMove(t.elements[0], t, thr); near(s.dx, -0.8); assert.ok(s.guides.x.includes(20));
// fuera de umbral: no se mueve
t = tpl([el("a", 12, 5, 10, 10, 0), el("n", 40, 60, 10, 10, 0)]);
s = G.snapMove(t.elements[0], t, thr); assert.strictEqual(s.dx, 0); assert.deepStrictEqual(s.guides.x, []);
// el elemento girado se pega por su cuadro ya girado (40×10 girado 90° ocupa 10 de ancho × 40 de alto, centrado en 25,8: su borde derecho queda a 0,2 mm del centro de la etiqueta)
t = tpl([el("a", 5.8, 10, 40, 10, 90)]);
s = G.snapMove(t.elements[0], t, thr);
const nb = G.bounds(Object.assign({}, t.elements[0], { x: t.elements[0].x + s.dx, y: t.elements[0].y + s.dy }));
assert.ok([0, 31, 62].some((pos) => [nb.left, nb.cx, nb.right].some((c) => Math.abs(c - pos) < 1e-6)));

// ---- imán al redimensionar: el punto de la esquina se pega
const p = G.snapPoint(61.2, 99.4, tpl([]), null, thr);
near(p.x, 62); near(p.y, 100); assert.deepStrictEqual(p.guides.x, [62]);
const q = G.snapPoint(30.4, 40, tpl([]), null, thr); near(q.x, 31); near(q.y, 40);

// ---- tamaño con el elemento girado: la esquina superior izquierda no se mueve
let r = G.resizeRotated(el("a", 10, 10, 20, 10, 0), 40, 30, 3);
near(r.x, 10); near(r.y, 10); near(r.width, 30); near(r.height, 20);
const rot = el("a", 10, 10, 20, 10, 90);
const anchor = (e) => {
  const a = (e.rotation * Math.PI) / 180, c = { x: e.x + e.width / 2, y: e.y + e.height / 2 };
  return { x: c.x + (-e.width / 2) * Math.cos(a) - (-e.height / 2) * Math.sin(a), y: c.y + (-e.width / 2) * Math.sin(a) + (-e.height / 2) * Math.cos(a) };
};
r = G.resizeRotated(rot, 15, 5 + 30, 3);                              // girado 90° la esquina inferior derecha se arrastra hacia abajo: crece el ANCHO del elemento
near(r.width, 30); near(r.height, 10);
near(anchor(Object.assign({}, rot, r)).x, anchor(rot).x, "ancla x"); near(anchor(Object.assign({}, rot, r)).y, anchor(rot).y, "ancla y");

// ---- alinear respecto a la etiqueta (con cuadro girado)
t = tpl([el("a", 10, 10, 20, 10, 0)]);
assert.deepStrictEqual(G.align(t.elements[0], t, "left"), { x: 0, y: 10 });
assert.deepStrictEqual(G.align(t.elements[0], t, "right"), { x: 42, y: 10 });
assert.deepStrictEqual(G.align(t.elements[0], t, "center"), { x: 21, y: 10 });
assert.deepStrictEqual(G.align(t.elements[0], t, "top"), { x: 10, y: 0 });
assert.deepStrictEqual(G.align(t.elements[0], t, "bottom"), { x: 10, y: 90 });
assert.deepStrictEqual(G.align(t.elements[0], t, "middle"), { x: 10, y: 45 });
const girado = el("g", 0, 0, 40, 10, 90);
near(G.bounds(Object.assign({}, girado, G.align(girado, tpl([girado]), "left"))).left, 0);
near(G.bounds(Object.assign({}, girado, G.align(girado, tpl([girado]), "bottom"))).bottom, 100);

// ---- rotación: con imán (3°), sin imán y con Mayús (pasos de 15°)
near(G.snapAngle(88.5), 90); near(G.snapAngle(2.9), 0); near(G.snapAngle(357.5), 0); near(G.snapAngle(47.9), 45); near(G.snapAngle(181.8), 180); near(G.snapAngle(268), 270);
near(G.snapAngle(93.5), 93.5, "fuera de tolerancia queda libre"); near(G.snapAngle(50), 50);
near(G.snapAngle(100, { shift: true }), 105); near(G.snapAngle(97, { shift: true }), 90); near(G.snapAngle(359, { shift: true }), 0);
near(G.snapAngle(88.5, { tol: 0 }), 88.5, "sin imán");
near(G.normAngle(-90), 270); near(G.normAngle(450), 90); near(G.normAngle(undefined), 0); near(G.normAngle("x"), 0);
near(G.angleFromPointer(10, 10, 10, 0), 0); near(G.angleFromPointer(10, 10, 20, 10), 90); near(G.angleFromPointer(10, 10, 10, 20), 180); near(G.angleFromPointer(10, 10, 0, 10), 270);

// ---- «fuera de la etiqueta» con el cuadro girado
assert.strictEqual(G.isOutside(el("a", 5, 5, 40, 10, 0), 62, 100), false);
assert.strictEqual(G.isOutside(el("a", 20, 5, 40, 10, 90), 62, 100), true);           // girado 90° ocupa 10×40 centrado en (40, 10): arriba queda en −10
assert.strictEqual(G.isOutside(el("a", 20, 30, 40, 10, 90), 62, 100), false);

// ---- plantillas viejas (sin ángulo) se leen como 0° y nada se rompe
const vieja = { id: "v", type: "qr", x: 4, y: 4, width: 22, height: 22 };
assert.deepStrictEqual(G.bounds(vieja), G.bounds(Object.assign({ rotation: 0 }, vieja)));
assert.strictEqual(G.isOutside(vieja, 62, 100), false);

// ---- vertical ↔ horizontal (25-oct-2026): reubicar por PROPORCIÓN, sin intercambiar ancho y alto de las cajas; nada fuera, nada encima, ningún texto cortado; ida y vuelta exacta
global.window = undefined;
const R = require("../../static/js/badge-render.js");                              // el MISMO ajuste de texto que se dibuja e imprime (en node mide con un ancho aproximado)
const LARGO = { first_name: "JUAN SEBASTIAN", last_name: "GARITA ROJAS", entity: "EMPRESA DENOMINADA INVERSIONES Y SERVICIOS DEL ORIENTE S.A.S.", id: "1020304050" };
const measure = (e, w) => R.textHeightMm(e, w, LARGO);
const txt = (id, variable, x, y, w, h, size) => ({ id, type: "text_variable", variable, x, y, width: w, height: h, font_size: size || 14, font_family: "Roboto", font_weight: "bold", align: "center", rotation: 0 });
const ejemplo = { width_mm: 58.9, height_mm: 100, elements: [
  txt("n", "first_name", 4, 6, 50.9, 10, 16), txt("a", "last_name", 4, 18, 50.9, 10, 16), txt("e", "entity", 4, 30, 50.9, 12, 11),
  { id: "f", type: "image_variable", x: 17, y: 45, width: 25, height: 30, rotation: 0 }, { id: "q", type: "qr", x: 19.45, y: 78, width: 20, height: 20, rotation: 0 }] };
const PXMM = 96 / 25.4, PXPT = 96 / 72;
function revisar(t, nombre, ref) {
  const W = t.width_mm, H = t.height_mm, els = t.elements;
  els.forEach((e) => assert.ok(!G.isOutside(e, W, H), `${nombre}: ${e.id} fuera de la etiqueta`));
  for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++) {
    const a = G.bounds(els[i]), b = G.bounds(els[j]);
    assert.ok(!(a.left < b.right - 0.01 && b.left < a.right - 0.01 && a.top < b.bottom - 0.01 && b.top < a.bottom - 0.01), `${nombre}: ${els[i].id} encima de ${els[j].id}`);
  }
  els.filter((e) => e.type === "text_variable").forEach((e) => {
    const fit = R.fitText(LARGO[e.variable], e.width * PXMM, e.height * PXMM, e.font_size * PXPT, (s, px) => s.length * px * 0.6);
    assert.ok(!fit.truncated, `${nombre}: el texto ${e.id} se cortaría (${fit.lines.join(" / ")})`);
    assert.ok(e.width >= e.height, `${nombre}: la caja de ${e.id} quedó alta y angosta (${e.width} × ${e.height})`);
  });
  els.filter((e) => e.type === "qr" || e.type === "image_variable").forEach((e) => {
    const o = (ref || ejemplo).elements.find((x) => x.id === e.id);
    assert.ok(Math.abs(e.width / e.height - o.width / o.height) < 2e-3, `${nombre}: ${e.id} se deformó`);       // (milésimas de mm por redondeo)
  });
}
revisar(ejemplo, "original");
const h = G.convertOrientation(ejemplo, true, { acrossMm: 58.9, measure });
assert.strictEqual(h.width_mm, 100); assert.strictEqual(h.height_mm, 58.9); assert.strictEqual(h.orientation, "horizontal"); assert.strictEqual(h.restored, false);
assert.deepStrictEqual(h.doesNotFit, []);
revisar(h, "horizontal");
const v = G.convertOrientation(h, false, { acrossMm: 58.9, measure });
assert.strictEqual(v.width_mm, 58.9); assert.strictEqual(v.height_mm, 100); assert.strictEqual(v.restored, true);
ejemplo.elements.forEach((o) => { const back = v.elements.find((e) => e.id === o.id); ["x", "y", "width", "height", "rotation"].forEach((k) => near(back[k], o[k], `ida y vuelta ${o.id}.${k}`)); });
revisar(v, "vuelta a vertical");
const h2 = G.convertOrientation(v, true, { acrossMm: 58.9, measure });                 // y otra vez: lo que tenía en horizontal
h.elements.forEach((o) => { const e = h2.elements.find((x) => x.id === o.id); ["x", "y", "width", "height"].forEach((k) => near(e[k], o[k], `segunda ida ${o.id}.${k}`)); });
// un diseño HECHO en horizontal (sin nada recordado) pasado a vertical
const horizontal = { width_mm: 100, height_mm: 58.9, elements: [
  txt("n", "first_name", 4, 5, 62, 10, 18), txt("a", "last_name", 4, 17, 62, 10, 18), txt("e", "entity", 4, 30, 62, 12, 11),
  { id: "q", type: "qr", x: 72, y: 8, width: 22, height: 22, rotation: 0 }, { id: "f", type: "image_variable", x: 74, y: 32, width: 18, height: 22, rotation: 0 }] };
const hv = G.convertOrientation(horizontal, false, { acrossMm: 58.9, measure });
assert.strictEqual(hv.width_mm, 58.9); assert.strictEqual(hv.height_mm, 100);
revisar(hv, "horizontal → vertical", horizontal);
// lo centrado sigue centrado
const centrado = G.convertOrientation({ width_mm: 58.9, height_mm: 100, elements: [txt("c", "first_name", 9.45, 40, 40, 10, 12)] }, true, { acrossMm: 58.9, measure });
near(centrado.elements[0].x + centrado.elements[0].width / 2, 50, "el texto centrado sigue centrado");
// «Ajustar a la cinta»: 100 × 65,5 → 100 × 58,9, nada fuera ni encima
const ancho = Object.assign({}, h, { height_mm: 65.5, elements: h.elements.map((e) => Object.assign({}, e, { y: e.y * 65.5 / 58.9 })) });
const fit = G.fitToTape(ancho, 58.9, { measure });
assert.strictEqual(fit.width_mm, 100); assert.strictEqual(fit.height_mm, 58.9);
revisar(fit, "ajustar a la cinta");
// los datos originales no se modifican (el «Deshacer» depende de eso)
assert.strictEqual(ejemplo.elements[0].x, 4); assert.ok(!ejemplo.elements[0].layouts);

// ---- no se gira dos veces y no se encoge: la impresora decide el giro por la forma (apaisado = 90°, vertical = 0°) y lo ancho de la cinta es exactamente lo imprimible
const QL = require("../../static/js/ql-usb.js");
const prefs = Object.assign({}, QL.PREF_DEFAULTS, { rotation: "auto" });
const lv = QL.layout(prefs, v.width_mm, v.height_mm), lh = QL.layout(prefs, h.width_mm, h.height_mm);
assert.strictEqual(lv.rotation, 0); assert.strictEqual(lh.rotation, 90);
assert.strictEqual(lv.acrossMm, 58.9); assert.strictEqual(lh.acrossMm, 58.9); assert.strictEqual(lv.tooWide, false); assert.strictEqual(lh.tooWide, false);

// ---- manijas como PowerPoint (25-oct-2026): 4 esquinas + 4 lados + giro; lo opuesto queda fijo; en los ejes del elemento; la manija gana siempre al elemento de debajo
{
  const A = { id: "a", type: "text_static", x: 10, y: 20, width: 30, height: 10, rotation: 0 };
  const P = G.handlePoints(A, 6);
  assert.deepStrictEqual([P.nw.x, P.nw.y, P.se.x, P.se.y, P.n.x, P.n.y, P.e.x, P.e.y], [10, 20, 40, 30, 25, 20, 40, 25]);
  near(P.rotate.x, 25); near(P.rotate.y, 14);
  // hit-testing: la manija más cercana dentro de la zona; fuera de toda zona, nada
  assert.strictEqual(G.hitHandle(40.5, 30.4, A, 2, 6), "se");
  assert.strictEqual(G.hitHandle(25, 13.5, A, 2, 6), "rotate");
  assert.strictEqual(G.hitHandle(25, 25, A, 2, 6), null, "el centro del elemento no es manija");
  assert.strictEqual(G.hitHandle(25, 25, null, 2, 6), null);
  // un elemento B encima justo donde está la manija: la manija igual se reconoce (la decisión no depende de qué elemento haya debajo)
  const B = { id: "b", type: "qr", x: 35, y: 25, width: 20, height: 20, rotation: 0 };
  assert.ok(!G.isOutside(B, 62, 100) && G.bounds(B).left < 40 && G.bounds(B).top < 30);
  assert.strictEqual(G.hitHandle(40, 30, A, 2, 6), "se");
  // cada manija: el punto opuesto no se mueve; los lados cambian una sola medida
  const opposite = { nw: "se", n: "s", ne: "sw", e: "w", se: "nw", s: "n", sw: "ne", w: "e" };
  for (const rot of [0, 30, 90, 349]) {
    const E = Object.assign({}, A, { rotation: rot });
    for (const h of Object.keys(G.HANDLES)) {
      const p0 = G.handlePoints(E, 0);
      const [hx, hy] = G.HANDLES[h];
      const a = (rot * Math.PI) / 180, push = 5;                                    // arrastrar 5 mm hacia afuera en los ejes del elemento
      const tx = p0[h].x + push * (hx * Math.cos(a) - hy * Math.sin(a)), ty = p0[h].y + push * (hx * Math.sin(a) + hy * Math.cos(a));
      const r = Object.assign({}, E, G.resizeFromHandle(E, h, tx, ty));
      const p1 = G.handlePoints(r, 0);
      const mm = (x, y, m) => assert.ok(Math.abs(x - y) < 2e-3, `${m}: ${x} != ${y}`);          // se guarda con milésimas de mm
      mm(p1[opposite[h]].x, p0[opposite[h]].x, `${rot}° ${h}: lo opuesto fijo (x)`); mm(p1[opposite[h]].y, p0[opposite[h]].y, `${rot}° ${h}: lo opuesto fijo (y)`);
      mm(r.width, hx ? 35 : 30, `${rot}° ${h}: ancho`); mm(r.height, hy ? 15 : 10, `${rot}° ${h}: alto`);
      near(r.rotation, rot);
    }
  }
  // esquina con Mayús: en proporción
  let r = G.resizeFromHandle(A, "se", 46, 31, { keepAspect: true });
  near(r.width / r.height, 3, "Mayús conserva la proporción"); near(r.x, 10); near(r.y, 20);
  // fotos, QR y códigos: proporción siempre (también por los lados)
  const Q = { id: "q", type: "qr", x: 10, y: 10, width: 20, height: 20, rotation: 0 };
  r = G.resizeFromHandle(Q, "e", 40, 20); near(r.width, 30); near(r.height, 30);
  r = G.resizeFromHandle(Q, "nw", 0, 5); near(r.width, r.height); near(r.x + r.width, 30); near(r.y + r.height, 30);
  const F = { id: "f", type: "image_variable", x: 0, y: 0, width: 25, height: 30, rotation: 0 };
  r = G.resizeFromHandle(F, "se", 50, 31); near(r.width / r.height, 25 / 30);
  // nunca menos de 3 mm (y nunca «al revés» al cruzar el lado opuesto)
  r = G.resizeFromHandle(A, "e", 0, 25); near(r.width, 3); near(r.x, 10);
  r = G.resizeFromHandle(A, "n", 25, 100); near(r.height, 3); near(r.y + r.height, 30);
}

console.log("badge_geometry_check ok");
