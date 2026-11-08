/* GoldenWeb 2.0 — Dirección con mapa (OpenStreetMap). Widget del tipo de campo `address_map` de la plantilla de evento.
   Valor: {text, lat, lng} (igual que lo valida app/event_template.py; al leer se acepta también `texto`). Se engancha al contenedor
   `[data-evf-enhance="map"]` de static/js/event-field-render.js, que ya trae el campo de texto (data-evf-part="text") y los ocultos lat/lng.
   API:  GWMap.enhance(el, opts)  ·  GWMap.parse(value)  ·  GWMap.serialize(state)  ·  GWMap.displayText(value)
   opts (todo opcional): countryCode | getCountryCode() (ISO-2, acota la búsqueda), center [lat,lng], fetch (para pruebas), geolocation, loadLeaflet().
   Evento: `gw:map-change` en el contenedor (burbujea) con detail {text, lat, lng}.
   Política de Nominatim (OpenStreetMap): sin autocompletar por tecla; solo al pulsar «Buscar» o Enter; mínimo 1 s entre peticiones; sin datos personales.
   Si el mapa o el buscador no cargan, el campo sigue siendo una dirección de texto (y las coordenadas se pueden escribir a mano). */
(function (root) {
  'use strict';

  var LEAFLET_VERSION = '1.9.4';
  // SRI de Leaflet 1.9.4 (sha384, calculado el 8-nov-2026 desde cdnjs). Si se cambia LEAFLET_VERSION hay que recalcularlos o el mapa no carga.
  var LEAFLET_SRI = { 'leaflet.js': 'sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH', 'leaflet.css': 'sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H' };
  var LEAFLET_BASE = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/' + LEAFLET_VERSION + '/';
  var TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  var NOMINATIM = 'https://nominatim.openstreetmap.org/search';
  var MIN_GAP_MS = 1100;           // Nominatim: máximo 1 petición por segundo
  var MAX_TEXT = 200;              // igual que el servidor
  var MAX_RESULTS = 6;
  var MIN_QUERY = 3;
  var DEFAULT_CENTER = [4.6097, -74.0817], DEFAULT_ZOOM = 5, POINT_ZOOM = 16;

  /* ------------------------------------------------------------------------------------------------ lógica pura */
  /* «4,6097» o «4.6097» -> número; vacío o inválido -> null. */
  function toNumber(s) {
    if (typeof s === 'number') return isFinite(s) ? s : null;
    var t = String(s == null ? '' : s).replace(/\s/g, '').replace(',', '.');
    if (!t || !/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
    var n = Number(t);
    return isFinite(n) ? n : null;
  }
  function round6(n) { return Math.round(n * 1e6) / 1e6; }
  function validLat(n) { return typeof n === 'number' && isFinite(n) && n >= -90 && n <= 90; }
  function validLng(n) { return typeof n === 'number' && isFinite(n) && n >= -180 && n <= 180; }
  function cleanText(s) { return String(s == null ? '' : s).replace(/[<>]/g, '').replace(/\s+/g, ' ').trim().slice(0, MAX_TEXT); }

  /* Valor guardado (objeto, JSON o texto suelto) -> {text, lat, lng}; lat/lng solo si ambos son válidos. */
  function parse(value) {
    var v = value;
    if (typeof v === 'string') {
      var s = v.trim();
      if (!s) return { text: '', lat: null, lng: null };
      if (s.charAt(0) === '{') { try { v = JSON.parse(s); } catch (e) { return { text: cleanText(s), lat: null, lng: null }; } }
      else return { text: cleanText(s), lat: null, lng: null };
    }
    if (!v || typeof v !== 'object') return { text: '', lat: null, lng: null };
    var lat = toNumber(v.lat), lng = toNumber(v.lng);
    var ok = validLat(lat) && validLng(lng);
    return { text: cleanText(v.text != null ? v.text : v.texto), lat: ok ? round6(lat) : null, lng: ok ? round6(lng) : null };
  }
  /* Estado -> lo que guarda el servidor, o null si está vacío. */
  function serialize(state) {
    var p = parse(state);
    if (!p.text && p.lat == null) return null;
    return { text: p.text, lat: p.lat, lng: p.lng };
  }
  function formatCoords(lat, lng) {
    if (!validLat(lat) || !validLng(lng)) return '';
    return lat.toFixed(5).replace('.', ',') + '; ' + lng.toFixed(5).replace('.', ',');
  }
  /* Texto para mostrar el valor en resúmenes: la dirección o, si no hay, las coordenadas. */
  function displayText(value) {
    var p = parse(value);
    return p.text || formatCoords(p.lat, p.lng);
  }
  /* Revisión de lo escrito a mano en los campos de coordenadas: {ok, lat, lng, error}. Ambos vacíos = sin ubicación (válido). */
  function checkCoords(latStr, lngStr) {
    var a = String(latStr == null ? '' : latStr).trim(), b = String(lngStr == null ? '' : lngStr).trim();
    if (!a && !b) return { ok: true, lat: null, lng: null, error: '' };
    if (!a || !b) return { ok: false, lat: null, lng: null, error: 'Escribe la latitud y la longitud, o deja ambas vacías.' };
    var lat = toNumber(a), lng = toNumber(b);
    if (lat == null || lng == null) return { ok: false, lat: null, lng: null, error: 'La latitud y la longitud deben ser números (ejemplo: 4,6097 y -74,0817).' };
    if (!validLat(lat)) return { ok: false, lat: null, lng: null, error: 'La latitud debe estar entre -90 y 90.' };
    if (!validLng(lng)) return { ok: false, lat: null, lng: null, error: 'La longitud debe estar entre -180 y 180.' };
    return { ok: true, lat: round6(lat), lng: round6(lng), error: '' };
  }
  /* Espera (ms) antes de poder pedir a Nominatim otra vez. */
  function waitMs(lastAt, now, gap) {
    var g = gap == null ? MIN_GAP_MS : gap;
    if (lastAt == null) return 0;
    return Math.max(0, g - (now - lastAt));
  }
  function searchUrl(query, countryCode) {
    var q = cleanText(query);
    var url = NOMINATIM + '?format=jsonv2&limit=' + MAX_RESULTS + '&addressdetails=0&accept-language=es&q=' + encodeURIComponent(q);
    var cc = String(countryCode || '').trim().toLowerCase();
    if (/^[a-z]{2}$/.test(cc)) url += '&countrycodes=' + cc;
    return url;
  }
  /* Respuesta de Nominatim -> [{label, lat, lng}] (descarta lo inválido y los repetidos). */
  function parseResults(json) {
    if (!Array.isArray(json)) return [];
    var seen = {}, out = [];
    json.forEach(function (r) {
      if (!r || out.length >= MAX_RESULTS) return;
      var lat = toNumber(r.lat), lng = toNumber(r.lon != null ? r.lon : r.lng);
      var label = cleanText(r.display_name || r.name);
      if (!label || !validLat(lat) || !validLng(lng)) return;
      var k = label + '|' + round6(lat) + '|' + round6(lng);
      if (seen[k]) return; seen[k] = 1;
      out.push({ label: label, lat: round6(lat), lng: round6(lng) });
    });
    return out;
  }
  /* País del contexto -> ISO-2 en minúsculas ('' si no se reconoce). Acepta código o nombre (usa GWGeo si está). */
  function countryToCode(value, geo) {
    var s = String(value == null ? '' : value).trim();
    if (!s) return '';
    if (/^[A-Za-z]{2}$/.test(s)) return s.toLowerCase();
    var g = geo || root.GWGeo;
    if (g && typeof g.searchCountries === 'function') {
      var hit = g.searchCountries(s, 1)[0];
      if (hit && /^[A-Za-z]{2}$/.test(hit.value || '') && g.normalize && g.normalize(hit.label) === g.normalize(s)) return hit.value.toLowerCase();
    }
    return '';
  }

  var pure = { toNumber: toNumber, validLat: validLat, validLng: validLng, parse: parse, serialize: serialize, displayText: displayText, formatCoords: formatCoords, checkCoords: checkCoords, waitMs: waitMs, searchUrl: searchUrl, parseResults: parseResults, countryToCode: countryToCode, cleanText: cleanText, MIN_GAP_MS: MIN_GAP_MS, LEAFLET_VERSION: LEAFLET_VERSION };
  if (typeof document === 'undefined') {            // node (pruebas): solo la lógica pura
    if (typeof module !== 'undefined' && module.exports) module.exports = pure;
    else root.GWMap = pure;
    return;
  }

  /* ------------------------------------------------------------------------------------------------ Leaflet perezoso */
  var leafletPromise = null;
  function loadLeaflet() {
    if (root.L && root.L.map) return Promise.resolve(root.L);
    if (leafletPromise) return leafletPromise;
    leafletPromise = new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { reject(new Error('timeout')); }, 15000);
      var css = document.createElement('link'); css.rel = 'stylesheet'; css.href = LEAFLET_BASE + 'leaflet.css'; css.integrity = LEAFLET_SRI['leaflet.css']; css.crossOrigin = '';
      document.head.appendChild(css);
      var js = document.createElement('script'); js.src = LEAFLET_BASE + 'leaflet.js'; js.integrity = LEAFLET_SRI['leaflet.js']; js.async = true; js.crossOrigin = '';
      js.onload = function () { clearTimeout(timer); if (root.L && root.L.map) { root.L.Icon.Default.imagePath = LEAFLET_BASE + 'images/'; resolve(root.L); } else reject(new Error('sin Leaflet')); };
      js.onerror = function () { clearTimeout(timer); reject(new Error('no cargó')); };
      document.head.appendChild(js);
    });
    leafletPromise.catch(function () { leafletPromise = null; });          // permite reintentar si la red vuelve
    return leafletPromise;
  }

  /* ------------------------------------------------------------------------------------------------ widget */
  var lastSearchAt = null, searchChain = Promise.resolve(), uid = 0;

  function mk(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function part(el, name) { return el.querySelector('[data-evf-part="' + name + '"]'); }

  function enhance(el, opts) {
    if (!el || el.dataset.gwMapReady) return null;
    opts = opts || {};
    var textIn = part(el, 'text'), latIn = part(el, 'lat'), lngIn = part(el, 'lng');
    if (!textIn || !latIn || !lngIn) return null;
    el.dataset.gwMapReady = '1';
    var n = ++uid, doFetch = opts.fetch || (root.fetch ? root.fetch.bind(root) : null);
    var map = null, marker = null, L = null, mapDead = false, lastResults = [], busy = false;

    el.classList.add('gw-map');
    var tools = mk('div', 'gw-map__tools');
    var btnSearch = mk('button', 'gw-btn gw-btn--secondary', 'Buscar'); btnSearch.type = 'button'; btnSearch.dataset.gwMapAct = 'search';
    var btnGeo = mk('button', 'gw-btn gw-btn--ghost', 'Usar mi ubicación'); btnGeo.type = 'button'; btnGeo.dataset.gwMapAct = 'geo';
    var btnClear = mk('button', 'gw-btn gw-btn--ghost', 'Quitar ubicación'); btnClear.type = 'button'; btnClear.dataset.gwMapAct = 'clear';
    tools.appendChild(btnSearch);
    if (opts.geolocation !== false && (opts.geolocation || navigator.geolocation)) tools.appendChild(btnGeo);
    tools.appendChild(btnClear);

    var status = mk('p', 'gw-map__status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    var list = mk('ul', 'gw-map__results gw-list--plain'); list.id = 'gwMapRes' + n; list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', 'Resultados de la búsqueda de direcciones'); list.hidden = true;
    var canvas = mk('div', 'gw-map__canvas'); canvas.id = 'gwMapCv' + n; canvas.setAttribute('role', 'application'); canvas.setAttribute('aria-label', 'Mapa. Toca o haz clic para marcar la ubicación; el marcador se puede arrastrar.'); canvas.hidden = true;
    var attr = mk('p', 'gw-map__attr'); attr.hidden = true;
    var a = mk('a', null, '© OpenStreetMap'); a.href = 'https://www.openstreetmap.org/copyright'; a.target = '_blank'; a.rel = 'noopener noreferrer';
    attr.appendChild(a); attr.appendChild(document.createTextNode(' · Búsqueda: Nominatim'));

    var det = mk('details', 'gw-map__coords');
    var sum = mk('summary', null, 'Coordenadas');
    var grid = mk('div', 'gw-map__coordgrid');
    var latBox = mk('div', 'gw-field'), lngBox = mk('div', 'gw-field');
    var latLbl = mk('label', 'gw-label', 'Latitud'); latLbl.htmlFor = 'gwMapLat' + n;
    var lngLbl = mk('label', 'gw-label', 'Longitud'); lngLbl.htmlFor = 'gwMapLng' + n;
    var latV = mk('input', 'gw-input'); latV.id = 'gwMapLat' + n; latV.type = 'text'; latV.inputMode = 'decimal'; latV.autocomplete = 'off'; latV.dataset.gwMapCoord = 'lat';
    var lngV = mk('input', 'gw-input'); lngV.id = 'gwMapLng' + n; lngV.type = 'text'; lngV.inputMode = 'decimal'; lngV.autocomplete = 'off'; lngV.dataset.gwMapCoord = 'lng';
    latBox.appendChild(latLbl); latBox.appendChild(latV); lngBox.appendChild(lngLbl); lngBox.appendChild(lngV);
    grid.appendChild(latBox); grid.appendChild(lngBox);
    var coordErr = mk('p', 'gw-map__coorderr'); coordErr.setAttribute('role', 'alert');
    det.appendChild(sum); det.appendChild(grid); det.appendChild(coordErr);

    [tools, status, list, canvas, attr, det].forEach(function (x) { el.appendChild(x); });
    textIn.setAttribute('aria-describedby', status.id = 'gwMapSt' + n);

    function say(msg, warn) { status.textContent = msg || ''; status.classList.toggle('gw-map__status--warn', !!warn); }
    function current() { return parse({ text: textIn.value, lat: latIn.value, lng: lngIn.value }); }
    function countryCode() {
      var v = typeof opts.getCountryCode === 'function' ? opts.getCountryCode() : opts.countryCode;
      if (!v) { var c = (el.closest('form, [data-evf-host], body') || document).querySelector('[data-evf-enhance="country"]'); v = c && c.value; }
      return countryToCode(v);
    }
    function emit() {
      var st = current();
      el.dispatchEvent(new CustomEvent('gw:map-change', { bubbles: true, detail: { text: st.text, lat: st.lat, lng: st.lng } }));
      latIn.dispatchEvent(new Event('input', { bubbles: true }));
    }
    function setPoint(lat, lng, fromMap) {
      if (lat == null) { latIn.value = ''; lngIn.value = ''; latV.value = ''; lngV.value = ''; }
      else { latIn.value = String(round6(lat)); lngIn.value = String(round6(lng)); latV.value = String(round6(lat)).replace('.', ','); lngV.value = String(round6(lng)).replace('.', ','); }
      coordErr.textContent = '';
      syncMarker(!fromMap);
    }
    function syncMarker(move) {
      if (!map) return;
      var st = current();
      if (st.lat == null) { if (marker) { map.removeLayer(marker); marker = null; } return; }
      if (!marker) {
        marker = L.marker([st.lat, st.lng], { draggable: true, keyboard: false, title: 'Ubicación del evento (arrástrala para ajustar)' }).addTo(map);
        marker.on('dragend', function () { var p = marker.getLatLng(); setPoint(p.lat, p.lng, true); say('Ubicación ajustada en el mapa.'); emit(); });
      } else marker.setLatLng([st.lat, st.lng]);
      if (move) map.setView([st.lat, st.lng], Math.max(map.getZoom(), POINT_ZOOM));
    }

    /* mapa (perezoso: solo al montar el campo) */
    function startMap() {
      var load = typeof opts.loadLeaflet === 'function' ? opts.loadLeaflet() : loadLeaflet();
      Promise.resolve(load).then(function (lib) {
        L = lib; canvas.hidden = false; attr.hidden = false;
        var st = current(), c = opts.center || DEFAULT_CENTER;
        map = L.map(canvas, { center: st.lat != null ? [st.lat, st.lng] : c, zoom: st.lat != null ? POINT_ZOOM : DEFAULT_ZOOM, keyboard: true });
        L.tileLayer(TILE_URL, { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>' }).addTo(map);
        map.on('click', function (ev) { setPoint(ev.latlng.lat, ev.latlng.lng, true); say('Ubicación marcada en el mapa.'); emit(); });
        syncMarker(false);
        setTimeout(function () { if (map) map.invalidateSize(); }, 200);          // por si el campo estaba en una pestaña o ventana que recién se abre
      }).catch(function () {
        mapDead = true; canvas.hidden = true; attr.hidden = true;
        say('No se pudo cargar el mapa (revisa tu conexión). Puedes escribir la dirección y guardar igual, o escribir las coordenadas.', true);
      });
    }

    /* búsqueda */
    function hideResults() { list.hidden = true; list.textContent = ''; lastResults = []; textIn.removeAttribute('aria-activedescendant'); }
    function showResults(items) {
      list.textContent = ''; lastResults = items;
      items.forEach(function (r, i) {
        var li = mk('li', 'gw-map__item'); li.setAttribute('role', 'presentation');
        var b = mk('button', 'gw-map__opt', r.label); b.type = 'button'; b.setAttribute('role', 'option'); b.dataset.gwMapIdx = String(i); b.id = 'gwMapOpt' + n + '_' + i;
        li.appendChild(b); list.appendChild(li);
      });
      list.hidden = !items.length;
      if (items.length) { var f = list.querySelector('button'); if (f) f.focus(); }
    }
    function choose(i) {
      var r = lastResults[i]; if (!r) return;
      textIn.value = r.label; setPoint(r.lat, r.lng, false); hideResults();
      say('Ubicación elegida: ' + r.label);
      emit(); textIn.focus();
    }
    function search() {
      if (busy) return;
      var q = cleanText(textIn.value);
      if (q.length < MIN_QUERY) { hideResults(); say('Escribe al menos ' + MIN_QUERY + ' letras de la dirección y pulsa «Buscar».', true); textIn.focus(); return; }
      if (!doFetch || (navigator.onLine === false)) { say('No hay conexión para buscar la dirección. Se guardará como texto; también puedes escribir las coordenadas.', true); return; }
      busy = true; btnSearch.disabled = true; hideResults(); say('Buscando…');
      var url = searchUrl(q, countryCode());
      searchChain = searchChain.then(function () {
        var wait = waitMs(lastSearchAt, Date.now());
        return new Promise(function (ok) { setTimeout(ok, wait); });
      }).then(function () {
        lastSearchAt = Date.now();
        return doFetch(url, { headers: { 'Accept-Language': 'es', 'Accept': 'application/json' }, credentials: 'omit', referrerPolicy: 'strict-origin-when-cross-origin' });
      }).then(function (res) {
        if (!res || !res.ok) throw new Error('http');
        return res.json();
      }).then(function (json) {
        var items = parseResults(json);
        if (!items.length) { say('No encontramos esa dirección. Prueba con otra forma de escribirla, marca el punto en el mapa o escribe las coordenadas.', true); return; }
        say(items.length === 1 ? 'Hay 1 resultado. Elígelo para usarlo.' : 'Hay ' + items.length + ' resultados. Elige uno con el ratón, el dedo o las flechas y Enter.');
        showResults(items);
      }).catch(function () {
        say('El buscador no responde. La dirección se guardará como texto; puedes marcarla en el mapa o escribir las coordenadas.', true);
      }).then(function () { busy = false; btnSearch.disabled = false; });
    }

    /* eventos (delegados en el contenedor) */
    el.addEventListener('click', function (e) {
      var t = e.target.closest && e.target.closest('[data-gw-map-act],[data-gw-map-idx]');
      if (!t || !el.contains(t)) return;
      if (t.dataset.gwMapIdx != null) { choose(Number(t.dataset.gwMapIdx)); return; }
      var act = t.dataset.gwMapAct;
      if (act === 'search') search();
      else if (act === 'clear') { setPoint(null); hideResults(); say('Ubicación del mapa quitada.'); emit(); }
      else if (act === 'geo') {
        var geo = opts.geolocation && opts.geolocation.getCurrentPosition ? opts.geolocation : navigator.geolocation;
        if (!geo) { say('Tu navegador no permite usar la ubicación.', true); return; }
        say('Pidiendo tu ubicación…'); t.disabled = true;
        geo.getCurrentPosition(function (pos) {
          t.disabled = false; setPoint(pos.coords.latitude, pos.coords.longitude, false); say('Se usó tu ubicación actual. Ajusta el marcador si hace falta.'); emit();
        }, function (err) {
          t.disabled = false;
          say(err && err.code === 1 ? 'No diste permiso para usar tu ubicación. Puedes buscar la dirección o marcarla en el mapa.' : 'No se pudo obtener tu ubicación. Puedes buscar la dirección o marcarla en el mapa.', true);
        }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 });
      }
    });
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target.dataset && e.target.dataset.gwMapCoord) { e.preventDefault(); return; }
      if (e.target === textIn && e.key === 'Enter') { e.preventDefault(); search(); return; }       // Enter busca; no envía el formulario
      if (e.target === textIn && e.key === 'ArrowDown' && lastResults.length) { e.preventDefault(); var f = list.querySelector('button'); if (f) f.focus(); return; }
      var opt = e.target.closest && e.target.closest('.gw-map__opt');
      if (opt) {
        var all = Array.prototype.slice.call(list.querySelectorAll('button')), i = all.indexOf(opt);
        if (e.key === 'ArrowDown') { e.preventDefault(); (all[i + 1] || all[0]).focus(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); if (i > 0) all[i - 1].focus(); else textIn.focus(); }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); hideResults(); textIn.focus(); }
      }
    });
    el.addEventListener('input', function (e) {
      if (e.target === textIn) { if (list.hidden === false) hideResults(); emit(); return; }
      var cv = e.target.dataset && e.target.dataset.gwMapCoord;
      if (!cv) return;
      e.stopPropagation();
      var r = checkCoords(latV.value, lngV.value);
      coordErr.textContent = r.error;
      if (!r.ok) return;
      if (r.lat == null) { latIn.value = ''; lngIn.value = ''; } else { latIn.value = String(r.lat); lngIn.value = String(r.lng); }
      syncMarker(true); emit();
    });

    /* valor inicial */
    var ini = current();
    if (ini.lat != null) { latV.value = String(ini.lat).replace('.', ','); lngV.value = String(ini.lng).replace('.', ','); det.open = false; }
    say(ini.lat != null ? 'Ubicación marcada en el mapa.' : 'Escribe la dirección y pulsa «Buscar», o marca el punto en el mapa.');
    startMap();
    return { search: search, getValue: function () { return serialize(current()); }, destroy: function () { if (map) map.remove(); } };
  }

  /* Monta todos los campos de mapa de un contenedor (lo llama event-field-render.js o la pantalla). */
  function enhanceAll(host, opts) {
    Array.prototype.forEach.call((host || document).querySelectorAll('[data-evf-enhance="map"]'), function (el) { enhance(el, opts); });
  }

  root.GWMap = { enhance: enhance, enhanceAll: enhanceAll, parse: parse, serialize: serialize, displayText: displayText, checkCoords: checkCoords, searchUrl: searchUrl, parseResults: parseResults, waitMs: waitMs, toNumber: toNumber, countryToCode: countryToCode };
})(typeof window !== 'undefined' ? window : globalThis);
