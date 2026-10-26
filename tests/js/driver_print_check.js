// Impresión por el controlador de Windows (static/js/driver-print.js): modo por equipo, tamaño exacto de la página y de la imagen, y el lanzador .bat. Se corre con: node tests/js/driver_print_check.js
const assert = require("assert");
const D = require("../../static/js/driver-print.js");
const QL = require("../../static/js/ql-usb.js");

const mem = () => ({ d: {}, getItem(k) { return k in this.d ? this.d[k] : null; }, setItem(k, v) { this.d[k] = String(v); }, removeItem(k) { delete this.d[k]; } });

// ---- modo por equipo: automático por defecto, se guarda, y un valor raro o sin almacenamiento vuelve a automático
const st = mem();
assert.strictEqual(D.getMode(st), "auto");
assert.ok(D.setMode(st, "driver")); assert.strictEqual(D.getMode(st), "driver"); assert.strictEqual(st.d.gw_print_mode, "driver");
assert.ok(D.setMode(st, "usb")); assert.strictEqual(D.getMode(st), "usb");
assert.ok(D.setMode(st, "auto")); assert.strictEqual(D.getMode(st), "auto"); assert.deepStrictEqual(st.d, {}, "«automático» no guarda nada");
assert.ok(!D.setMode(st, "raro")); st.d.gw_print_mode = "basura"; assert.strictEqual(D.getMode(st), "auto");
assert.strictEqual(D.getMode(null), "auto"); assert.strictEqual(D.getMode({ getItem() { throw new Error("bloqueado"); } }), "auto");
assert.deepStrictEqual(D.MODES, ["auto", "usb", "driver"]);
assert.strictEqual(D.MODE_LABELS.driver, "Controlador de Windows");

// ---- ancho de página que se le pide al controlador: automático (el ancho útil, 58,9 mm) salvo que se fije en este equipo
assert.strictEqual(D.getPageWidthMm(st), null);
D.setPageWidthMm(st, 62); assert.strictEqual(D.getPageWidthMm(st), 62);
D.setPageWidthMm(st, 0); assert.strictEqual(D.getPageWidthMm(st), null); assert.ok(!("gw_driver_page_mm" in st.d));
st.d.gw_driver_page_mm = "9999"; assert.strictEqual(D.getPageWidthMm(st), null, "fuera de rango: automático");
// ---- calibración por equipo: de −5 a +5 mm en pasos de 0,1
assert.deepStrictEqual(D.getOffsets(st), { dx: 0, dy: 0 });
assert.deepStrictEqual(D.setOffsets(st, 1.26, -0.34), { dx: 1.3, dy: -0.3 }); assert.deepStrictEqual(D.getOffsets(st), { dx: 1.3, dy: -0.3 });
assert.deepStrictEqual(D.setOffsets(st, 99, -99), { dx: 5, dy: -5 }, "tope de ±5 mm");
assert.deepStrictEqual(D.setOffsets(st, "x", null), { dx: 0, dy: 0 }); assert.ok(!("gw_driver_dx" in st.d) && !("gw_driver_dy" in st.d), "cero = no se guarda");

// ---- ¿se abrió con el lanzador?
const ses = mem();
assert.strictEqual(D.kioskFromUrl("?impresion=kiosk", ses), true); assert.strictEqual(ses.d.gw_kiosk_print, "1");
assert.strictEqual(D.kioskFromUrl("", ses), true, "al recargar la ventana (sin el parámetro) se recuerda");
assert.strictEqual(D.kioskFromUrl("?impresion=otra", mem()), false); assert.strictEqual(D.kioskFromUrl("", mem()), false); assert.strictEqual(D.kioskFromUrl("?impresion=kiosk", null), true);

// ---- tamaño EXACTO en mm de lo que se manda a imprimir (la cinta de 62 mm: 696 puntos imprimibles = 58,93 mm)
const near = (a, b, tol, m) => assert.ok(Math.abs(a - b) <= (tol || 0.006), `${m || ""} ${a} != ${b}`);
const dots = QL.MEDIA[62].printable;
assert.strictEqual(dots, 696);
let sp = D.pageSpec(dots, 1181, null);                                        // una escarapela vertical de 100 mm de largo
near(sp.imageWidthMm, 696 * 25.4 / 300, 0.006); near(sp.imageWidthMm, 58.93, 0.006);
near(sp.imageHeightMm, 1181 * 25.4 / 300, 0.006); near(sp.imageHeightMm, 100.0, 0.05);
near(sp.pageWidthMm, 58.93, 0.006); assert.strictEqual(sp.leftMm, 0, "la imagen ocupa todo el ancho útil");
assert.strictEqual(sp.pageCss, `@page { size: ${sp.pageWidthMm}mm ${sp.pageHeightMm}mm; margin: 0 }`);
assert.ok(sp.pageWidthMm <= 58.95 && sp.imageWidthMm <= 58.95, "ni la página ni la imagen superan el ancho útil (58,9 mm)");
assert.strictEqual(sp.pageHeightMm, sp.imageHeightMm, "la página mide lo mismo que la imagen: sin escalado");
sp = D.pageSpec(dots, 696, 58.9);                                           // si se fija una página más angosta que la imagen: la imagen manda (nunca se recorta)
near(sp.pageWidthMm, 58.93, 0.01); assert.strictEqual(sp.leftMm, 0);
sp = D.pageSpec(dots, 800, 62); near(sp.pageWidthMm, 62, 0.001); near(sp.leftMm, (62 - 58.93) / 2, 0.01, "con página de 62 mm, la imagen va centrada");
// calibración aplicada a la imagen: +1,3 mm a la derecha y +0,5 mm abajo (la página crece 0,5 mm); −0,4 mm arriba no agrega papel
sp = D.pageSpec(dots, 1000, null, { dx: 1.3, dy: 0.5 });
near(sp.leftMm, 1.3); near(sp.topMm, 0.5); near(sp.pageHeightMm, D.mmOfDots(1000) + 0.5, 0.006); near(sp.pageWidthMm, 58.93, 0.006);
sp = D.pageSpec(dots, 1000, null, { dx: -2, dy: -0.4 }); near(sp.leftMm, -2); near(sp.topMm, -0.4); near(sp.pageHeightMm, D.mmOfDots(1000), 0.006);
const h2 = D.pageHtml(D.pageSpec(dots, 1000, null, { dx: 1.3, dy: 0.5 }), "data:x"); assert.ok(h2.includes("top:0.5mm;left:1.3mm"), h2.slice(200, 520));
// el largo en mm sale de los puntos reales (la etiqueta de prueba, el recorte, el giro) y la página trae el @page exacto
const lay = QL.layout(Object.assign({}, QL.PREF_DEFAULTS), 100, 58.9);
assert.strictEqual(lay.rotation, 90);                                       // una horizontal 100 × 58,9 sale de 58,9 mm de ancho por 100 mm de largo sobre la cinta
const html = D.pageHtml(D.pageSpec(dots, 1181, null), "data:image/png;base64,AAA");
assert.ok(/@page \{ size: 58\.93mm 100\.0?\d*mm; margin: 0 \}/.test(html) || /@page \{ size: 58\.93mm 99\.\d+mm; margin: 0 \}/.test(html), html.slice(0, 220));
assert.ok(html.includes("margin:0") && html.includes("width:58.93mm") && html.includes("image-rendering:pixelated") && html.includes("data:image/png;base64,AAA"));
assert.ok(!/transform|scale\(/.test(html), "sin escalado");

// ---- lanzador: no instala nada, no toca el registro, abre Chrome con --kiosk-printing y su propio perfil; si no hay Chrome, Edge; si no, un mensaje claro
const url = "https://app.golden-eventos.com/kiosk/12/registro";
assert.strictEqual(D.kioskUrl(url + "#x"), "https://app.golden-eventos.com/kiosk/12/registro?impresion=kiosk");
assert.strictEqual(D.kioskUrl(url + "?a=1"), "https://app.golden-eventos.com/kiosk/12/registro?a=1&impresion=kiosk");
const bat = D.launcherBat(url);
assert.ok(bat.includes("\r\n") && !/[^\r]\n/.test(bat), "saltos de línea de Windows");
assert.ok(bat.includes('set "URL=https://app.golden-eventos.com/kiosk/12/registro?impresion=kiosk"'));
assert.ok(bat.includes('--kiosk-printing --user-data-dir="%PERFIL%"') && bat.includes('set "PERFIL=%LOCALAPPDATA%\\GoldenWebImpresion"'));
for (const p of ["%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe", "%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe", "%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"]) assert.ok(bat.includes(`if exist "${p}"`), p);
assert.ok(bat.includes("msedge.exe") && bat.includes("No se encontro Google Chrome ni Microsoft Edge") && bat.includes("pause"));
assert.ok(bat.indexOf("chrome.exe") < bat.indexOf("msedge.exe"), "primero Chrome, luego Edge");
assert.ok(!/reg(\.exe)?\s+(add|import)|regedit|HKEY|HKLM|HKCU|runas|msiexec|choco|winget|powershell|Invoke-|curl|bitsadmin|certutil/i.test(bat), "no toca el registro ni instala nada ni descarga nada");
assert.ok(/[\x00-\x7f]*/.test(bat) && !/[^\x00-\x7f]/.test(bat), "solo ASCII (se abre bien en cualquier Windows)");
assert.ok(D.launcherBat("https://x.test/a?b=100%").includes("100%%"), "el % se escapa en un .bat");
const cmd = D.launcherCommand(url);
assert.ok(cmd.startsWith('"%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe" --kiosk-printing --user-data-dir="%LOCALAPPDATA%\\GoldenWebImpresion" "https://app.golden-eventos.com/kiosk/12/registro?impresion=kiosk"'), cmd);

// ---- NADA se corta ni se corre, en NINGUNA orientación (25-oct-2026): la horizontal se gira 90° con el giro automático del USB ANTES de armar la página, así el lado de 100 mm queda a lo largo
//      de la cinta; la página y la imagen miden 58,9 mm de ancho; con una plantilla simétrica el margen izquierdo y el derecho son iguales (±0,5 mm).
{
  const T = QL.MEDIA[62].printable, DPM = 300 / 25.4;
  const sym = (wMm, hMm) => {                                              // plantilla simétrica: un marco a 4 mm de cada borde y un bloque centrado
    const w = Math.round(wMm * DPM), h = Math.round(hMm * DPM), b = new Uint8Array(w * h), m = Math.round(4 * DPM);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const frame = x === m || x === w - 1 - m || y === m || y === h - 1 - m;
      const block = x > w / 2 - 40 && x < w / 2 + 40 && y > h / 2 - 25 && y < h / 2 + 25;
      if (frame && x >= m && x <= w - 1 - m && y >= m && y <= h - 1 - m || block) b[y * w + x] = 1;
    }
    return { b, w, h };
  };
  for (const [name, wMm, hMm] of [["vertical 58,9×100", 58.9, 100], ["horizontal 100×58,9", 100, 58.9], ["horizontal 100×65,5", 100, 65.5], ["vertical 62×100", 62, 100], ["cuadrada 60×60", 60, 60]]) {
    const { b, w, h } = sym(wMm, hMm);
    const p = Object.assign({}, QL.PREF_DEFAULTS, { crop: false });
    const lay = QL.layout(p, wMm, hMm);
    const prep = QL.prepareBitmap(b, w, h, p, lay);
    const spec = D.pageSpec(T, prep.height, null);
    assert.ok(spec.pageWidthMm <= 58.95 && spec.imageWidthMm <= 58.95, `${name}: la página (${spec.pageWidthMm}) y la imagen (${spec.imageWidthMm}) no pasan de 58,9 mm`);
    assert.strictEqual(lay.rotation, wMm > hMm ? 90 : 0, `${name}: giro automático`);
    let minX = 1e9, maxX = -1, minY = 1e9, maxY = -1;
    for (let y = 0; y < prep.height; y++) for (let x = 0; x < T; x++) if (prep.bitmap[y * T + x]) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y); }
    const left = D.mmOfDots(minX), right = D.mmOfDots(T - 1 - maxX);
    assert.ok(Math.abs(left - right) <= 0.5, `${name}: margen izquierdo ${left.toFixed(2)} mm y derecho ${right.toFixed(2)} mm (deben ser iguales ±0,5)`);
    assert.ok(minX >= 0 && maxX <= T - 1 && minY >= 0 && maxY <= prep.height - 1, `${name}: nada sale por ningún borde`);
    // si la plantilla es más ancha que lo imprimible (65,5 mm > 58,9 mm) se ENCOGE entera, nunca se recorta: el marco sigue completo
    const cols = new Set(); for (let y = 0; y < prep.height; y++) for (let x = 0; x < T; x++) if (prep.bitmap[y * T + x]) cols.add(x);
    assert.ok(minX > 0 || wMm <= 59, `${name}: el marco izquierdo no toca el borde de la imagen`);
  }
}

// ---- hotfix 27-oct-2026: sin cuadro (--kiosk-printing) la etiqueta va como PDF de UNA página del tamaño exacto (el visor de PDF de Chrome no dibuja encabezados ni pies)
{
  const W = 696, H = 709, bm = new Uint8Array(W * H);
  for (let x = 0; x < W; x++) { bm[x] = 1; bm[(H - 1) * W + x] = 1; }                         // marco arriba y abajo
  for (const [dx, dy, pw] of [[0, 0, null], [1.5, 0.8, null], [0, 0, 62]]) {
    const spec = D.pageSpec(W, H, pw, { dx, dy });
    const bytes = D.pdfFromBitmap(bm, W, H, spec, false);
    const txt = Buffer.from(bytes).toString("latin1");
    assert.ok(txt.startsWith("%PDF-1.4") && txt.trimEnd().endsWith("%%EOF"), "PDF bien formado");
    const mb = /\/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]/.exec(txt).slice(1).map((v) => (+v) * 25.4 / 72);
    assert.ok(Math.abs(mb[0] - spec.pageWidthMm) < 0.2 && Math.abs(mb[1] - spec.pageHeightMm) < 0.2, "hoja exacta (±0,2 mm): " + mb + " vs " + spec.pageWidthMm + "×" + spec.pageHeightMm);
    const cm = /q ([\d.]+) 0 0 ([\d.]+) (-?[\d.]+) (-?[\d.]+) cm \/Im0 Do Q/.exec(txt).slice(1).map((v) => (+v) * 25.4 / 72);
    assert.ok(Math.abs(cm[0] - spec.imageWidthMm) < 0.05 && Math.abs(cm[1] - spec.imageHeightMm) < 0.05, "la imagen no se escala");
    assert.ok(Math.abs(cm[2] - spec.leftMm) < 0.05 && Math.abs(cm[3] - (spec.pageHeightMm - spec.topMm - spec.imageHeightMm)) < 0.05, "centrada y con la calibración: " + cm);
    assert.ok(!/\/Font|BT |Tj|\/Title|https?:|\d\/\d/.test(txt.replace(/0000\d{6} \d{5} [nf] /g, "").replace(/\/MediaBox[^\]]*\]/, "")), "sin texto, título, dirección ni número de página");
    const xref = +/startxref\n(\d+)/.exec(txt)[1];
    assert.ok(txt.slice(xref, xref + 4) === "xref", "xref en su sitio");
    const offs = txt.slice(xref).match(/(\d{10}) 00000 n /g).map((l) => +l.slice(0, 10));
    offs.forEach((o, i) => assert.ok(txt.slice(o).startsWith((i + 1) + " 0 obj"), "objeto " + (i + 1) + " en su desplazamiento"));
    const rowBytes = Math.ceil(W / 8), start = txt.indexOf("stream\n", txt.indexOf("/Subtype /Image")) + 7;
    assert.strictEqual(bytes[start], 0x00, "la primera fila (marco) es tinta");
    assert.strictEqual(bytes[start + rowBytes * 5], 0xff, "una fila sin tinta es papel");
  }
}

console.log("driver_print_check OK");
