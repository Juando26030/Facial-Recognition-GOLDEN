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
assert.deepStrictEqual(r, { lines: ["ANA"], size: 16 * PXPT, shrunk: false, truncated: false });
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
  const fake = () => ({ style: {}, dataset: {}, children: [], attrs: {}, setAttribute(k, v) { this.attrs[k] = String(v); }, appendChild(c) { this.children.push(c); return c; }, getContext: () => null });          // setAttribute: el QR se marca para volver a dibujarse (18-nov-2026)
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

// ---- 19-nov-2026: un texto que no cabe en su caja usa primero el espacio libre de abajo (más líneas) hasta el siguiente elemento; solo si aún no alcanza, achica la letra
{
  const els = [
    { id: "a", type: "text_variable", variable: "entity", x: 5, y: 20, width: 50, height: 8, font_size: 14, rotation: 0 },
    { id: "b", type: "text_variable", variable: "role", x: 5, y: 44, width: 50, height: 8, font_size: 14, rotation: 0 },
    { id: "c", type: "qr", variables: ["id"], x: 60, y: 22, width: 10, height: 10, rotation: 0 },
  ];
  assert.ok(Math.abs(R.roomBelow(els[0], els, 100) - (44 - 28 - 0.5)) < 1e-9, "llega hasta el siguiente elemento que se cruza a lo ancho (el QR de la derecha no cuenta)");
  assert.ok(Math.abs(R.roomBelow(els[1], els, 100) - (100 - 52 - 0.5)) < 1e-9, "sin nada debajo: hasta el borde de la etiqueta");
  assert.strictEqual(R.roomBelow({ ...els[0], rotation: 30 }, els, 100), 0, "girado: no crece");
  assert.strictEqual(R.roomBelow({ id: "z", x: 5, y: 20, width: 50, height: 30 }, els, 100), 0, "caja que ya llega al siguiente elemento: sin espacio");

  const fake = () => ({ style: {}, dataset: {}, children: [], attrs: {}, setAttribute(k, v) { this.attrs[k] = String(v); }, appendChild(c) { this.children.push(c); return c; }, getContext: () => null });          // setAttribute: el QR se marca para volver a dibujarse (18-nov-2026)
  global.document = { createElement: fake };
  const data = { entity: "INSTITUCIÓN EDUCATIVA TÉCNICA AGROPECUARIA DEL MUNICIPIO DE SAN JOSÉ" };
  const solo = R.renderElement(els[0], data, {}), conEspacio = R.renderElement(els[0], data, { room: R.roomBelow(els[0], els, 100) });
  const px = (d) => parseFloat(d.style.fontSize);
  assert.ok(!conEspacio.children[0].textContent.endsWith("…"), "con espacio libre ya no se recorta con «…»");
  assert.ok(conEspacio.children[0].textContent.split("\n").length > solo.children[0].textContent.split("\n").length, "toma más líneas");
  assert.ok(px(conEspacio) >= px(solo), "y la letra no queda más chica que sin espacio");
  assert.ok(parseFloat(conEspacio.style.cssText.match(/height:([\d.]+)mm/) ? conEspacio.style.cssText.match(/height:([\d.]+)mm/)[1] : 0) >= 8, "la caja sigue su alto original o más");
  assert.ok(conEspacio.dataset.grown === undefined || parseFloat(conEspacio.dataset.grown) <= 15.5 + 1e-9, "nunca más allá del espacio libre");
  delete global.document;
}

console.log("badge_text_fit_check ok");
