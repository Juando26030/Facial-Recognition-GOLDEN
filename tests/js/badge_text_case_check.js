// Mayúsculas / minúsculas de los textos de la escarapela (static/js/badge-render.js applyTextCase): solo presentación, en español. Se corre con: node tests/js/badge_text_case_check.js
const assert = require("assert");
const R = require("../../static/js/badge-render.js");
const T = R.applyTextCase;

const CASOS = {
  "MARÍA DE LOS ÁNGELES RODRÍGUEZ VILLAMIZAR": ["MARÍA DE LOS ÁNGELES RODRÍGUEZ VILLAMIZAR", "maría de los ángeles rodríguez villamizar", "María de los Ángeles Rodríguez Villamizar"],
  "juan sebastian garita rojas": ["JUAN SEBASTIAN GARITA ROJAS", "juan sebastian garita rojas", "Juan Sebastian Garita Rojas"],
  "José-Luis O'Brien": ["JOSÉ-LUIS O'BRIEN", "josé-luis o'brien", "José-Luis O'Brien"],
  "o'brien josé-luis": ["O'BRIEN JOSÉ-LUIS", "o'brien josé-luis", "O'Brien José-Luis"],
  "Corporación Universitaria Minuto de Dios - UNIMINUTO": ["CORPORACIÓN UNIVERSITARIA MINUTO DE DIOS - UNIMINUTO", "corporación universitaria minuto de dios - uniminuto", "Corporación Universitaria Minuto de Dios - Uniminuto"],
  "golden eventos y logística s.a.s.": ["GOLDEN EVENTOS Y LOGÍSTICA S.A.S.", "golden eventos y logística s.a.s.", "Golden Eventos y Logística S.A.S."],
  "ÑANDÚ PEÑA": ["ÑANDÚ PEÑA", "ñandú peña", "Ñandú Peña"],
  "  ana   maría    de la  CRUZ  ": ["ANA MARÍA DE LA CRUZ", "ana maría de la cruz", "Ana María de la Cruz"],
  "": ["", "", ""],
};
for (const [entrada, [mayus, minus, altas]] of Object.entries(CASOS)) {
  assert.strictEqual(T(entrada, "upper"), mayus, `MAYÚSCULAS de «${entrada}»`);
  assert.strictEqual(T(entrada, "lower"), minus, `minúsculas de «${entrada}»`);
  assert.strictEqual(T(entrada, "title"), altas, `Altas y Bajas de «${entrada}»`);
  assert.strictEqual(T(entrada, "as_is"), entrada, "«Como está» no toca nada");
  assert.strictEqual(T(entrada, undefined), entrada, "plantilla vieja (sin el campo) = como está");
}
// la partícula al inicio sí va con mayúscula; las demás en minúscula
assert.strictEqual(T("DE LA TORRE Y ASOCIADOS", "title"), "De la Torre y Asociados");
assert.strictEqual(T("pedro e hijos u otros o nada el fin del mundo las rosas los andes", "title"), "Pedro e Hijos u Otros o Nada el Fin del Mundo las Rosas los Andes");
// siglas (lista en UN solo lugar) y abreviaturas con puntos; números romanos
assert.deepStrictEqual(R.SIGLAS, ["SAS", "S.A.S.", "S.A.", "LTDA", "ONG", "EPS", "IPS", "DIAN", "ESAP", "UNAD", "DNP"]);
assert.strictEqual(T("inversiones abc sas", "title"), "Inversiones Abc SAS");
assert.strictEqual(T("comercial s.a. y ltda", "title"), "Comercial S.A. y LTDA");
assert.strictEqual(T("fundación ong eps ips dian esap unad dnp", "title"), "Fundación ONG EPS IPS DIAN ESAP UNAD DNP");
assert.strictEqual(T("e.u. ltda.", "title"), "E.U. LTDA.");
assert.strictEqual(T("JUAN PABLO II y fase iii, capítulo iv", "title"), "Juan Pablo II y Fase III, Capítulo IV");
// signos al inicio de una palabra
assert.strictEqual(T("«hola» (mundo) ¿qué?", "title"), "«Hola» (Mundo) ¿Qué?");
// un modo desconocido no rompe nada
assert.strictEqual(T("Hola", "raro"), "Hola");
// el dato sigue igual: solo cambia lo que se dibuja
const el = { type: "text_variable", variable: "first_name", text_case: "upper" };
const data = { first_name: "maría josé" };
assert.strictEqual(R.textContent(el, data), "MARÍA JOSÉ");
assert.strictEqual(data.first_name, "maría josé");
assert.strictEqual(R.textContent({ type: "text_static", content: "feria de la ciudad", text_case: "title" }, {}), "Feria de la Ciudad");

// ---- el ajuste de texto mide lo que SE IMPRIME (ya transformado): nunca se corta, en vertical y horizontal, con y sin giro
{
  const fake = () => ({ style: {}, dataset: {}, children: [], appendChild(c) { this.children.push(c); return c; }, getContext: () => null });
  global.document = { createElement: fake };
  const datos = { first_name: "MARÍA DE LOS ÁNGELES", last_name: "rodríguez villamizar", entity: "golden eventos y logística s.a.s." };
  const cajas = [[50.9, 12, 16], [50.9, 10, 11], [85, 12, 18], [62, 10, 11]];             // vertical (58,9 mm de ancho) y horizontal (100 mm)
  for (const variable of Object.keys(datos)) for (const [w, h, pt] of cajas) for (const mode of ["as_is", "upper", "lower", "title"]) for (const rot of [0, 90, 349]) {
    const e = { id: "t", type: "text_variable", variable, x: 2, y: 2, width: w, height: h, font_size: pt, font_family: "Roboto", rotation: rot, text_case: mode };
    const d = R.renderElement(e, datos, {});
    assert.notStrictEqual(d.dataset.fit, "truncated", `${variable} ${mode} ${w}×${h} ${rot}°: no se recorta`);
    const shown = d.children[0].textContent.split("\n").join(" ");
    assert.strictEqual(shown, R.textContent(e, datos), `${variable} ${mode}: se dibuja el texto transformado completo`);
    assert.strictEqual(d.style.overflow, rot ? "visible" : "hidden");
  }
  delete global.document;
}

console.log("badge_text_case_check ok");
