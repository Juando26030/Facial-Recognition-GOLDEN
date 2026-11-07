/* Diseñador de la plantilla de evento (Configuración › Diseñar plantilla para eventos, solo admin y super_admin). Mismo estilo que el diseñador del formulario de persona y el editor de formularios web:
   tarjetas que se ARRASTRAN, panel de propiedades a la derecha y vista previa. Sin tipografías. Cada arrastre tiene su alternativa con teclado (botones «Subir»/«Bajar» y listas «Paso»/«Zona»).
   Dos vistas sobre UNA plantilla: (A) «Vista de creación de evento» (pasos y campos de Nuevo evento, obligatorios) y (B) «Vista calendario» (qué campos salen en la tarjeta del calendario y dónde; solo visual).
   Las funciones del MODELO son puras y se prueban en Node (tests/js/event_template_designer_check.js); mount() solo pinta con clases .gw-* y usa toast.js. Todo texto del administrador va ESCAPADO. El servidor valida de nuevo. */
(function (root) {
  'use strict';
  var ZONES = ['top', 'left', 'right', 'bottom'];
  var LIMITS = { active: 80, sections: 6, zoneItems: 12, options: 50, invTypes: 20, title: 60, sectionTitle: 40 };
  var clone = function (o) { return JSON.parse(JSON.stringify(o)); };
  var esc = function (t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };

  /* ------------------------------------------------------------------------------------------------ modelo (puro) */
  function fromServer(resp) {
    return { version: resp.version || 0, fields: clone(resp.fields), sections: clone(resp.creation_layout.sections), zones: clone(resp.calendar_layout.zones), catalog: resp.catalog || {}, people: resp.people || {}, updated_by: resp.updated_by || null, updated_at: resp.updated_at || null };
  }
  function toPayload(m) {
    return { version: m.version, fields: clone(m.fields), creation_layout: { sections: clone(m.sections) }, calendar_layout: { zones: clone(m.zones) } };
  }
  var field = function (m, key) { for (var i = 0; i < m.fields.length; i++) if (m.fields[i].key === key) return m.fields[i]; return null; };
  var isLocked = function (m, key) { return ((m.catalog.locked) || ['client', 'event_code', 'name']).indexOf(key) >= 0; };
  var isCustom = function (key) { return /^c_/.test(key); };
  var active = function (m) { return m.fields.filter(function (f) { return !f.retired; }); };
  var retired = function (m) { return m.fields.filter(function (f) { return f.retired; }); };
  function sectionIndexOf(m, key) { for (var i = 0; i < m.sections.length; i++) if (m.sections[i].keys.indexOf(key) >= 0) return i; return -1; }
  function unplaced(m) { return active(m).filter(function (f) { return sectionIndexOf(m, f.key) < 0; }); }
  function zoneOf(m, key) { for (var i = 0; i < ZONES.length; i++) { var z = m.zones[ZONES[i]] || []; for (var j = 0; j < z.length; j++) if (z[j].key === key) return ZONES[i]; } return null; }
  function calUnplaced(m) { return active(m).filter(function (f) { return !zoneOf(m, f.key); }); }

  function newKey(m, rng) {
    var r = rng || Math.random, k;
    do { k = 'c_'; for (var i = 0; i < 8; i++) k += 'abcdefghijklmnopqrstuvwxyz0123456789'.charAt(Math.floor(r() * 36)); } while (field(m, k));
    return k;
  }
  function typeLabel(m, type) {
    var t = ((m.catalog && m.catalog.types) || []).filter(function (x) { return x.type === type; })[0];
    return t ? t.label : type;
  }
  function defaultsFor(m, type) {
    var d = { title: typeLabel(m, type), options: [], config: {} };
    if (type === 'select') d.options = ['Opción 1', 'Opción 2'];
    if (type === 'money') d.config = { currency: 'COP' };
    if (type === 'number') d.config = { min: null, max: null, decimals: 0 };
    if (type === 'text_short') d.config = { max_len: 200 };
    if (type === 'text_long') d.config = { max_len: 2000 };
    if (type === 'city') { var c = active(m).filter(function (f) { return f.type === 'country'; })[0]; d.config = { country_key: c ? c.key : null }; }
    if (type === 'bandana_colors') d.config = { max: 3 };
    if (type === 'inventory') d.config = { inventory_types: [{ key: 'tipo1', label: 'Tipo 1', refs: [] }] };
    return d;
  }
  /* Campo nuevo (personalizado) de un tipo; queda al final del paso `sectionId` (o del último). Devuelve la clave, o null si ya no caben más. */
  function addField(m, type, sectionId, rng) {
    if (active(m).length >= LIMITS.active) return null;
    var d = defaultsFor(m, type), key = newKey(m, rng);
    m.fields.push({ key: key, type: type, title: d.title, required: false, options: d.options, config: d.config, help: '', retired: false });
    var sec = m.sections.filter(function (s) { return s.id === sectionId; })[0] || m.sections[m.sections.length - 1];
    sec.keys.push(key);
    return key;
  }
  function removeFromAll(m, key) { m.sections.forEach(function (s) { s.keys = s.keys.filter(function (k) { return k !== key; }); }); }
  /* Pone `key` en el paso `sectionId` en la posición `index` (la saca de donde estuviera). */
  function place(m, key, sectionId, index) {
    var f = field(m, key), sec = m.sections.filter(function (s) { return s.id === sectionId; })[0];
    if (!f || f.retired || !sec) return false;
    removeFromAll(m, key);
    var i = index == null || index > sec.keys.length ? sec.keys.length : Math.max(0, index);
    sec.keys.splice(i, 0, key);
    return true;
  }
  /* Quita el campo de la vista de creación (sigue existiendo en el catálogo). Un obligatorio pasa a opcional. */
  function unplace(m, key) {
    var f = field(m, key);
    if (!f) return { ok: false, reason: 'No existe ese campo' };
    if (isLocked(m, key)) return { ok: false, reason: '«' + f.title + '» es obligatorio siempre y no se puede quitar' };
    var note = '';
    if (f.required) { f.required = false; note = '«' + f.title + '» pasó a opcional porque ya no se pide al crear el evento'; }
    removeFromAll(m, key);
    return { ok: true, note: note };
  }
  /* Sube (-1) o baja (+1) dentro del paso; en el borde pasa al paso vecino. */
  function moveBy(m, key, delta) {
    var si = sectionIndexOf(m, key);
    if (si < 0) return false;
    var keys = m.sections[si].keys, i = keys.indexOf(key), j = i + delta;
    if (j >= 0 && j < keys.length) { keys.splice(i, 1); keys.splice(j, 0, key); return true; }
    var to = si + (delta < 0 ? -1 : 1);
    if (to < 0 || to >= m.sections.length) return false;
    keys.splice(i, 1);
    if (delta < 0) m.sections[to].keys.push(key); else m.sections[to].keys.unshift(key);
    return true;
  }
  function addSection(m, title, rng) {
    if (m.sections.length >= LIMITS.sections) return null;
    var r = rng || Math.random, id;
    do { id = 'p' + Math.floor(r() * 1e6); } while (m.sections.some(function (s) { return s.id === id; }));
    m.sections.push({ id: id, title: String(title || 'Nuevo paso').slice(0, LIMITS.sectionTitle), keys: [] });
    return id;
  }
  /* Un paso solo puede quedar vacío mientras se arma (no se guarda vacío); validate() lo avisa. */
  function removeSection(m, id) {
    if (m.sections.length <= 1) return { ok: false, reason: 'Tiene que quedar al menos un paso' };
    var i = m.sections.findIndex(function (s) { return s.id === id; });
    if (i < 0) return { ok: false, reason: 'No existe ese paso' };
    var target = m.sections[i > 0 ? i - 1 : 1];
    target.keys = target.keys.concat(m.sections[i].keys);          // sus campos pasan al paso vecino: nada se pierde ni queda sin lugar
    var moved = m.sections[i].keys.length;
    m.sections.splice(i, 1);
    return { ok: true, note: moved ? 'Los campos del paso pasaron al paso «' + target.title + '»' : '' };
  }
  function moveSection(m, id, delta) {
    var i = m.sections.findIndex(function (s) { return s.id === id; }), j = i + delta;
    if (i < 0 || j < 0 || j >= m.sections.length) return false;
    var s = m.sections.splice(i, 1)[0]; m.sections.splice(j, 0, s);
    return true;
  }
  function setRequired(m, key, on) {
    var f = field(m, key);
    if (!f || f.type === 'switch' || isLocked(m, key)) return false;
    f.required = !!on;
    if (on && sectionIndexOf(m, key) < 0) m.sections[m.sections.length - 1].keys.push(key);          // un obligatorio tiene que estar en la vista de creación
    return true;
  }
  /* Retirar un campo personalizado: sale de las dos vistas; su definición y los valores ya guardados en eventos se conservan («campo retirado»). */
  function retire(m, key) {
    var f = field(m, key);
    if (!f || !isCustom(key)) return false;
    f.retired = true; f.required = false;
    removeFromAll(m, key); calUnplace(m, key);
    return true;
  }
  function restore(m, key) {
    var f = field(m, key);
    if (!f || !f.retired) return false;
    f.retired = false;
    return true;
  }
  /* ---- calendario */
  function calUnplace(m, key) { ZONES.forEach(function (z) { m.zones[z] = (m.zones[z] || []).filter(function (it) { return it.key !== key; }); }); }
  function calPlace(m, key, zone, index, label) {
    var f = field(m, key);
    if (!f || f.retired || ZONES.indexOf(zone) < 0) return false;
    var prev = null, from = null;
    ZONES.forEach(function (z) { (m.zones[z] || []).forEach(function (it) { if (it.key === key) { prev = it; from = z; } }); });
    if (from !== zone && (m.zones[zone] || []).length >= LIMITS.zoneItems) return false;          // zona llena: no se toca nada
    var keepLabel = label != null ? !!label : (prev ? prev.label : true);
    calUnplace(m, key);
    var list = m.zones[zone] = m.zones[zone] || [];
    var i = index == null || index > list.length ? list.length : Math.max(0, index);
    list.splice(i, 0, { key: key, label: keepLabel });
    return true;
  }
  function calMoveBy(m, key, delta) {
    var z = zoneOf(m, key);
    if (!z) return false;
    var list = m.zones[z], i = list.findIndex(function (it) { return it.key === key; }), j = i + delta;
    if (j < 0 || j >= list.length) return false;
    var it = list.splice(i, 1)[0]; list.splice(j, 0, it);
    return true;
  }
  function calSetLabel(m, key, on) {
    var z = zoneOf(m, key);
    if (!z) return false;
    m.zones[z].forEach(function (it) { if (it.key === key) it.label = !!on; });
    return true;
  }
  /* ---- propiedades */
  function parseLines(text) {
    var seen = {}, out = [];
    String(text || '').split(/\r?\n/).forEach(function (l) { var v = l.trim(); if (v && !seen[v.toLowerCase()]) { seen[v.toLowerCase()] = 1; out.push(v); } });
    return out;
  }
  function addInventoryType(m, key) {
    var f = field(m, key); if (!f || f.type !== 'inventory') return false;
    var list = f.config.inventory_types = f.config.inventory_types || [];
    if (list.length >= LIMITS.invTypes) return false;
    var n = list.length + 1, k;
    do { k = 'tipo' + n++; } while (list.some(function (t) { return t.key === k; }));
    list.push({ key: k, label: 'Tipo ' + (list.length + 1), refs: [] });
    return true;
  }
  function removeInventoryType(m, key, typeKey) {
    var f = field(m, key); if (!f || f.type !== 'inventory') return false;
    if (f.config.inventory_types.length <= 1) return false;
    f.config.inventory_types = f.config.inventory_types.filter(function (t) { return t.key !== typeKey; });
    return true;
  }

  /* Mismas reglas que el servidor (app/event_template.py), para avisar ANTES de guardar. Devuelve una lista de mensajes (vacía = bien). */
  function validate(m) {
    var out = [], placed = {};
    m.sections.forEach(function (s) {
      if (!String(s.title || '').trim()) out.push('Hay un paso sin título');
      if (!s.keys.length) out.push('El paso «' + (s.title || 'sin título') + '» está vacío: pon al menos un campo o quítalo');
      s.keys.forEach(function (k) { placed[k] = 1; });
    });
    if (active(m).length > LIMITS.active) out.push('Hay demasiados campos activos (máximo ' + LIMITS.active + ')');
    active(m).forEach(function (f) {
      var w = '«' + (f.title || 'sin título') + '»';
      if (!String(f.title || '').trim()) out.push('Hay un campo sin título');
      if (/[<>]/.test(f.title || '') || /[<>]/.test(f.help || '')) out.push(w + ' no puede incluir «<» ni «>»');
      if (f.required && f.type !== 'switch' && !placed[f.key]) out.push(w + ' es obligatorio: tiene que estar en la vista de creación');
      if (f.type === 'select') {
        if (!f.options.length) out.push(w + ': agrega al menos una opción');
        if (f.options.some(function (o) { return /[<>]/.test(o); })) out.push(w + ': las opciones no pueden incluir «<» ni «>»');
      }
      if (f.type === 'inventory') {
        var ts = (f.config && f.config.inventory_types) || [];
        if (!ts.length) out.push(w + ': agrega al menos un tipo de inventario');
        ts.forEach(function (t) { if (!String(t.label || '').trim()) out.push(w + ': hay un tipo de inventario sin nombre'); });
      }
      if (f.type === 'number' && f.config.min != null && f.config.max != null && Number(f.config.min) > Number(f.config.max)) out.push(w + ': el mínimo no puede ser mayor que el máximo');
    });
    ((m.catalog && m.catalog.locked) || []).forEach(function (k) { if (!placed[k]) out.push('«' + ((field(m, k) || {}).title || k) + '» no se puede quitar de la vista de creación'); });
    return out;
  }

  /* Valores de ejemplo para la vista previa de la tarjeta del calendario. */
  function sampleEvent(m) {
    var ev = { id: 0, tenant_name: 'Cliente S.A.S.', event_code: 'CONG-2026', name: 'Congreso Anual', country: 'Colombia', city: 'Bogotá', location: 'Corferias', address: 'Av. 24 # 38-47', start_date: '2026-11-12', end_date: '2026-11-14', setup_date: '2026-11-10',
      event_time_start: '08:00', event_time_end: '18:00', setup_time_start: '06:00', setup_time_end: '07:00', coordinator_name: 'Ana Torres', commercial_name: 'Luis Rojas', super_event_name: 'Congresos 2026',
      bandana_colors: [{ name: 'Rojo Golden', hex: '#c0392b' }], notes: 'Entrada por la puerta 3', switches: {}, extra: {} };
    (m.catalog.switches || []).forEach(function (s) { ev.switches[s.key] = true; });
    m.fields.forEach(function (f) {
      if (!isCustom(f.key)) return;
      var c = f.config || {};
      ev.extra[f.key] = { text_short: 'Texto de ejemplo', text_long: 'Texto largo de ejemplo', select: (f.options || [])[0], money: 2500000, number: 120, date: '2026-11-12', time: '08:00', datetime: '2026-11-12T08:00',
        country: 'Colombia', city: 'Bogotá', address_map: { text: 'Cra 7 # 71-21', lat: null, lng: null }, contact: { name: 'María Pérez', phone: '3001234567' },
        bandana_colors: [{ name: 'Rojo Golden', hex: '#c0392b' }], commercial: 1, coordinator: 1,
        inventory: (c.inventory_types || []).slice(0, 1).map(function (t) { return { type: t.key, qty: 100, ref: (t.refs || [])[0] || null }; }) }[f.type];
    });
    return ev;
  }

  var model = { fromServer: fromServer, toPayload: toPayload, field: field, active: active, retired: retired, unplaced: unplaced, calUnplaced: calUnplaced, sectionIndexOf: sectionIndexOf, zoneOf: zoneOf, isLocked: isLocked, isCustom: isCustom,
    newKey: newKey, typeLabel: typeLabel, defaultsFor: defaultsFor, addField: addField, place: place, unplace: unplace, moveBy: moveBy, addSection: addSection, removeSection: removeSection, moveSection: moveSection,
    setRequired: setRequired, retire: retire, restore: restore, calPlace: calPlace, calUnplace: calUnplace, calMoveBy: calMoveBy, calSetLabel: calSetLabel, parseLines: parseLines,
    addInventoryType: addInventoryType, removeInventoryType: removeInventoryType, validate: validate, sampleEvent: sampleEvent, ZONES: ZONES, LIMITS: LIMITS };

  /* ------------------------------------------------------------------------------------------------ pantalla */
  function mount(host, opts) {
    var m = null, sel = null, selSection = null, selZone = 'left', calSel = null, EF = root.EventFields;
    var icons = host.getAttribute('data-icons') || '';
    var ic = function (name, cls) { return '<svg class="gw-icon ' + (cls || '') + '" aria-hidden="true"><use href="' + esc(icons) + '#i-' + name + '"/></svg>'; };
    var q = function (id) { return host.querySelector('#' + id); };
    var dirty = function () { if (opts && opts.onChange) opts.onChange(); };
    var toast = function (msg, kind) { if (root.showToast) root.showToast(msg, kind || 'info'); };
    var typeTag = function (f) { return f.type === 'switch' ? 'Interruptor' : model.typeLabel(m, f.type); };

    function load(resp) { m = fromServer(resp); if (!sel || !model.field(m, sel)) sel = null; renderAll(); }

    /* ---- vista A: creación */
    function cardHtml(f) {
      var locked = model.isLocked(m, f.key), idx = model.sectionIndexOf(m, f.key);
      return '<li class="gw-tpl-card' + (sel === f.key ? ' gw-tpl-card--sel' : '') + (locked ? ' gw-tpl-card--locked' : '') + '" draggable="true" tabindex="0" role="button" aria-pressed="' + (sel === f.key ? 'true' : 'false') + '" data-key="' + esc(f.key) + '" data-tpl-act="select">' +
        '<span class="gw-tpl-card__grip" aria-hidden="true">' + ic('grip', 'gw-icon--sm') + '</span>' +
        '<span class="gw-tpl-card__body"><span class="gw-tpl-card__label">' + esc(f.title) + '</span><span class="gw-tpl-card__type">' + esc(typeTag(f)) + '</span>' +
        '<span class="gw-tpl-card__tags">' + (locked ? '<span class="gw-badge gw-badge--info">Siempre</span>' : '') + (f.required && f.type !== 'switch' ? '<span class="gw-badge gw-badge--warn">Obligatorio</span>' : '') + (f.type === 'switch' ? '<span class="gw-badge gw-badge--info">Como en Parámetros</span>' : '') + '</span></span>' +
        '<span class="gw-tpl-card__tools"><button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="up" data-key="' + esc(f.key) + '" aria-label="Subir «' + esc(f.title) + '»"' + (idx === 0 && m.sections[0].keys[0] === f.key ? ' disabled' : '') + '>' + ic('chevron', 'gw-icon--sm gw-tpl-up') + '</button>' +
        '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="down" data-key="' + esc(f.key) + '" aria-label="Bajar «' + esc(f.title) + '»">' + ic('chevron', 'gw-icon--sm gw-tpl-down') + '</button></span></li>';
    }
    function sectionHtml(s, i) {
      var last = i === m.sections.length - 1;
      return '<section class="gw-tpl-sec' + (selSection === s.id ? ' gw-tpl-sec--sel' : '') + '" data-sec="' + esc(s.id) + '" aria-label="Paso ' + (i + 1) + '">' +
        '<div class="gw-tpl-sec__head"><span class="gw-tpl-sec__n" aria-hidden="true">' + (i + 1) + '</span>' +
        '<input class="gw-input gw-tpl-sec__title" type="text" maxlength="' + LIMITS.sectionTitle + '" value="' + esc(s.title) + '" data-tpl-sec-title="' + esc(s.id) + '" aria-label="Título del paso ' + (i + 1) + '">' +
        '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="sec-up" data-sec="' + esc(s.id) + '" aria-label="Subir el paso ' + (i + 1) + '"' + (i === 0 ? ' disabled' : '') + '>' + ic('chevron', 'gw-icon--sm gw-tpl-up') + '</button>' +
        '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="sec-down" data-sec="' + esc(s.id) + '" aria-label="Bajar el paso ' + (i + 1) + '"' + (last ? ' disabled' : '') + '>' + ic('chevron', 'gw-icon--sm gw-tpl-down') + '</button>' +
        '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="sec-del" data-sec="' + esc(s.id) + '" aria-label="Quitar el paso ' + (i + 1) + '"' + (m.sections.length <= 1 ? ' disabled' : '') + '>' + ic('trash', 'gw-icon--sm') + '</button></div>' +
        '<ol class="gw-tpl-list" data-drop-sec="' + esc(s.id) + '">' + s.keys.map(function (k) { return model.field(m, k) ? cardHtml(model.field(m, k)) : ''; }).join('') + '</ol>' +
        '<div class="gw-tpl-drop" data-drop-sec="' + esc(s.id) + '" data-drop-end="1">' + (s.keys.length ? 'Suelta aquí para dejarlo al final' : 'Paso vacío: arrastra campos aquí o elígelos a la izquierda') + '</div></section>';
    }
    function paletteHtml() {
      var types = ((m.catalog.types) || []).filter(function (t) { return t.creatable; });
      var free = model.unplaced(m), ret = model.retired(m);
      return '<section class="gw-card gw-tpl-side"><h2 class="gw-tpl-h">Crear un campo nuevo</h2><p class="gw-hint">Elige el tipo (clic) o arrástralo al paso.</p><div class="gw-tpl-pal">' +
        types.map(function (t) { return '<button type="button" class="gw-tpl-pal__btn" draggable="true" data-tpl-act="add-type" data-type="' + esc(t.type) + '">' + ic('plus', 'gw-icon--sm') + esc(t.label) + '</button>'; }).join('') + '</div></section>' +
        '<section class="gw-card gw-tpl-side"><h2 class="gw-tpl-h">Campos disponibles</h2><p class="gw-hint">Ya existen pero no se piden al crear. Clic o arrastra para pedirlos.</p>' +
        (free.length ? '<div class="gw-tpl-pal">' + free.map(function (f) { return '<button type="button" class="gw-tpl-pal__btn" draggable="true" data-tpl-act="add-field" data-key="' + esc(f.key) + '">' + ic('plus', 'gw-icon--sm') + '<span>' + esc(f.title) + '<small class="gw-tpl-pal__sub">' + esc(typeTag(f)) + '</small></span></button>'; }).join('') + '</div>' : '<p class="gw-hint">Todos los campos ya están en la vista.</p>') + '</section>' +
        (ret.length ? '<section class="gw-card gw-tpl-side"><details><summary class="gw-tpl-sum">Campos retirados (' + ret.length + ')</summary><p class="gw-hint">Sus valores en los eventos ya creados se conservan. Puedes volver a usarlos.</p>' +
          ret.map(function (f) { return '<div class="gw-tpl-ret"><span>' + esc(f.title) + ' <small class="gw-hint">' + esc(typeTag(f)) + '</small></span><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-tpl-act="restore" data-key="' + esc(f.key) + '">Volver a usar</button></div>'; }).join('') + '</details></section>' : '');
    }
    function lab(id, text, inner, hint) { return '<div class="gw-field"><label class="gw-label" for="' + id + '">' + text + '</label>' + inner + (hint ? '<small class="gw-hint">' + hint + '</small>' : '') + '</div>'; }
    function propsHtml() {
      var f = sel && model.field(m, sel);
      if (!f) return '<p class="gw-hint">Elige un campo para ver y cambiar sus parámetros.</p>';
      var locked = model.isLocked(m, f.key), c = f.config || {}, custom = model.isCustom(f.key), sw = f.type === 'switch', si = model.sectionIndexOf(m, f.key);
      var html = '<h2 class="gw-tpl-h">' + esc(f.title) + '</h2><p class="gw-hint">' + esc(typeTag(f)) + (custom ? '' : ' · campo del sistema') + '</p>';
      html += lab('tp_title', 'Título', '<input class="gw-input" id="tp_title" type="text" maxlength="' + LIMITS.title + '" value="' + esc(f.title) + '" data-tpl-prop="title">');
      html += lab('tp_help', 'Ayuda (opcional)', '<input class="gw-input" id="tp_help" type="text" maxlength="200" value="' + esc(f.help || '') + '" data-tpl-prop="help">', 'Se muestra debajo del campo.');
      if (sw) {
        var s = ((m.catalog.switches) || []).filter(function (x) { return x.field_key === f.key; })[0];
        html += '<div class="gw-alert">' + ic('info') + '<div class="gw-alert__body">Es la misma opción de «Parámetros del evento»' + (s && s.requires ? ' (necesita «' + esc(((m.catalog.switches.filter(function (x) { return x.key === s.requires; })[0]) || {}).title || '') + '» activo)' : '') + '. Si no la defines al crear el evento, la defines después en Parámetros.</div></div>';
      } else {
        html += '<label class="gw-check"><input type="checkbox" data-tpl-prop="required"' + (f.required ? ' checked' : '') + (locked ? ' disabled' : '') + '> <span class="gw-choice__text">Obligatorio' + (locked ? ' (siempre)' : '') + '</span></label>';
      }
      if (f.type === 'select') html += lab('tp_opts', 'Opciones (una por línea)', '<textarea class="gw-textarea" id="tp_opts" rows="6" data-tpl-prop="options">' + esc((f.options || []).join('\n')) + '</textarea>', 'Puedes agregar o quitar opciones cuando quieras: los eventos que ya tienen una opción la conservan.');
      if (f.type === 'money') html += lab('tp_cur', 'Moneda', '<select class="gw-select" id="tp_cur" data-tpl-prop="currency">' + (m.catalog.currencies || ['COP']).map(function (cu) { return '<option value="' + esc(cu) + '"' + (c.currency === cu ? ' selected' : '') + '>' + esc(cu) + '</option>'; }).join('') + '</select>');
      if (f.type === 'number') html += '<div class="gw-fields-row gw-fields-row--3">' + lab('tp_min', 'Mínimo', '<input class="gw-input" id="tp_min" type="number" value="' + esc(c.min == null ? '' : c.min) + '" data-tpl-prop="min">') + lab('tp_max', 'Máximo', '<input class="gw-input" id="tp_max" type="number" value="' + esc(c.max == null ? '' : c.max) + '" data-tpl-prop="max">') + lab('tp_dec', 'Decimales', '<input class="gw-input" id="tp_dec" type="number" min="0" max="4" value="' + esc(c.decimals || 0) + '" data-tpl-prop="decimals">') + '</div>';
      if ((f.type === 'text_short' || f.type === 'text_long') && custom) html += lab('tp_len', 'Largo máximo', '<input class="gw-input" id="tp_len" type="number" min="1" max="' + (f.type === 'text_short' ? 200 : 2000) + '" value="' + esc(c.max_len || (f.type === 'text_short' ? 200 : 2000)) + '" data-tpl-prop="max_len">');
      if (f.type === 'bandana_colors' && custom) html += lab('tp_cmax', 'Cantidad máxima de colores', '<input class="gw-input" id="tp_cmax" type="number" min="1" max="8" value="' + esc(c.max || 1) + '" data-tpl-prop="cmax">', 'Los colores se eligen de la librería de colores guardados, igual que al crear el evento.');
      if (f.type === 'city' && custom) html += lab('tp_ck', 'Depende del país', '<select class="gw-select" id="tp_ck" data-tpl-prop="country_key"><option value="">— Ninguno (texto libre) —</option>' + model.active(m).filter(function (x) { return x.type === 'country'; }).map(function (x) { return '<option value="' + esc(x.key) + '"' + (c.country_key === x.key ? ' selected' : '') + '>' + esc(x.title) + '</option>'; }).join('') + '</select>', 'Las ciudades sugeridas son las del país elegido; siempre se puede escribir otra.');
      if (f.type === 'address_map') html += '<div class="gw-alert">' + ic('info') + '<div class="gw-alert__body">Guarda la dirección escrita y, cuando exista el mapa, el punto marcado. El mapa se activa en una entrega posterior.</div></div>';
      if (f.type === 'inventory') {
        html += '<h3 class="gw-tpl-h2">Tipos de inventario</h3><p class="gw-hint">Cada línea del evento elige un tipo, una cantidad y (si tiene) una referencia de la lista.</p>' +
          (c.inventory_types || []).map(function (t, i) {
            return '<div class="gw-tpl-inv" data-inv="' + esc(t.key) + '"><div class="gw-field"><label class="gw-label" for="ti_l' + i + '">Nombre del tipo</label><input class="gw-input" id="ti_l' + i + '" type="text" maxlength="60" value="' + esc(t.label) + '" data-tpl-inv-label="' + esc(t.key) + '"></div>' +
              '<div class="gw-field"><label class="gw-label" for="ti_r' + i + '">Referencias (una por línea, opcional)</label><textarea class="gw-textarea" id="ti_r' + i + '" rows="3" data-tpl-inv-refs="' + esc(t.key) + '">' + esc((t.refs || []).join('\n')) + '</textarea></div>' +
              '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="inv-del" data-inv="' + esc(t.key) + '"' + ((c.inventory_types || []).length <= 1 ? ' disabled' : '') + '>' + ic('trash', 'gw-icon--sm') + ' Quitar este tipo</button></div>';
          }).join('') + '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-tpl-act="inv-add">' + ic('plus', 'gw-icon--sm') + ' Agregar tipo de inventario</button>';
      }
      html += '<div class="gw-tpl-move">' + lab('tp_sec', 'Paso en que se pide', '<select class="gw-select" id="tp_sec" data-tpl-prop="section"><option value=""' + (locked ? ' disabled' : '') + '>— No se pide al crear —</option>' + m.sections.map(function (s, i) { return '<option value="' + esc(s.id) + '"' + (si === i ? ' selected' : '') + '>' + (i + 1) + '. ' + esc(s.title) + '</option>'; }).join('') + '</select>', locked ? 'Este campo es obligatorio siempre y no se puede quitar.' : 'También puedes arrastrar la tarjeta o usar los botones de subir y bajar.') + '</div>';
      html += '<div class="gw-actions">' +
        (custom ? '<button type="button" class="gw-btn gw-btn--danger gw-btn--sm" data-tpl-act="retire" data-key="' + esc(f.key) + '">' + ic('trash', 'gw-icon--sm') + ' Retirar este campo</button>' : '') + '</div>';
      if (custom) html += '<p class="gw-hint">Retirar un campo no borra lo que ya se guardó en los eventos.</p>';
      return html;
    }
    function renderCreation() {
      q('tplPaletteA').innerHTML = paletteHtml();
      q('tplCanvasA').innerHTML = m.sections.map(sectionHtml).join('') + '<button type="button" class="gw-btn gw-btn--secondary" data-tpl-act="sec-add"' + (m.sections.length >= LIMITS.sections ? ' disabled' : '') + '>' + ic('plus', 'gw-icon--sm') + ' Agregar paso</button>';
      q('tplPropsA').innerHTML = propsHtml();
    }

    /* ---- vista B: calendario */
    var ZLABEL = { top: 'Arriba (encabezado)', left: 'Izquierda', right: 'Derecha', bottom: 'Abajo' };
    function chipHtml(it) {
      var f = model.field(m, it.key); if (!f) return '';
      return '<li class="gw-tpl-card gw-tpl-card--chip' + (calSel === f.key ? ' gw-tpl-card--sel' : '') + '" draggable="true" tabindex="0" role="button" aria-pressed="' + (calSel === f.key ? 'true' : 'false') + '" data-key="' + esc(f.key) + '" data-tpl-act="cal-select">' +
        '<span class="gw-tpl-card__grip" aria-hidden="true">' + ic('grip', 'gw-icon--sm') + '</span><span class="gw-tpl-card__body"><span class="gw-tpl-card__label">' + esc(f.title) + '</span><span class="gw-tpl-card__type">' + (it.label ? 'Con el nombre del campo' : 'Solo el valor') + '</span></span>' +
        '<span class="gw-tpl-card__tools"><button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="cal-up" data-key="' + esc(f.key) + '" aria-label="Subir «' + esc(f.title) + '»">' + ic('chevron', 'gw-icon--sm gw-tpl-up') + '</button>' +
        '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="cal-down" data-key="' + esc(f.key) + '" aria-label="Bajar «' + esc(f.title) + '»">' + ic('chevron', 'gw-icon--sm gw-tpl-down') + '</button></span></li>';
    }
    function zoneHtml(z) {
      var list = m.zones[z] || [];
      return '<div class="gw-tpl-zone gw-tpl-zone--' + z + (selZone === z ? ' gw-tpl-zone--sel' : '') + '" data-zone="' + z + '"><h3 class="gw-tpl-zone__title">' + esc(ZLABEL[z]) + '</h3>' +
        '<ol class="gw-tpl-list" data-drop-zone="' + z + '">' + list.map(chipHtml).join('') + '</ol><div class="gw-tpl-drop" data-drop-zone="' + z + '" data-drop-end="1">' + (list.length ? 'Suelta aquí' : 'Vacía: arrastra campos aquí') + '</div>' +
        '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-tpl-act="zone-pick" data-zone="' + z + '">Agregar aquí</button></div>';
    }
    function previewHtml() {
      var ev = sampleEvent(m), tpl = { fields: m.fields, calendar_layout: { zones: m.zones }, people: { commercial: [{ id: 1, name: 'Persona de ejemplo' }], coordinator: [{ id: 1, name: 'Persona de ejemplo' }] }, version: m.version };
      var cm = EF.cardModel(ev, EF.calendarLayout(tpl)), row = function (it) { return '<div class="gw-evf-card">' + (it.label ? '<span class="gw-evf-card__label">' + esc(it.title) + '</span>' : '') + '<span>' + esc(it.text) + '</span></div>'; };
      return '<article class="gw-tpl-preview" aria-label="Vista previa de la tarjeta"><header class="gw-tpl-preview__top">' + cm.top.map(row).join('') + '</header>' +
        '<div class="gw-tpl-preview__cols"><div>' + cm.left.map(row).join('') + '</div><div>' + cm.right.map(row).join('') + '</div></div><footer>' + cm.bottom.map(row).join('') + '</footer></article>';
    }
    function calPropsHtml() {
      var f = calSel && model.field(m, calSel), z = f && model.zoneOf(m, calSel);
      if (!f || !z) return '<p class="gw-hint">Elige un campo de la tarjeta para cambiar dónde sale.</p>';
      var it = m.zones[z].filter(function (x) { return x.key === calSel; })[0];
      return '<h2 class="gw-tpl-h">' + esc(f.title) + '</h2><p class="gw-hint">' + esc(typeTag(f)) + '</p>' +
        lab('tc_zone', 'Dónde sale', '<select class="gw-select" id="tc_zone" data-tpl-cal-zone>' + ZONES.map(function (zz) { return '<option value="' + zz + '"' + (zz === z ? ' selected' : '') + '>' + esc(ZLABEL[zz]) + '</option>'; }).join('') + '</select>') +
        '<label class="gw-check"><input type="checkbox" data-tpl-cal-label' + (it.label ? ' checked' : '') + '> <span class="gw-choice__text">Mostrar también el nombre del campo</span></label>' +
        '<div class="gw-actions"><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-tpl-act="cal-remove" data-key="' + esc(f.key) + '">' + ic('close', 'gw-icon--sm') + ' Quitar de la tarjeta</button></div>';
    }
    function renderCalendar() {
      var free = model.calUnplaced(m);
      q('tplPaletteB').innerHTML = '<section class="gw-card gw-tpl-side"><h2 class="gw-tpl-h">Campos de la plantilla</h2><p class="gw-hint">Todos los campos posibles. Clic para ponerlos en «' + esc(ZLABEL[selZone]) + '» o arrástralos a la tarjeta.</p>' +
        (free.length ? '<div class="gw-tpl-pal">' + free.map(function (f) { return '<button type="button" class="gw-tpl-pal__btn" draggable="true" data-tpl-act="cal-add" data-key="' + esc(f.key) + '">' + ic('plus', 'gw-icon--sm') + '<span>' + esc(f.title) + '<small class="gw-tpl-pal__sub">' + esc(typeTag(f)) + '</small></span></button>'; }).join('') + '</div>' : '<p class="gw-hint">Todos los campos ya salen en la tarjeta.</p>') + '</section>';
      q('tplCanvasB').innerHTML = '<div class="gw-tpl-calgrid">' + zoneHtml('top') + zoneHtml('left') + zoneHtml('right') + zoneHtml('bottom') + '</div><h3 class="gw-tpl-h2">Así se verá (con datos de ejemplo)</h3>' + previewHtml();
      q('tplPropsB').innerHTML = calPropsHtml();
    }

    function renderAll() {
      q('tplMeta').textContent = m.version ? 'Versión ' + m.version + (m.updated_by ? ' · guardada por ' + m.updated_by : '') : 'Plantilla de fábrica (nadie la ha cambiado todavía)';
      renderCreation(); renderCalendar();
    }
    var rerender = function () { renderAll(); dirty(); };
    function focusCard(key, panel) { var el = host.querySelector('#' + panel + ' .gw-tpl-card[data-key="' + key + '"]'); if (el) el.focus(); }

    /* ---- acciones (delegación) */
    function act(name, el) {
      var key = el.getAttribute('data-key');
      switch (name) {
        case 'select': sel = key; renderCreation(); break;                                  // solo cambia la selección: no es una edición
        case 'cal-select': calSel = key; renderCalendar(); break;
        case 'add-type': { var k = addField(m, el.getAttribute('data-type'), selSection); if (!k) { toast('Ya no caben más campos activos en la plantilla', 'error'); break; } sel = k; rerender(); toast('Campo agregado: cámbiale el título a la derecha', 'success'); break; }
        case 'add-field': { var sec = m.sections.filter(function (s) { return s.id === selSection; })[0] || m.sections[m.sections.length - 1]; place(m, key, sec.id); sel = key; rerender(); break; }
        case 'restore': restore(m, key); rerender(); break;
        case 'up': case 'down': { if (!moveBy(m, key, name === 'up' ? -1 : 1)) break; sel = key; rerender(); focusCard(key, 'tplCanvasA'); break; }
        case 'sec-add': { var id = addSection(m, 'Nuevo paso'); if (id) { selSection = id; rerender(); } break; }
        case 'sec-del': { var sid = el.getAttribute('data-sec'), r = removeSection(m, sid); if (!r.ok) toast(r.reason, 'error'); else { if (selSection === sid) selSection = null; rerender(); if (r.note) toast(r.note, 'info'); } break; }
        case 'sec-up': case 'sec-down': if (moveSection(m, el.getAttribute('data-sec'), name === 'sec-up' ? -1 : 1)) rerender(); break;
        case 'retire': { var f = model.field(m, key); root.showConfirm('¿Retirar «' + esc(f.title) + '»? Sale de las dos vistas, pero lo que ya se guardó en los eventos se conserva.', { confirmLabel: 'Retirar' }).then(function (ok) { if (ok) { retire(m, key); sel = null; rerender(); } }); break; }
        case 'inv-add': if (sel && addInventoryType(m, sel)) rerender(); break;
        case 'inv-del': if (sel && removeInventoryType(m, sel, el.getAttribute('data-inv'))) rerender(); break;
        case 'cal-add': { if (!calPlace(m, key, selZone)) { toast('Esa zona ya tiene el máximo de campos (' + LIMITS.zoneItems + ')', 'error'); break; } calSel = key; rerender(); break; }
        case 'cal-up': case 'cal-down': { if (calMoveBy(m, key, name === 'cal-up' ? -1 : 1)) { calSel = key; rerender(); focusCard(key, 'tplCanvasB'); } break; }
        case 'cal-remove': calUnplace(m, key); calSel = null; rerender(); break;
        case 'zone-pick': selZone = el.getAttribute('data-zone'); renderCalendar(); break;
      }
    }
    host.addEventListener('click', function (e) {
      var el = e.target.closest('[data-tpl-act]');
      if (el) {
        if (el.getAttribute('data-tpl-act') === 'select' && e.target.closest('.gw-tpl-card__tools')) return;           // los botones subir/bajar actúan solos
        act(el.getAttribute('data-tpl-act'), el);
        return;
      }
      var s = e.target.closest('.gw-tpl-sec'); if (s && selSection !== s.getAttribute('data-sec')) { selSection = s.getAttribute('data-sec'); host.querySelectorAll('.gw-tpl-sec').forEach(function (n) { n.classList.toggle('gw-tpl-sec--sel', n === s); }); }
    });
    host.addEventListener('keydown', function (e) {
      var card = e.target.closest && e.target.closest('.gw-tpl-card');
      if (!card || e.target !== card) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
    });
    function setProp(f, prop, value) {
      var c = f.config = f.config || {};
      switch (prop) {
        case 'title': f.title = value; break;
        case 'help': f.help = value; break;
        case 'required': setRequired(m, f.key, value); break;
        case 'options': f.options = parseLines(value).slice(0, LIMITS.options); break;
        case 'currency': c.currency = value; break;
        case 'min': c.min = value === '' ? null : Number(value); break;
        case 'max': c.max = value === '' ? null : Number(value); break;
        case 'decimals': c.decimals = Math.max(0, Math.min(4, Number(value) || 0)); break;
        case 'max_len': c.max_len = Math.max(1, Number(value) || 1); break;
        case 'cmax': c.max = Math.max(1, Math.min(8, Number(value) || 1)); break;
        case 'country_key': c.country_key = value || null; break;
        case 'section': if (!value) { var r = unplace(m, f.key); if (!r.ok) toast(r.reason, 'error'); else if (r.note) toast(r.note, 'info'); } else place(m, f.key, value); break;
      }
    }
    host.addEventListener('input', function (e) {                           // texto que se escribe: se guarda en el modelo SIN repintar (no se pierde el cursor)
      var t = e.target, f = sel && model.field(m, sel), p;
      if ((p = t.getAttribute('data-tpl-prop')) && f && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') && t.type !== 'checkbox') {
        setProp(f, p, t.value);
        if (p === 'title') { var lab2 = host.querySelector('#tplCanvasA .gw-tpl-card[data-key="' + f.key + '"] .gw-tpl-card__label'); if (lab2) lab2.textContent = f.title; }
        dirty(); return;
      }
      if (t.hasAttribute('data-tpl-sec-title')) { var s = m.sections.filter(function (x) { return x.id === t.getAttribute('data-tpl-sec-title'); })[0]; if (s) { s.title = t.value; dirty(); } return; }
      if (t.hasAttribute('data-tpl-inv-label') && f) { var ty = f.config.inventory_types.filter(function (x) { return x.key === t.getAttribute('data-tpl-inv-label'); })[0]; if (ty) { ty.label = t.value; dirty(); } return; }
      if (t.hasAttribute('data-tpl-inv-refs') && f) { var ty2 = f.config.inventory_types.filter(function (x) { return x.key === t.getAttribute('data-tpl-inv-refs'); })[0]; if (ty2) { ty2.refs = parseLines(t.value); dirty(); } }
    });
    host.addEventListener('change', function (e) {                         // listas y casillas: sí se repinta (cambia la vista)
      var t = e.target, f = sel && model.field(m, sel), p;
      if ((p = t.getAttribute('data-tpl-prop')) && f && (t.tagName === 'SELECT' || t.type === 'checkbox')) { setProp(f, p, t.type === 'checkbox' ? t.checked : t.value); rerender(); return; }
      if (t.hasAttribute('data-tpl-prop') && f) { renderAll(); return; }            // textos: al salir del campo se refrescan tarjetas y vista previa
      if (t.hasAttribute('data-tpl-cal-zone') && calSel) { if (!calPlace(m, calSel, t.value)) toast('Esa zona ya tiene el máximo de campos (' + LIMITS.zoneItems + ')', 'error'); rerender(); return; }
      if (t.hasAttribute('data-tpl-cal-label') && calSel) { calSetLabel(m, calSel, t.checked); rerender(); return; }
      if (t.hasAttribute('data-tpl-sec-title') || t.hasAttribute('data-tpl-inv-label') || t.hasAttribute('data-tpl-inv-refs')) renderAll();
    });

    /* ---- arrastrar y soltar (HTML5). Alternativa con teclado: los botones Subir/Bajar y las listas «Paso»/«Zona». */
    var dragData = null;
    host.addEventListener('dragstart', function (e) {
      var n = e.target.closest && e.target.closest('[draggable="true"]'); if (!n) return;
      var act2 = n.getAttribute('data-tpl-act');
      dragData = { act: act2, key: n.getAttribute('data-key'), type: n.getAttribute('data-type') };
      e.dataTransfer.setData('text/plain', 'plantilla'); e.dataTransfer.effectAllowed = 'move'; n.classList.add('gw-tpl-card--drag');
    });
    host.addEventListener('dragend', function () { dragData = null; host.querySelectorAll('.gw-tpl-card--drag, .gw-tpl-over').forEach(function (n) { n.classList.remove('gw-tpl-card--drag', 'gw-tpl-over'); }); });
    function dropTarget(e) {
      var list = e.target.closest && e.target.closest('[data-drop-sec],[data-drop-zone]'); if (!list) return null;
      var sec = list.getAttribute('data-drop-sec'), zone = list.getAttribute('data-drop-zone'), card = e.target.closest('.gw-tpl-card'), index = null;
      if (card && !list.hasAttribute('data-drop-end')) {
        var keys = sec ? (m.sections.filter(function (s) { return s.id === sec; })[0] || { keys: [] }).keys : (m.zones[zone] || []).map(function (it) { return it.key; });
        index = keys.indexOf(card.getAttribute('data-key'));
        var r = card.getBoundingClientRect(); if (index >= 0 && e.clientY > r.top + r.height / 2) index += 1;
      }
      return { el: list, sec: sec, zone: zone, index: index };
    }
    host.addEventListener('dragover', function (e) { if (!dragData) return; var t = dropTarget(e); if (!t) return; e.preventDefault(); host.querySelectorAll('.gw-tpl-over').forEach(function (n) { n.classList.remove('gw-tpl-over'); }); t.el.classList.add('gw-tpl-over'); });
    host.addEventListener('drop', function (e) {
      if (!dragData) return; var t = dropTarget(e); if (!t) return; e.preventDefault();
      var d = dragData; dragData = null;
      if (t.sec) {
        if (d.act === 'add-type') { var k = addField(m, d.type, t.sec); if (!k) { toast('Ya no caben más campos activos en la plantilla', 'error'); return; } place(m, k, t.sec, t.index); sel = k; }
        else if (d.act === 'select' || d.act === 'add-field') { place(m, d.key, t.sec, t.index); sel = d.key; }
        else return;
      } else if (t.zone) {
        if (d.act !== 'cal-select' && d.act !== 'cal-add') return;
        if (!calPlace(m, d.key, t.zone, t.index)) { toast('Esa zona ya tiene el máximo de campos (' + LIMITS.zoneItems + ')', 'error'); return; }
        calSel = d.key; selZone = t.zone;
      }
      rerender();
    });

    return { load: load, getModel: function () { return m; }, validate: function () { return validate(m); }, payload: function () { return toPayload(m); }, hasModel: function () { return !!m; } };
  }

  var api = { model: model, mount: mount, esc: esc };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
  root.EventTemplateDesigner = api;
})(typeof window !== 'undefined' ? window : globalThis);
