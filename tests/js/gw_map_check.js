// Dirección con mapa (static/js/gw-map.js): lógica pura. Correr: node tests/js/gw_map_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const M = require('../../static/js/gw-map.js');

// números: coma o punto, basura -> null
assert.strictEqual(M.toNumber('4,6097'), 4.6097);
assert.strictEqual(M.toNumber(' -74.0817 '), -74.0817);
assert.strictEqual(M.toNumber('abc'), null);
assert.strictEqual(M.toNumber(''), null);
assert.strictEqual(M.toNumber('1e5'), null, 'sin notación científica');
assert.strictEqual(M.toNumber(NaN), null);

// límites
assert.ok(M.validLat(90) && M.validLat(-90) && !M.validLat(90.0001) && !M.validLat(null));
assert.ok(M.validLng(180) && M.validLng(-180) && !M.validLng(181) && !M.validLng('1'));

// parse: objeto, JSON, texto, `texto` como alias, descarta pares inválidos
assert.deepStrictEqual(M.parse({ text: 'Calle 1', lat: 4.6, lng: -74.08 }), { text: 'Calle 1', lat: 4.6, lng: -74.08 });
assert.deepStrictEqual(M.parse('{"texto":"Cra 7","lat":"4,5","lng":"-74,1"}'), { text: 'Cra 7', lat: 4.5, lng: -74.1 });
assert.deepStrictEqual(M.parse('Solo texto'), { text: 'Solo texto', lat: null, lng: null });
assert.deepStrictEqual(M.parse('{roto'), { text: '{roto', lat: null, lng: null });
assert.deepStrictEqual(M.parse(null), { text: '', lat: null, lng: null });
assert.deepStrictEqual(M.parse({ text: 'x', lat: 95, lng: 0 }), { text: 'x', lat: null, lng: null }, 'fuera de rango');
assert.deepStrictEqual(M.parse({ text: 'x', lat: 4 }), { text: 'x', lat: null, lng: null }, 'falta una coordenada');
assert.strictEqual(M.parse({ text: '<b>Hola</b>   mundo' }).text, 'bHola/b mundo', 'sin < ni >, espacios colapsados');
assert.strictEqual(M.parse({ text: 'a'.repeat(300) }).text.length, 200);
assert.strictEqual(M.parse({ lat: 4.12345678, lng: -74.98765432 }).lat, 4.123457, '6 decimales');

// serialize: forma del servidor {text,lat,lng} o null
assert.strictEqual(M.serialize({}), null);
assert.strictEqual(M.serialize(null), null);
assert.deepStrictEqual(M.serialize({ text: 'Sede', lat: '4.6', lng: '-74.1' }), { text: 'Sede', lat: 4.6, lng: -74.1 });
assert.deepStrictEqual(M.serialize({ lat: 4.6, lng: -74.1 }), { text: '', lat: 4.6, lng: -74.1 }, 'solo coordenadas también vale');
assert.deepStrictEqual(M.serialize({ text: 'Sin mapa' }), { text: 'Sin mapa', lat: null, lng: null });
assert.deepStrictEqual(M.parse(M.serialize({ text: 'A', lat: 1, lng: 2 })), { text: 'A', lat: 1, lng: 2 }, 'ida y vuelta');

// mostrar
assert.strictEqual(M.displayText({ text: 'Corferias', lat: 4.6, lng: -74.1 }), 'Corferias');
assert.strictEqual(M.displayText({ lat: 4.6097, lng: -74.0817 }), '4,60970; -74,08170');
assert.strictEqual(M.displayText(null), '');
assert.strictEqual(M.formatCoords(100, 0), '');

// coordenadas a mano
assert.deepStrictEqual(M.checkCoords('', ''), { ok: true, lat: null, lng: null, error: '' });
assert.deepStrictEqual(M.checkCoords('4,6', '-74,1'), { ok: true, lat: 4.6, lng: -74.1, error: '' });
assert.ok(!M.checkCoords('4,6', '').ok && /latitud y la longitud/.test(M.checkCoords('4,6', '').error));
assert.ok(/números/.test(M.checkCoords('x', '1').error));
assert.ok(/entre -90 y 90/.test(M.checkCoords('91', '1').error));
assert.ok(/entre -180 y 180/.test(M.checkCoords('1', '181').error));

// ritmo de Nominatim: nunca menos de 1 s entre peticiones
assert.strictEqual(M.waitMs(null, 1000), 0);
assert.strictEqual(M.waitMs(1000, 1200, 1100), 900);
assert.strictEqual(M.waitMs(1000, 5000, 1100), 0);
assert.ok(M.MIN_GAP_MS >= 1000);

// URL de búsqueda: sin autocompletar, idioma español, país acotado, nada personal
const u = new URL(M.searchUrl('Calle 100 # 8A-55, Bogotá', 'CO'));
assert.strictEqual(u.origin, 'https://nominatim.openstreetmap.org');
assert.strictEqual(u.pathname, '/search');
assert.strictEqual(u.searchParams.get('q'), 'Calle 100 # 8A-55, Bogotá');
assert.strictEqual(u.searchParams.get('countrycodes'), 'co');
assert.strictEqual(u.searchParams.get('accept-language'), 'es');
assert.strictEqual(u.searchParams.get('format'), 'jsonv2');
assert.ok(Number(u.searchParams.get('limit')) <= 10);
assert.ok(![...u.searchParams.keys()].some(k => /email|user|name|id|token/i.test(k)));
assert.strictEqual(new URL(M.searchUrl('Cali', '')).searchParams.get('countrycodes'), null, 'sin país, sin filtro');
assert.strictEqual(new URL(M.searchUrl('Cali', 'colombia')).searchParams.get('countrycodes'), null, 'solo códigos ISO-2');

// resultados de Nominatim
const res = M.parseResults([
  { display_name: 'Corferias, Bogotá', lat: '4.6300', lon: '-74.0950' },
  { display_name: 'Corferias, Bogotá', lat: '4.6300', lon: '-74.0950' },
  { display_name: 'Sin coordenadas' },
  { display_name: 'Fuera', lat: '100', lon: '0' },
  { lat: '1', lon: '1' },
  null,
]);
assert.deepStrictEqual(res, [{ label: 'Corferias, Bogotá', lat: 4.63, lng: -74.095 }]);
assert.deepStrictEqual(M.parseResults({ error: 'x' }), []);
assert.strictEqual(M.parseResults(Array.from({ length: 20 }, (_, i) => ({ display_name: 'L' + i, lat: '1', lon: String(i) }))).length, 6);

// país del contexto -> código ISO-2
assert.strictEqual(M.countryToCode('CO'), 'co');
assert.strictEqual(M.countryToCode('  '), '');
assert.strictEqual(M.countryToCode('Colombia'), '', 'sin GWGeo no se adivina el nombre');
const G = require('../../static/js/gw-geo.js');
G.setData(JSON.parse(fs.readFileSync(path.join(__dirname, '../../static/data/geo.json'), 'utf8')));
assert.strictEqual(M.countryToCode('Colombia', G), 'co');
assert.strictEqual(M.countryToCode('mexico', G), 'mx');
assert.strictEqual(M.countryToCode('Colom', G), '', 'un nombre incompleto no acota la búsqueda');

// Leaflet con versión fija y desde cdnjs; teselas de OSM con atribución
const src = fs.readFileSync(path.join(__dirname, '../../static/js/gw-map.js'), 'utf8');
assert.ok(/cdnjs\.cloudflare\.com\/ajax\/libs\/leaflet\/'? ?\+? ?LEAFLET_VERSION|leaflet\/' \+ LEAFLET_VERSION/.test(src));
assert.ok(/\d+\.\d+\.\d+/.test(M.LEAFLET_VERSION));
assert.ok(src.includes('© OpenStreetMap') && src.includes('OpenStreetMap</a>'));
assert.ok(!/\.style\.|cssText|onclick|alert\(|confirm\(|prompt\(/.test(src), 'sin estilos fijos, onclick ni diálogos del navegador');

console.log('gw_map_check: OK');
