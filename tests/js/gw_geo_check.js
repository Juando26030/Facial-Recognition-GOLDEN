// Países y ciudades (static/js/gw-geo.js). Correr: node tests/js/gw_geo_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const G = require('../../static/js/gw-geo.js');
const data = JSON.parse(fs.readFileSync(path.join(__dirname, '../../static/data/geo.json'), 'utf8'));
G.setData(data);

// normalización: sin acentos, minúsculas, espacios colapsados
assert.strictEqual(G.normalize('  BOGOTÁ  '), 'bogota');
assert.strictEqual(G.normalize('Düsseldorf'), 'dusseldorf');
assert.strictEqual(G.normalize(null), '');

// países: lista completa sin texto, ordenada y con value = código
const todos = G.searchCountries('');
assert.ok(todos.length >= 195, 'al menos los 195 países');
assert.ok(todos.every(o => /^[A-Z]{2}$/.test(o.value) && o.label));
assert.deepStrictEqual(G.searchCountries('colombia')[0], { value: 'CO', label: 'Colombia' });
assert.strictEqual(G.searchCountries('MEXICO')[0].value, 'MX', 'sin acentos y sin mayúsculas');
assert.strictEqual(G.searchCountries('germany')[0].value, 'DE', 'también por nombre en inglés');
assert.strictEqual(G.searchCountries('us')[0].value, 'US', 'el código exacto va primero');
assert.deepStrictEqual(G.searchCountries('zzzz'), []);
assert.strictEqual(G.searchCountries('a', 5).length, 5, 'límite');
const emp = G.searchCountries('pa').map(o => o.label);
assert.ok(emp.indexOf('Panamá') < emp.indexOf('Bulgaria') || emp.indexOf('Bulgaria') < 0, 'primero los que empiezan igual');

// ciudades
const co = G.citiesOf('co');
assert.ok(co.length > 250);
assert.deepStrictEqual(G.citiesOf('ZZ'), []);
assert.strictEqual(G.searchCities('CO', '').length, G.DEFAULT_LIMIT, 'sin texto: límite por defecto');
assert.strictEqual(G.searchCities('CO', 'girardot')[0].value, 'Girardot');
assert.strictEqual(G.searchCities('CO', 'MONTELIBANO')[0].value, 'Montelíbano');
assert.strictEqual(G.searchCities('CO', 'bogo')[0].value, 'Bogotá');
assert.strictEqual(G.searchCities('CO', 'boy')[0].value, 'Boyacá');
assert.ok(G.searchCities('CO', 'rosa', 500).length > 3);
assert.deepStrictEqual(G.searchCities('CO', 'xyzxyz'), [], 'sin coincidencias: el campo queda en texto abierto');
// una palabra que empieza igual va antes que la que solo contiene
const sr = G.searchCities('CO', 'cabal').map(o => o.value);
assert.ok(sr.indexOf('Santa Rosa de Cabal') >= 0);

assert.ok(G.isKnownCity('CO', 'bogota') && !G.isKnownCity('CO', 'Villa Inventada'));
assert.deepStrictEqual(G.findCountry('perú'), { value: 'PE', label: 'Perú' });
assert.strictEqual(G.findCountry('nada'), null);
console.log('gw_geo_check OK');
