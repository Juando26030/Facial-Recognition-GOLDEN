// QR en vCard (Fase 10, C): static/js/vcard.js + lectores (qr.js, search-core.js). Correr: node tests/js/qr_vcard_check.js
const assert = require('assert');
const V = require('../../static/js/vcard.js');
const { parse, classify, isDynamic, unwrap, collect } = require('../../static/js/qr.js');
const SC = require('../../static/js/search-core.js');
const qrcode = require('../../static/vendor/qrcode-generator-1.4.4.min.js');

// ---- construir: nombre, teléfono y el código en NOTE
const card = V.build({ first_name: 'Ana', last_name: 'Pérez', phone: '300 123 4567', note: '1016100329|Ana|Pérez' });
assert.strictEqual(card, ['BEGIN:VCARD', 'VERSION:3.0', 'N:Pérez;Ana;;;', 'FN:Ana Pérez', 'TEL:300 123 4567', 'NOTE:GW:1016100329|Ana|Pérez', 'END:VCARD'].join('\n'));
assert.ok(!V.build({ first_name: 'Ana', last_name: 'P', note: 'x' }).includes('TEL'), 'sin teléfono no hay TEL');
assert.ok(V.build({ note: 'x' }).includes('FN:Asistente'));
assert.ok(V.build({ first_name: 'A;B,C', last_name: 'D', note: 'x' }).includes('N:D;A\\;B\\,C;;;'), 'se escapan ; y ,');

// ---- sacar el código de NOTE (round trip) y seguir aceptando el formato anterior
const payloads = ['1016100329', '1016100329|Ana|Pérez', 'Ana, la; de\\Mora|1.016.100.329', 'gwq1.5.12345678.' + 'a'.repeat(20), 'gwq1s.5.' + 'b'.repeat(20)];
for (const p of payloads) {
  assert.strictEqual(V.unwrap(V.build({ first_name: 'Ana', last_name: 'Mora', phone: '3001234567', note: p })), p, p);
  assert.strictEqual(unwrap(V.build({ first_name: 'Ana', note: p })), p);
}
assert.strictEqual(unwrap('1016100329|Ana|Mora'), '1016100329|Ana|Mora');            // formato anterior: igual
assert.strictEqual(unwrap('  gwq1s.5.' + 'b'.repeat(20)), '  gwq1s.5.' + 'b'.repeat(20));
const foreign = 'BEGIN:VCARD\nVERSION:3.0\nFN:Otro\nEND:VCARD';
assert.strictEqual(unwrap(foreign), foreign, 'una vCard ajena no se toca');
assert.strictEqual(unwrap(card.replace(/\n/g, '\r\n')), '1016100329|Ana|Pérez', 'CRLF');
assert.strictEqual(unwrap(card.replace(/\n/g, '')), '1016100329|Ana|PérezEND:VCARD'.replace('END:VCARD', ''), 'un lector que se come los saltos de línea');
assert.strictEqual(unwrap(card.replace('NOTE:GW:1016100329|Ana|Pérez', 'NOTE:GW:1016100329|Ana|\r\n Pérez')), '1016100329|Ana|Pérez', 'línea doblada');

// ---- los lectores
assert.deepStrictEqual(parse(card), { cedula: '1016100329', nombres: 'Ana', apellidos: 'Pérez', isQr: true });
assert.deepStrictEqual(parse('1016100329|Ana|Pérez'), parse(card));
assert.deepStrictEqual(classify(card, 'qr_code', null), { kind: 'qr', cedula: '1016100329', nombres: 'Ana', apellidos: 'Pérez' });
const dyn = 'gwq1.5.12345678.' + 'a'.repeat(20);
assert.strictEqual(isDynamic(V.build({ first_name: 'Ana', note: dyn })), true);
assert.strictEqual(isDynamic(card), false);
assert.strictEqual(isDynamic(dyn), true);
assert.strictEqual(parse(V.build({ first_name: 'Ana', note: '1016100329' })).cedula, '1016100329');
const q = SC.classifyQuery(card);
assert.strictEqual(q.kind, 'qr'); assert.strictEqual(q.cedula, SC.classifyQuery('1016100329|Ana|Pérez').cedula);

// ---- lector de mano: la vCard llega en varias líneas, cada una con su Enter
let out = [];
for (const line of card.split('\n')) out.push(collect(line));
assert.deepStrictEqual(out.slice(0, -1).filter((x) => x !== null), [], 'mientras no termina, nada');
assert.strictEqual(out[out.length - 1], card);
assert.strictEqual(collect('1016100329|Ana|Mora'), '1016100329|Ana|Mora');            // lectura normal: pasa tal cual
assert.strictEqual(collect('  52123456 '), '52123456');

// ---- densidad: la vCard cabe en una versión de QR chica con nivel L (el tamaño de la etiqueta no cambia: solo hay más cuadritos)
function version(text, level) {
  qrcode.stringToBytes = qrcode.stringToBytesFuncs['UTF-8'];
  const qr = qrcode(0, level); qr.addData(text); qr.make();
  return (qr.getModuleCount() - 17) / 4;
}
const typical = V.build({ first_name: 'María Fernanda', last_name: 'Rodríguez Castañeda', phone: '3001234567', note: '1016100329|María Fernanda|Rodríguez Castañeda' });
const dynamicCard = V.build({ first_name: 'María Fernanda', last_name: 'Rodríguez Castañeda', phone: '3001234567', note: dyn });
const longest = V.build({ first_name: 'Juan Sebastián Alejandro', last_name: 'Rodríguez Castañeda de la Hoz', phone: '+57 300 123 4567', note: '1016100329|Juan Sebastián Alejandro|Rodríguez Castañeda de la Hoz' });
console.log('versión QR  anterior(M):', version('1016100329|María Fernanda|Rodríguez Castañeda', 'M'), ' vCard típica(L):', version(typical, 'L'), ' vCard dinámica(L):', version(dynamicCard, 'L'), ' vCard larga(L):', version(longest, 'L'));
assert.ok(version(typical, 'L') <= 8, 'la vCard típica cabe en versión 8 (49 módulos) con nivel L');
assert.ok(version(dynamicCard, 'L') <= 8);
assert.ok(version(longest, 'L') <= 10, 'aun el peor caso razonable no pasa de versión 10 (57 módulos)');
assert.ok(version(typical, 'L') < version(typical, 'M'), 'L es más chico que M para el mismo texto');
console.log('qr_vcard_check OK');

// ---- 19-nov-2026: cada QR elige qué datos lleva su vCard; sin elegir: nombre y teléfono; «sin vCard» = solo el código
{
  const BR = require("../../static/js/badge-render.js");
  global.window = global.window || {}; window.GWVcard = V; global.GWVcard = V; global.qrcode = qrcode;
  const VF = ["org", "title", "phone", "email", "categories"];
  const person = { first_name: "María Fernanda", last_name: "Rodríguez Castañeda", phone: "3001234567", email: "maria@correo.com", entity: "Corporación Universitaria Minuto de Dios", role: "Coordinador general", categories: "VIP, Staff" };
  const t = (el) => BR.qrText(el, "1016100329", person).text;
  const base = t({});
  assert.ok(base.includes("TEL:") && !base.includes("EMAIL:") && !base.includes("ORG:") && !base.includes("TITLE:"), "por defecto: nombre y teléfono");
  const mini = t({ vcard_fields: [] });
  assert.ok(!mini.includes("TEL:") && mini.includes("FN:María Fernanda Rodríguez Castañeda"), "sin datos extra: solo el nombre y el código");
  const all = t({ vcard_fields: ["org", "title", "phone", "email", "categories"] });
  ["ORG:", "TITLE:", "TEL:", "EMAIL:", "CATEGORIES:"].forEach((k) => assert.ok(all.includes(k), k));
  assert.deepStrictEqual(BR.qrText({ vcard: false }, "1016100329", person), { text: "1016100329", card: false, level: "M" }, "sin vCard: solo el código");
  assert.strictEqual(V.unwrap(all), "1016100329", "el lector saca el código igual");
  if (typeof globalThis.qrcode !== "undefined") {
    const dens = (el) => { const q = BR.qrText(el, "1016100329|María Fernanda|Rodríguez Castañeda", person); return BR.qrDensity(q.text, q.level); };
    const dAll = dens({ vcard_fields: ["org", "title", "phone", "email", "categories"] }), dMini = dens({ vcard_fields: [] }), dPlain = dens({ vcard: false });
    console.log("densidad (versión): todo", dAll.version, "| solo nombre", dMini.version, "| sin vCard", dPlain.version);
    assert.ok(dAll.version > dMini.version && dMini.version >= dPlain.version, "más datos = QR más denso");
    assert.ok(dPlain.level === "good", "solo el código: lectura buena");
  }
  // modos de QR (18-nov-2026): vcard (por defecto) | mecard | link | code; «vcard:false» de antes = code
  const withCard = Object.assign({}, person, { card_url: "https://app.golden-eventos.com/tarjeta/AbCdEfGhIjKlMnOpQrStUvWx" });
  const tm = (el, who) => BR.qrText(el, "1016100329", who || withCard);
  assert.strictEqual(BR.qrMode({}), "vcard"); assert.strictEqual(BR.qrMode({ vcard: false }), "code"); assert.strictEqual(BR.qrMode({ qr_mode: "link", vcard: false }), "link"); assert.strictEqual(BR.qrMode({ qr_mode: "raro" }), "vcard");
  assert.strictEqual(tm({ qr_mode: "code" }).text, "1016100329");
  const lk = tm({ qr_mode: "link" });
  assert.ok(lk.text.startsWith("https://app.golden-eventos.com/tarjeta/AbCd") && lk.text.endsWith("#GW:1016100329"), "enlace + código en el fragmento"); assert.strictEqual(V.unwrap(lk.text), "1016100329");
  assert.strictEqual(tm({ qr_mode: "link" }, person).text, "1016100329", "sin enlace público: solo el código");
  const mc = tm({ qr_mode: "mecard", vcard_fields: ["phone", "email", "org"] });
  assert.ok(mc.text.startsWith("MECARD:N:") && mc.text.includes("TEL:3001234567;") && mc.text.includes("EMAIL:maria@correo.com;") && !mc.text.includes("ORG"), "MECARD: nombre, teléfono y correo"); assert.strictEqual(V.unwrap(mc.text), "1016100329");
  assert.strictEqual(tm({ qr_mode: "mecard" }).text.includes("EMAIL"), false, "MECARD por defecto: nombre y teléfono");
  if (typeof globalThis.qrcode !== "undefined") {
    const v = (el) => { const q = tm(el); return BR.qrDensity(q.text, q.level).version; };
    console.log("versión por modo: código", v({ qr_mode: "code" }), "| enlace", v({ qr_mode: "link" }), "| MECARD", v({ qr_mode: "mecard", vcard_fields: ["phone", "email"] }), "| vCard completa", v({ vcard_fields: VF }));
    assert.ok(v({ qr_mode: "link" }) <= 6, "el enlace queda chico"); assert.ok(v({ qr_mode: "mecard", vcard_fields: ["phone", "email"] }) < v({ vcard_fields: VF }), "MECARD más chico que la vCard completa");
  }
  // escarapela digital (19-nov-2026): el QR de la plantilla lleva el código DINÁMICO con el modo del diseño y el lector lo reconoce igual
  const dyn = "gwq1.123.4567.0123456789abcdef0123";
  ["vcard", "mecard", "link", "code"].forEach((mode) => {
    const txt = BR.qrText({ qr_mode: mode, vcard_fields: ["phone", "email"] }, dyn, withCard).text;
    assert.strictEqual(V.unwrap(txt), dyn, "el código dinámico sale intacto en el modo " + mode);
    assert.ok(isDynamic(txt), "el lector lo reconoce como dinámico en el modo " + mode);
    assert.ok(!txt.includes("1016100329"), "el QR digital nunca lleva la cédula");
  });
  assert.strictEqual(typeof BR.redrawQrs, "function");
  delete global.window; delete global.GWVcard; delete global.qrcode;
}
