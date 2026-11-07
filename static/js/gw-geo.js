/* gw-geo.js — países y ciudades (lógica pura, sin DOM). Datos: static/data/geo.json.
 * Pensado para enchufarse a un combobox: devuelve [{value,label}]. Mismas reglas de
 * normalización que app/geo.py (minúsculas y sin acentos). */
(function (root) {
  'use strict';

  var DEFAULT_LIMIT = 50;
  var data = null;
  var byCode = {};

  function normalize(text) {
    var s = String(text == null ? '' : text).toLowerCase();
    if (s.normalize) s = s.normalize('NFD').replace(/[̀-ͯ]/g, '');
    return s.replace(/\s+/g, ' ').trim();
  }

  function setData(d) {
    data = d && d.countries ? d : { countries: [] };
    byCode = {};
    data.countries.forEach(function (c) {
      c._n = normalize(c.name);
      c._e = normalize(c.en || '');
      c._k = c.code.toLowerCase();
      c._cn = (c.cities || []).map(normalize);
      byCode[c.code.toUpperCase()] = c;
    });
  }

  function load(url) {
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('geo ' + r.status); return r.json(); })
      .then(function (d) { setData(d); return d; });
  }

  /* 0 = empieza igual, 1 = una palabra empieza igual, 2 = contiene; -1 = no coincide. */
  function rank(norm, q) {
    if (!q) return 0;
    if (norm.indexOf(q) === 0) return 0;
    if (norm.indexOf(' ' + q) >= 0) return 1;
    return norm.indexOf(q) >= 0 ? 2 : -1;
  }

  function pick(list, limit) {
    return list.slice(0, limit > 0 ? limit : DEFAULT_LIMIT);
  }

  function countryOption(c) { return { value: c.code, label: c.name }; }

  /* Sin texto: la lista completa de países en orden alfabético (sin límite). */
  function searchCountries(query, limit) {
    if (!data) return [];
    var q = normalize(query);
    if (!q) return data.countries.map(countryOption);
    var hits = [];
    data.countries.forEach(function (c, i) {
      var a = rank(c._n, q), b = rank(c._e, q);
      var r = Math.min(a < 0 ? 9 : a, b < 0 ? 9 : b);
      if (c._k === q) r = -1;
      if (r < 9) hits.push({ c: c, r: r, i: i });
    });
    hits.sort(function (x, y) { return x.r - y.r || x.i - y.i; });
    return pick(hits.map(function (h) { return countryOption(h.c); }), limit);
  }

  function citiesOf(code) {
    var c = byCode[String(code || '').toUpperCase()];
    return c ? c.cities.map(function (x) { return { value: x, label: x }; }) : [];
  }

  /* Sin texto: las primeras `limit` (vienen por relevancia). Con texto: por rango y luego relevancia. */
  function searchCities(code, query, limit) {
    var c = byCode[String(code || '').toUpperCase()];
    if (!c) return [];
    var q = normalize(query);
    var hits = [];
    c.cities.forEach(function (name, i) {
      var r = rank(c._cn[i], q);
      if (r >= 0) hits.push({ name: name, r: r, i: i });
    });
    hits.sort(function (x, y) { return x.r - y.r || x.i - y.i; });
    return pick(hits.map(function (h) { return { value: h.name, label: h.name }; }), limit);
  }

  /* ¿Es una ciudad de la lista? Si no, el campo la deja como texto abierto. */
  function isKnownCity(code, text) {
    var c = byCode[String(code || '').toUpperCase()];
    return !!c && c._cn.indexOf(normalize(text)) >= 0;
  }

  function findCountry(text) {
    var q = normalize(text);
    if (!data || !q) return null;
    for (var i = 0; i < data.countries.length; i++) {
      var c = data.countries[i];
      if (q === c._k || q === c._n || q === c._e) return countryOption(c);
    }
    return null;
  }

  var api = {
    normalize: normalize, setData: setData, load: load, DEFAULT_LIMIT: DEFAULT_LIMIT,
    searchCountries: searchCountries, citiesOf: citiesOf, searchCities: searchCities,
    isKnownCity: isKnownCity, findCountry: findCountry
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.GWGeo = api;
})(typeof window !== 'undefined' ? window : globalThis);
