// País/ciudad de la plantilla con GWGeo + combobox (event-field-render.js): ciudades del país elegido, texto libre, recálculo al cambiar el país,
// el valor guardado sigue siendo el TEXTO, respaldo sin lista, y colores/enganches de mapa e inventario. DOM falso mínimo.
const assert = require('assert');
const GWGeo = require('../../static/js/gw-geo.js');
GWGeo.setData({ countries: [
  { code: 'CO', name: 'Colombia', en: 'Colombia', cities: ['Bogotá', 'Medellín', 'Girardot'] },
  { code: 'MX', name: 'México', en: 'Mexico', cities: ['Ciudad de México', 'Guadalajara'] }] });

// combobox falso: guarda opciones y el valor elegido; imita lo esencial de GWCombobox.attach
const attached = [];
const GWCombobox = { attach(input, cfg) {
  const cb = { cfg, options: cfg.options.slice(), chosen: null,
    setOptions(o) { cb.options = o.slice(); if (cb.chosen && !cb.chosen.free && !o.some((x) => x.value === cb.chosen.value)) { input.value = ''; cb.chosen = null; } },
    setValue(v) { const f = cb.options.filter((o) => String(o.value) === String(v))[0]; if (f) { input.value = f.label; cb.chosen = { value: f.value, free: false }; } else if (v) { input.value = String(v); cb.chosen = { value: String(v), free: true }; } else { input.value = ''; cb.chosen = null; } } };
  input._gwCombobox = cb; attached.push(input); return cb; } };

function input(value, extra) {
  const l = {}, a = {};
  return Object.assign({ value: value || '', dataset: {}, parentNode: null, ownerDocument: { getElementById: () => null },
    getAttribute: (k) => a[k], setAttribute: (k, v) => { a[k] = v; }, removeAttribute: (k) => { delete a[k]; },
    addEventListener: (t, f) => { (l[t] = l[t] || []).push(f); }, fire: (t, e) => (l[t] || []).forEach((f) => f(Object.assign({ type: t }, e))) }, extra || {});
}
global.window = global; globalThis.GWGeo = GWGeo; globalThis.GWCombobox = GWCombobox;
globalThis.fetch = undefined;
const EF = require('../../static/js/event-field-render.js');

(async () => {
  // 1) Sin lista de geo (sin url): respaldo, no se engancha nada
  let pais = input('Colombia'), ciudad = input('Bogotá');
  let api = await EF.geoPair(pais, ciudad, '');
  assert.strictEqual(api.ready, false); assert.strictEqual(attached.length, 0);
  api.set('Perú', 'Lima'); assert.strictEqual(pais.value, 'Perú'); assert.strictEqual(ciudad.value, 'Lima');

  // 2) Con lista: país con TODOS los países; ciudad = las del país; lo que se lee es el texto
  GWGeo.load = () => Promise.resolve();                       // la lista ya está cargada arriba (setData)
  pais = input('Colombia'); ciudad = input('Bogotá');
  api = await EF.geoPair(pais, ciudad, '/static/data/geo.json');
  assert.strictEqual(api.ready, true);
  assert.deepStrictEqual(pais._gwCombobox.options.map((o) => o.label), ['Colombia', 'México']);
  assert.strictEqual(pais.value, 'Colombia'); assert.strictEqual(ciudad.value, 'Bogotá');                        // lo que ya traían se conserva (texto)
  assert.deepStrictEqual(ciudad._gwCombobox.options.map((o) => o.label), ['Bogotá', 'Medellín', 'Girardot']);
  assert.strictEqual(ciudad._gwCombobox.cfg.allowFreeText, true, 'ciudad admite texto libre');
  assert.strictEqual(pais._gwCombobox.cfg.allowFreeText, true);

  // 3) Escribir un país a medias NO borra la ciudad; elegir otro país recalcula (la ciudad de la lista se suelta)
  pais.value = 'Mex'; pais.fire('gw:combobox-change', { detail: { value: 'Mex', free: true } });
  assert.strictEqual(ciudad.value, 'Bogotá');
  pais.value = 'México'; pais.fire('gw:combobox-change', { detail: { value: 'MX' } });
  assert.deepStrictEqual(ciudad._gwCombobox.options.map((o) => o.label), ['Ciudad de México', 'Guadalajara']);
  assert.strictEqual(ciudad.value, '', 'una ciudad de otro país se suelta');

  // 4) Texto libre: una ciudad que no está en la lista se conserva y sobrevive al cambio de país
  ciudad._gwCombobox.setValue('Villa Nueva');
  assert.strictEqual(ciudad.value, 'Villa Nueva'); assert.strictEqual(ciudad._gwCombobox.chosen.free, true);
  pais.value = 'Colombia'; pais.fire('gw:combobox-change', { detail: { value: 'CO' } });
  assert.strictEqual(ciudad.value, 'Villa Nueva');
  assert.deepStrictEqual(ciudad._gwCombobox.options.map((o) => o.label), ['Bogotá', 'Medellín', 'Girardot']);

  // 5) País desconocido (texto libre, p. ej. evento viejo) al salir del campo: sin ciudades sugeridas
  pais.value = 'Narnia'; pais.fire('focusout', {});
  assert.deepStrictEqual(ciudad._gwCombobox.options, []);

  // 6) set() programático (Editar evento): país por nombre, ciudades del país, ciudad del evento
  api.set('México', 'Guadalajara');
  assert.strictEqual(pais.value, 'México'); assert.strictEqual(ciudad.value, 'Guadalajara');
  api.set('', '');
  assert.strictEqual(pais.value, ''); assert.strictEqual(ciudad.value, ''); assert.deepStrictEqual(ciudad._gwCombobox.options, []);

  // 7) Reutilizar no engancha dos veces
  const n = attached.length; await EF.geoPair(pais, ciudad, '/x'); assert.strictEqual(attached.length, n);

  // 8) Los controles pintados de país/ciudad llevan los ganchos y siguen funcionando sin JS (datalist de respaldo)
  const f = (type, key) => ({ key, type, title: key, required: false, config: type === 'city' ? { country_key: 'country' } : {}, options: [] });
  const hc = EF.renderField(f('country', 'country'), { value: 'Colombia', ctx: { countries: ['Colombia'] } });
  assert(hc.includes('data-evf-enhance="country"') && hc.includes('<datalist') && hc.includes('value="Colombia"'));
  const hy = EF.renderField(f('city', 'city'), { value: 'Bogotá' });
  assert(hy.includes('data-evf-enhance="city"') && hy.includes('data-evf-country="country"'));

  // 9) afterMount engancha mapa e inventario SOLO si esos widgets existen (líneas de enganche para los otros agentes)
  const calls = [];
  globalThis.GWMap = { enhance(el, o) { calls.push(['map', el.id]); } }; globalThis.GWInventory = { enhance(el) { calls.push(['inv', el.id]); } };
  const host = { querySelectorAll: (sel) => (sel === '[data-evf-enhance="map"]' ? [{ id: 'm' }] : sel === '[data-evf-enhance="inventory"]' ? [{ id: 'i' }] : []), querySelector: () => null };
  await EF.afterMount(host, { geoUrl: '' });
  assert.deepStrictEqual(calls, [['map', 'm'], ['inv', 'i']]);
  delete globalThis.GWMap; delete globalThis.GWInventory;
  await EF.afterMount(host, {});                                    // sin widgets: no falla
  console.log('event_fields_geo_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
