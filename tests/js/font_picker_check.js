// Comprobación de static/js/font-picker.js: el buscador y que Configuración y el diseñador lean la MISMA lista. Se corre con: node tests/js/font_picker_check.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");

global.window = global;
require("../../static/js/fonts-propias.js");           // define window.GoldenFonts (generado por scripts/gen_fonts_css.py)
const Picker = require("../../static/js/font-picker.js");

const names = global.GoldenFonts.choices;
assert.ok(names.length >= 40, "todas las tipografías alojadas, no una lista corta");
assert.strictEqual(new Set(names).size, names.length, "sin repetidas");
["Roboto", "Open Sans", "Montserrat", "Playfair Display", "Merriweather", "Bebas Neue", "Lato", "Pacifico", "Zilla Slab"].forEach((n) => assert.ok(names.includes(n), n));

// buscador: sin tildes, sin mayúsculas, por cualquier parte del nombre
assert.deepStrictEqual(Picker.filter(names, ""), names);
assert.deepStrictEqual(Picker.filter(names, "  "), names);
assert.deepStrictEqual(Picker.filter(names, "roboto"), ["Roboto"]);
assert.deepStrictEqual(Picker.filter(["Bebas Neue", "Open Sans"], "SANS"), ["Open Sans"]);
assert.ok(Picker.filter(names, "sans").length >= 5);
assert.deepStrictEqual(Picker.filter(names, "zzz-no-existe"), []);
assert.deepStrictEqual(Picker.filter(["Josefin Sans"], "josefín"), ["Josefin Sans"]);

// cada familia tiene sus archivos y su declaración @font-face (se ve y se imprime igual en cualquier equipo)
const css = fs.readFileSync(path.join(__dirname, "../../static/css/fonts-propias.css"), "utf8");
names.forEach((n) => assert.ok(css.includes(`font-family: '${n}'`), `falta @font-face de ${n}`));
(css.match(/fonts\/[\w.-]+\.woff2/g) || []).forEach((f) => assert.ok(fs.existsSync(path.join(__dirname, "../../static", f)), `falta el archivo ${f}`));

// una familia vieja o desconocida se lee como Roboto (plantillas viejas), una conocida queda igual
assert.strictEqual(global.GoldenFonts.resolve("Lato"), "Lato");
assert.strictEqual(global.GoldenFonts.resolve("Fuente Inventada"), "Roboto");

// ensureLoaded sin navegador no falla
Picker.ensureLoaded("Roboto").then(() => console.log("font_picker_check ok"));
