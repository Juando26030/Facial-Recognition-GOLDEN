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

// ---- vertical ↔ horizontal: el lienzo cambia, los elementos giran con él, ida y vuelta devuelve lo mismo
const diseno = tpl([el("n", 5, 8, 50, 12, 0), el("q", 38, 70, 22, 22, 0), el("f", 5, 25, 25, 30, 0), el("r", 10, 60, 20, 10, 30)]);
const h = G.convertOrientation(diseno, true);
assert.strictEqual(h.width_mm, 100); assert.strictEqual(h.height_mm, 62); assert.strictEqual(h.orientation, "horizontal");
const hn = h.elements.find((e) => e.id === "n");
near(hn.x, 8); near(hn.y, 62 - 5 - 50); near(hn.width, 12); near(hn.height, 50);            // x' = y, y' = W − x − w, w' = h, h' = w
assert.deepStrictEqual(h.doesNotFit, []);
assert.ok(h.elements.every((e) => !G.isOutside(e, 100, 62)));
const v = G.convertOrientation(h, false);
assert.strictEqual(v.width_mm, 62); assert.strictEqual(v.height_mm, 100); assert.strictEqual(v.orientation, "vertical");
diseno.elements.forEach((o) => { const back = v.elements.find((e) => e.id === o.id); ["x", "y", "width", "height", "rotation"].forEach((k) => near(back[k], o[k], `${o.id}.${k}`)); });
// lo que no cabe se avisa: en horizontal 100×62 un elemento de 20×70 (más alto que la etiqueta) no cabe al pasar a vertical 62×100 con ancho 70
const noCabe = G.convertOrientation({ width_mm: 100, height_mm: 62, elements: [el("y", 0, 0, 20, 70, 0)] }, false);
assert.deepStrictEqual(noCabe.doesNotFit, ["y"]);
// el elemento que quedaba medio afuera se mete en la etiqueta cuando cabe
const borde = G.convertOrientation(tpl([el("b", 55, 90, 10, 10, 0)]), true);
assert.ok(borde.elements[0].x >= 0 && !G.isOutside(borde.elements[0], 100, 62));
// los datos originales no se modifican (el «Deshacer» depende de eso)
assert.strictEqual(diseno.elements[0].x, 5);

// ---- no se gira dos veces: la rotación automática de la impresora decide por la forma (apaisado = 90°, vertical = 0°) y en ambos casos lo ancho de la etiqueta queda a lo ancho de la cinta
const QL = require("../../static/js/ql-usb.js");
const prefs = Object.assign({}, QL.PREF_DEFAULTS, { rotation: "auto" });
const lv = QL.layout(prefs, v.width_mm, v.height_mm), lh = QL.layout(prefs, h.width_mm, h.height_mm);
assert.strictEqual(lv.rotation, 0); assert.strictEqual(lh.rotation, 90);
assert.strictEqual(lv.acrossMm, 62); assert.strictEqual(lh.acrossMm, 62); assert.strictEqual(lv.alongMm, 100); assert.strictEqual(lh.alongMm, 100);

console.log("badge_geometry_check ok");
