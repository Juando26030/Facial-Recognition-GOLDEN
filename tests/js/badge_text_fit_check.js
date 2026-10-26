// Comprobación del ajuste de los textos a su caja (static/js/badge-render.js fitText): «ningún texto se corta». Se corre con: node tests/js/badge_text_fit_check.js
// 1) baja de línea por palabras (nunca parte una palabra); 2) si aún no cabe, reduce la letra hasta el 40 %; 3) solo entonces recorta con «…».
const assert = require("assert");
const R = require("../../static/js/badge-render.js");

const PXMM = 96 / 25.4, PXPT = 96 / 72;
const measure = (s, px) => s.length * px * 0.6;                     // ancho aproximado de letra en mayúsculas/negrita (en el navegador se mide con la fuente real)
const fit = (text, wMm, hMm, pt) => R.fitText(text, wMm * PXMM, hMm * PXMM, pt * PXPT, measure);
const words = (t) => t.trim().split(/\s+/);

const DATOS = [
  "JUAN SEBASTIAN GARITA ROJAS", "MARÍA DE LOS ÁNGELES RODRÍGUEZ VILLAMIZAR", "GARITA ROJAS", "José Ignacio Castañeda Pérez de la Torre",
  "EMPRESA DENOMINADA INVERSIONES Y SERVICIOS DEL ORIENTE S.A.S.", "Corporación Universitaria Minuto de Dios - UNIMINUTO", "ANA",
];
// cajas típicas de una escarapela vertical (58,9 mm de ancho) y horizontal (100 mm de ancho)
const CAJAS = [[50, 10, 16], [50, 12, 11], [85, 10, 18], [60, 12, 11], [40, 8, 14]];
for (const t of DATOS) for (const [w, h, pt] of CAJAS) {
  const r = fit(t, w, h, pt);
  const boxW = w * PXMM, boxH = h * PXMM;
  assert.ok(r.size <= pt * PXPT + 1e-9 && r.size >= pt * PXPT * R.MIN_RATIO - 1e-9, "tamaño dentro de lo permitido");
  assert.ok(r.lines.length * r.size * R.LINE_HEIGHT <= boxH + 0.02, `${t} en ${w}×${h}: las líneas caben a lo alto`);
  r.lines.forEach((l) => assert.ok(measure(l, r.size) <= boxW + 0.02, `${t} en ${w}×${h}: «${l}» cabe a lo ancho`));
  if (!r.truncated) {
    assert.deepStrictEqual(words(r.lines.join(" ")), words(t), `${t}: no se pierde ni se parte ninguna palabra`);
    r.lines.forEach((l) => words(l).forEach((wd) => assert.ok(words(t).includes(wd), `«${wd}» es una palabra entera`)));
  } else {
    assert.ok(r.lines[r.lines.length - 1].endsWith("…"), "si se recorta, se nota con «…»");
  }
}

// el nombre de la prueba física: en la caja de la escarapela vertical NO se corta (baja a dos líneas a su tamaño o un poco menor)
let r = fit("JUAN SEBASTIAN GARITA ROJAS", 50, 10, 16);
assert.strictEqual(r.truncated, false);
assert.deepStrictEqual(r.lines, ["JUAN SEBASTIAN", "GARITA ROJAS"]);
// la empresa larga: entra completa en varias líneas con letra más pequeña
r = fit("EMPRESA DENOMINADA INVERSIONES Y SERVICIOS DEL ORIENTE S.A.S.", 50, 12, 11);
assert.strictEqual(r.truncated, false); assert.ok(r.shrunk && r.lines.length >= 2);
// lo que cabe no se toca
r = fit("ANA", 50, 10, 16);
assert.strictEqual(r.size, 16 * PXPT); assert.deepStrictEqual(r.lines, ["ANA"]); assert.ok(!r.shrunk && !r.truncated && !r.grown && r.ratio === 1);
// recién cuando ni con la letra mínima cabe, se recorta con «…» (y nunca a la mitad sin aviso)
r = fit("SUPERCALIFRAGILISTICOESPIALIDOSO EXTRAORDINARIAMENTE LARGO", 12, 3, 16);
assert.strictEqual(r.truncated, true); assert.ok(r.lines[r.lines.length - 1].endsWith("…"));
assert.ok(Math.abs(r.size - 16 * PXPT * R.MIN_RATIO) < 1e-9);
// vacío, sin caja o sin datos: no falla
assert.deepStrictEqual(fit("", 50, 10, 12).lines, []);
assert.deepStrictEqual(fit(null, 50, 10, 12).lines, []);
assert.strictEqual(fit("Hola", 0, 10, 12).truncated, false);

// el alto que necesita un texto (para reacomodar al cambiar la orientación): más palabras o menos ancho = más alto
const el = { type: "text_variable", variable: "entity", font_size: 11, font_family: "Roboto" };
const data = { entity: "EMPRESA DENOMINADA INVERSIONES Y SERVICIOS DEL ORIENTE S.A.S." };
assert.ok(R.textHeightMm(el, 40, data) > R.textHeightMm(el, 90, data));
assert.ok(R.textHeightMm(el, 90, { entity: "ANA" }) < R.textHeightMm(el, 90, data) + 1e-9);

// ---- un elemento GIRADO no recorta (html2canvas aplica el overflow:hidden de un elemento con transform con la caja SIN girar: la QL-800 imprimía «DRÍGL», «LAMIZ»)
{
  const fake = () => ({ style: {}, dataset: {}, children: [], appendChild(c) { this.children.push(c); return c; }, getContext: () => null });
  global.document = { createElement: fake };
  const txt = (rotation) => ({ id: "t", type: "text_variable", variable: "last_name", x: 4, y: 30, width: 50, height: 12, font_size: 16, font_family: "Roboto", rotation });
  const data = { last_name: "RODRÍGUEZ VILLAMIZAR" };
  for (const rot of [30, 45, 90, 180, 270, 349, -12]) {
    const d = R.renderElement(txt(rot), data, {});
    assert.strictEqual(d.style.overflow, "visible", `girado ${rot}°: no se recorta`);
    assert.ok(d.style.cssText.includes(`rotate(${rot}deg)`));
  }
  for (const rot of [0, 360, undefined]) assert.strictEqual(R.renderElement(txt(rot), data, {}).style.overflow, "hidden", `sin giro (${rot}) se conserva el recorte de siempre`);
  const qr = R.renderElement({ id: "q", type: "qr", variables: ["id"], x: 0, y: 0, width: 10, height: 10, rotation: 90 }, { id: "1" }, {});
  assert.strictEqual(qr.style.overflow, "visible");
  // el ajuste se calcula en los ejes del PROPIO elemento (ancho × alto de su caja, antes de girar): girarlo no cambia las líneas
  const lines = (rot) => R.renderElement(txt(rot), data, {}).children[0].textContent;
  assert.strictEqual(lines(90), lines(0)); assert.strictEqual(lines(349), lines(0));
  delete global.document;
}

// ---- la plantilla vigente en cada impresión: sin caché y con un parámetro único (ningún intermediario devuelve una copia)
{
  const calls = [];
  global.fetch = (url, init) => { calls.push([url, init]); return Promise.resolve({ ok: true }); };
  R.fetchTemplate(7, "VIP"); R.fetchTemplate(7);
  assert.strictEqual(calls.length, 2);
  assert.ok(/^\/api\/events\/7\/badge-template\?category=VIP&_=\d+$/.test(calls[0][0]), calls[0][0]);
  assert.ok(/^\/api\/events\/7\/badge-template\?_=\d+$/.test(calls[1][0]), calls[1][0]);
  assert.ok(calls.every((c) => c[1].cache === "no-store"));
  delete global.fetch;
}

// ---- REGLAS NUEVAS (25-oct-2026): (a) palabras, (b) la caja CRECE hacia abajo, (c) reducir con piso del 60 %, (d) «…» solo al final; jerarquía; nombre y apellido parejos; modos por texto
assert.strictEqual(R.MIN_RATIO, 0.6);
{
  const PXMM2 = 96 / 25.4, PT = 96 / 72;
  const m2 = (s, px) => s.length * px * 0.6;
  const OPC = "1. MILAGRO PARA LA RECONSTRUCCIÓN, TRANSFORMACIÓN Y RESILIENCIA";                     // el opcional de Juan (más de 60 caracteres)
  assert.ok(OPC.length >= 62);
  // opcional de 62 caracteres a 18 pt en una caja de 49,4 × 7,9 mm: con espacio libre debajo CRECE (no se achica a lo mínimo ni se corta)
  let f = R.fitText(OPC, 49.4 * PXMM2, 7.9 * PXMM2, 18 * PT, m2, { mode: "grow", maxH: 35 * PXMM2 });
  assert.ok(!f.truncated && f.grown && f.heightPx > 7.9 * PXMM2 && f.heightPx <= 35 * PXMM2 + 0.01, JSON.stringify(f));
  assert.ok(f.ratio >= 0.8, "con 35 mm libres se queda cerca del tamaño diseñado (" + f.ratio + ")");
  // sin espacio libre: reduce, pero nunca por debajo del 60 % antes de recortar
  f = R.fitText(OPC, 49.4 * PXMM2, 7.9 * PXMM2, 18 * PT, m2, { mode: "grow", maxH: 20 * PXMM2 });
  assert.ok(f.ratio >= 0.6 - 1e-9, "piso del 60 %"); assert.ok(f.shrunk);
  assert.strictEqual(f.truncated, false, "con 20 mm cabe reduciendo hasta el 60 %: sin «…»");
  // modo «reducir para caber»: la caja NO crece
  f = R.fitText(OPC, 49.4 * PXMM2, 7.9 * PXMM2, 18 * PT, m2, { mode: "shrink", maxH: 35 * PXMM2 });
  assert.ok(!f.grown && f.heightPx === 7.9 * PXMM2);
  // modo «una línea»: una sola línea, se achica por ancho; si ni al 60 % cabe, «…»
  f = R.fitText("JUAN SEBASTIAN GARITA", 40 * PXMM2, 8 * PXMM2, 14 * PT, m2, { mode: "single" });
  assert.strictEqual(f.lines.length, 1);
  f = R.fitText(OPC, 40 * PXMM2, 8 * PXMM2, 14 * PT, m2, { mode: "single" });
  assert.ok(f.lines.length === 1 && f.truncated && f.lines[0].endsWith("…") && f.ratio >= 0.6 - 1e-9);
  // el piso blando de la jerarquía: floorPx sube el mínimo pero nunca por encima del tamaño diseñado
  f = R.fitText("MARÍA DE LOS ÁNGELES RODRÍGUEZ", 50 * PXMM2, 10 * PXMM2, 20 * PT, m2, { mode: "grow", maxH: 30 * PXMM2, floorPx: 99 * PT });
  assert.ok(f.size <= 20 * PT + 1e-9);

  // ---- plan de la plantilla: nombre y apellido nunca menores que «MESA»; parejos; el opcional crece hacia abajo
  const T = (id, v, x, y, w, h, pt, extra) => Object.assign({ id, type: "text_variable", variable: v, x, y, width: w, height: h, font_size: pt, font_family: "Roboto", font_weight: "bold", rotation: 0 }, extra || {});
  const MESA = { id: "m", type: "text_static", content: "MESA", x: 4, y: 92, width: 50.9, height: 6, font_size: 14, font_family: "Roboto", font_weight: "bold", rotation: 0 };
  const tpl = (els, w, h) => ({ width_mm: w || 58.9, height_mm: h || 100, elements: els });
  const NOMBRES = [["CRISTIAN CAMILO", "NAVARRO SANCHEZ"], ["MARÍA DE LOS ÁNGELES", "RODRÍGUEZ VILLAMIZAR"], ["JUAN SEBASTIAN", "GARITA ROJAS"], ["ANA", "MORA"]];
  for (const [first, last] of NOMBRES) {
    const vertical = tpl([T("n", "first_name", 4, 8, 50.9, 12, 24), T("a", "last_name", 4, 22, 50.9, 12, 24), MESA, T("o", "opt_1", 4, 53.7, 49.4, 7.9, 18)]);
    const horizontal = tpl([T("n", "first_name", 4, 4, 62, 12, 24), T("a", "last_name", 4, 18, 62, 12, 24), Object.assign({}, MESA, { x: 4, y: 55, width: 62, height: 3.5 }), T("o", "opt_1", 4, 34, 62, 7.9, 18)], 100, 58.9);
    for (const [name, t] of [["vertical", vertical], ["horizontal", horizontal]]) {
      const plan = R.planText(t, { first_name: first, last_name: last, opt_1: OPC });
      const n = plan.get("n"), a = plan.get("a"), mesa = plan.get("m"), o = plan.get("o");
      assert.ok(!n.truncated && !a.truncated && !o.truncated, `${name} ${first}: sin «…»`);
      assert.ok(n.size >= mesa.size - 1e-9 && a.size >= mesa.size - 1e-9, `${name} ${first}: el nombre no queda menor que MESA (${n.size} vs ${mesa.size})`);
      assert.ok(Math.abs(n.size - a.size) < 1e-6, `${name} ${first}: nombre y apellido parejos`);
      assert.ok(n.ratio >= 0.6 - 1e-9 && a.ratio >= 0.6 - 1e-9 && o.ratio >= 0.6 - 1e-9);
    }
  }
  // un texto sin giro NO crece sobre el elemento que tiene debajo, y el girado no crece
  const tapado = tpl([T("n", "first_name", 4, 8, 50.9, 12, 24), Object.assign({}, MESA, { y: 22 })]);
  const pn = R.planText(tapado, { first_name: "MARÍA DE LOS ÁNGELES RODRÍGUEZ VILLAMIZAR" }).get("n");
  assert.ok(pn.heightPx <= (22 - 0.5 - 8) * PXMM2 + 0.5, "no invade al de abajo");
  const girado = R.planText(tpl([T("n", "first_name", 4, 8, 50.9, 12, 24, { rotation: 90 })]), { first_name: "MARÍA DE LOS ÁNGELES RODRÍGUEZ" }).get("n");
  assert.ok(!girado.grown, "un texto girado no crece");
  // por defecto: los variables crecen; los fijos se reducen; se puede elegir
  assert.strictEqual(R.fitModeOf({ type: "text_variable" }), "grow"); assert.strictEqual(R.fitModeOf({ type: "text_static" }), "shrink");
  assert.strictEqual(R.fitModeOf({ type: "text_variable", fit_mode: "single" }), "single"); assert.strictEqual(R.fitModeOf({ type: "text_variable", fit_mode: "raro" }), "grow");
}

console.log("badge_text_fit_check ok");
