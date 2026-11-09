/* Campos de la plantilla de evento (Fase 2): UN solo renderizador "tipo de campo -> control" para reutilizar en Nuevo evento, en la edición del evento y en los widgets futuros (mapa, inventario).
   Espejo en el navegador de app/event_template.py: el servidor SIEMPRE vuelve a validar. Todo texto del administrador (títulos, opciones, ayudas) se ESCAPA aquí; se muestra a todo el personal.
   Contratos (docs/FASE_2_ALCANCE.md, «Plantilla de evento: modelo y contratos»):
     EventFields.renderField(field, {value, ctx})  -> HTML de un campo (etiqueta + control + ayuda). Cada control lleva data-evf-key="<clave>" y data-evf-part="<parte>".
     EventFields.readField(field, root)            -> valor listo para enviar (misma forma que guarda el servidor) o null si está vacío.
     EventFields.validateValue(field, value)       -> mensaje de error o null (obligatorio y formato).
     EventFields.formatValue(field, value, ctx)    -> texto plano para mostrar (resumen, calendario).
     EventFields.valueOf(field, event)             -> valor crudo de un campo dentro de un evento serializado por /api/events.
     EventFields.displayValue(field, event, ctx)   -> texto del valor de un evento ('' si no tiene).
     EventFields.calendarLayout(templateResponse, extra) -> el `layout` que recibe renderCalendarCard(event, layout).
     EventFields.cardModel(event, layout)          -> {top|left|right|bottom: [{key,type,title,label,text}]} solo con los campos que tienen valor.
     EventFields.afterMount(host, {geoUrl, loadCities}) -> relojes, librería de colores, país/ciudad con GWGeo+combobox y enganches de mapa/inventario; devuelve una promesa.
     EventFields.geoPair(paisInput, ciudadInput, geoUrl) -> promesa {set(país, ciudad)} para campos fijos (Editar evento).
   `ctx` (todo opcional): countries[], people{commercial:[{id,name}],coordinator:[{id,name}]}, superEvents[{id,name}], tenantName, readonly{clave:true}, hidden{clave:true}, idPrefix.
   Ganchos para otros agentes (no cambian el contrato): data-evf-enhance="country|city|map|combobox|inventory" en el contenedor del campo. */
(function (root) {
  'use strict';
  var esc = function (t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var CURRENCY = { COP: '$', USD: 'US$', EUR: '€' };
  var DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/, TIME_RE = /^(\d{1,2}):(\d{2})$/, HEX_RE = /^#[0-9a-fA-F]{6}$/;
  var WD = root.Workday || (function () { try { return require('./workday.js'); } catch (e) { return null; } })();          // jornada (Fase 5): espejo de app/workday.py
  var EMPTY = function (v) { return v == null || v === '' || (Array.isArray(v) && !v.length); };

  /* base: clave del campo -> cómo se lee de un evento serializado (/api/events) */
  var BASE_EVENT = {
    client: function (e) { return e.tenant_name; }, event_code: function (e) { return e.event_code; }, name: function (e) { return e.name; }, country: function (e) { return e.country; }, city: function (e) { return e.city; },
    location: function (e) { return e.location; }, address: function (e) { return e.address; }, start_date: function (e) { return e.start_date; }, end_date: function (e) { return e.end_date; },
    setup_date: function (e) { return e.setup_date; }, event_time_start: function (e) { return e.event_time_start; }, event_time_end: function (e) { return e.event_time_end; },
    setup_time_start: function (e) { return e.setup_time_start; }, setup_time_end: function (e) { return e.setup_time_end; },
    coordinator_staff_id: function (e) { return e.coordinator_name; }, commercial_staff_id: function (e) { return e.commercial_name; }, super_event_id: function (e) { return e.super_event_name; },
    bandana: function (e) { return e.bandana_colors; }, notes: function (e) { return e.notes; },
  };

  /* Jornada (campo calculado, solo lectura): se deduce de las horas del evento; si el evento no trae horas pero el servidor sí mandó workday_* se usan esos. */
  function workdayOf(event) {
    var w = WD ? WD.compute(event.event_time_start, event.event_time_end) : null;
    if (w) return w;
    return event.workday_label ? { key: event.workday_key, label: event.workday_label, hours: event.workday_hours, hours_text: event.workday_hours != null ? String(event.workday_hours).replace('.', ',') + ' h' : '' } : null;
  }
  function workdayText(start, end) { return (WD && WD.text(start, end)) || '—'; }

  function valueOf(field, event) {
    if (!field || !event) return null;
    if (field.type === 'workday') return workdayOf(event);
    if (field.type === 'switch') return !!((event.switches || {})[(field.config || {}).switch]);
    if (BASE_EVENT[field.key]) return BASE_EVENT[field.key](event);
    var x = event.extra || {};
    return x[field.key] == null ? null : x[field.key];
  }

  /* ---------------------------------------------------------------------------------------------------- formato para mostrar */
  function groupThousands(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.'); }
  function formatNumber(v, decimals) {
    var n = Number(v); if (!isFinite(n)) return String(v);
    var neg = n < 0; n = Math.abs(n);
    var parts = n.toFixed(decimals || 0).split('.');
    return (neg ? '-' : '') + groupThousands(parts[0]) + (parts[1] ? ',' + parts[1] : '');
  }
  function formatDate(s) { var m = DATE_RE.exec(String(s || '')); return m ? m[3] + '/' + m[2] + '/' + m[1] : String(s || ''); }
  function personName(ctx, kind, id) {
    var list = ((ctx && ctx.people) || {})[kind] || [];
    for (var i = 0; i < list.length; i++) if (String(list[i].id) === String(id)) return list[i].name;
    return '';
  }
  function formatValue(field, value, ctx) {
    if (field.type === 'switch') return value ? 'Sí' : 'No';
    if (field.type === 'workday') return value && value.label ? value.label + (value.hours_text ? ' · ' + value.hours_text : '') : '';
    if (EMPTY(value)) return '';
    switch (field.type) {
      case 'money': return (CURRENCY[(field.config || {}).currency] || '$') + ' ' + formatNumber(value, Number(value) % 1 ? 2 : 0);
      case 'number': return formatNumber(value, Number((field.config || {}).decimals) || 0);
      case 'date': return formatDate(value);
      case 'datetime': { var p = String(value).split('T'); return formatDate(p[0]) + ' ' + (p[1] || ''); }
      case 'commercial': case 'coordinator': return typeof value === 'number' ? (personName(ctx, field.type, value) || '') : String(value);
      case 'address_map': return value.text || (value.lat != null ? value.lat + ', ' + value.lng : '');
      case 'contact': return [value.name, value.phone].filter(Boolean).join(' · ');
      case 'bandana_colors': return value.map(function (c) { return c.name || c.hex; }).join(', ');
      case 'inventory': {
        var types = {}; ((field.config || {}).inventory_types || []).forEach(function (t) { types[t.key] = t.label; });
        return value.map(function (l) { return (types[l.type] || l.type) + ' ×' + (l.qty == null ? 0 : l.qty) + (l.ref ? ' (' + l.ref + ')' : ''); }).join(', ');
      }
      default: return String(value);
    }
  }
  function displayValue(field, event, ctx) {
    var v = valueOf(field, event);
    if (BASE_EVENT[field.key] && (field.key === 'coordinator_staff_id' || field.key === 'commercial_staff_id' || field.key === 'super_event_id' || field.key === 'client')) return v ? String(v) : '';
    return formatValue(field, v, ctx);
  }

  /* ---------------------------------------------------------------------------------------------------- calendario (contrato de renderCalendarCard) */
  function calendarLayout(tpl, ctx) {
    var fields = {}; ((tpl && tpl.fields) || []).forEach(function (f) { fields[f.key] = f; });
    return { zones: (tpl && tpl.calendar_layout && tpl.calendar_layout.zones) || { top: [], left: [], right: [], bottom: [] }, fields: fields, ctx: ctx || { people: (tpl && tpl.people) || {} }, version: (tpl && tpl.version) || 0 };
  }
  function cardModel(event, layout) {
    var out = {};
    ['top', 'left', 'right', 'bottom'].forEach(function (z) {
      out[z] = [];
      ((layout.zones || {})[z] || []).forEach(function (it) {
        var f = layout.fields[it.key];
        if (!f || f.retired) return;
        var text = displayValue(f, event, layout.ctx);
        if (!text) return;
        out[z].push({ key: f.key, type: f.type, title: f.title, label: !!it.label, text: text });
      });
    });
    return out;
  }

  /* ---------------------------------------------------------------------------------------------------- validación (espejo del servidor) */
  function validateValue(field, value) {
    var t = field.type, w = '«' + field.title + '»';
    if (t === 'switch' || t === 'workday') return null;
    if (EMPTY(value) || (typeof value === 'string' && !value.trim())) return field.required ? w + ' es obligatorio' : null;
    var cfg = field.config || {};
    switch (t) {
      case 'text_short': case 'text_long': {
        var max = Number(cfg.max_len) || (t === 'text_short' ? 200 : 2000);
        if (/[<>]/.test(value)) return w + ' no puede incluir «<» ni «>»';
        if (String(value).trim().length > max) return w + ' admite hasta ' + max + ' caracteres';
        return null;
      }
      case 'select': return (field.options || []).indexOf(value) < 0 ? w + ': elige una de las opciones' : null;
      case 'money': case 'number': {
        var n = Number(String(value).replace(/\s/g, '').replace(',', '.'));
        if (!isFinite(n)) return w + ' debe ser un número';
        if (t === 'money' && n < 0) return w + ' no puede ser negativo';
        if (t === 'number') {
          if (cfg.min != null && n < cfg.min) return w + ' no puede ser menor que ' + cfg.min;
          if (cfg.max != null && n > cfg.max) return w + ' no puede ser mayor que ' + cfg.max;
          var dec = Number(cfg.decimals) || 0, frac = (String(value).replace(',', '.').split('.')[1] || '').length;
          if (frac > dec) return w + ' admite hasta ' + dec + ' decimales';
        }
        return null;
      }
      case 'date': return DATE_RE.test(value) ? null : w + ' debe ser una fecha válida';
      case 'time': { var m = TIME_RE.exec(value); return m && +m[1] < 24 && +m[2] < 60 ? null : w + ' debe ser una hora válida'; }
      case 'datetime': { var p = String(value).split('T'); return DATE_RE.test(p[0] || '') && TIME_RE.test(p[1] || '') ? null : w + ' necesita fecha y hora'; }
      case 'contact': {
        if (value.phone) { var d = String(value.phone).replace(/\D/g, ''); if (d.length < 7 || d.length > 15) return w + ': el teléfono celular debe tener entre 7 y 15 dígitos'; }
        return field.required && (!value.name || !value.phone) ? w + ' necesita nombre y teléfono' : null;
      }
      case 'address_map': return (value.lat == null) !== (value.lng == null) ? w + ': falta una coordenada del mapa' : null;
      case 'bandana_colors': return value.some(function (c) { return !HEX_RE.test(c.hex || ''); }) ? w + ': color inválido' : null;
      case 'inventory': return value.some(function (l) { return !(l.qty >= 0) || (l.qty % 1) !== 0; }) ? w + ': la cantidad debe ser un número entero' : null;
      default: return null;
    }
  }

  /* ---------------------------------------------------------------------------------------------------- pintar */
  function ids(field, ctx) { var p = (ctx && ctx.idPrefix) || 'evf'; return { id: p + '_' + field.key, p: p }; }
  function attrs(field, part, extra) {
    return ' data-evf-key="' + esc(field.key) + '" data-evf-part="' + part + '"' + (extra || '');
  }
  function optionsHtml(list, selected, blank) {
    return (blank ? '<option value="">' + esc(blank) + '</option>' : '') + list.map(function (o) {
      var v = typeof o === 'object' ? o.value : o, l = typeof o === 'object' ? o.label : o;
      return '<option value="' + esc(v) + '"' + (String(v) === String(selected) ? ' selected' : '') + '>' + esc(l) + '</option>';
    }).join('');
  }
  function peopleOptions(ctx, kind) { return (((ctx && ctx.people) || {})[kind] || []).map(function (p) { return { value: p.id, label: p.name }; }); }
  function bandanaSlot(field, i, c, multi) {
    var id = field.key + '_' + i;
    return '<div class="gw-fields-row gw-fields-row--2 gw-evf__color" data-evf-slot="' + i + '">' +
      (multi ? '<label class="gw-check"><input type="checkbox"' + attrs(field, 'use') + (c ? ' checked' : '') + '> Usar el color ' + (i + 1) + '</label>' : '') +
      '<div class="gw-field"><label class="gw-label" for="evf_c_' + esc(id) + '">Color' + (multi ? ' ' + (i + 1) : ' de pañoleta') + '</label><input class="gw-evf__swatch" id="evf_c_' + esc(id) + '" type="color"' + attrs(field, 'hex') + ' value="' + esc(c ? c.hex : '#d4af37') + '"></div>' +
      '<div class="gw-field"><label class="gw-label" for="evf_n_' + esc(id) + '">Nombre del color</label><input class="gw-input" id="evf_n_' + esc(id) + '" type="text" maxlength="60"' + attrs(field, 'name') + ' value="' + esc(c ? c.name : '') + '" placeholder="Ej. Rojo Golden"></div></div>';
  }
  function inventoryRow(field, line) {
    var types = (field.config || {}).inventory_types || [];
    var t = types.filter(function (x) { return x.key === (line && line.type); })[0] || types[0] || { refs: [] };
    return '<div class="gw-evf__invrow" data-evf-line>' +
      '<select class="gw-select" aria-label="Tipo de inventario"' + attrs(field, 'type') + '>' + optionsHtml(types.map(function (x) { return { value: x.key, label: x.label }; }), t.key) + '</select>' +
      '<input class="gw-input" type="number" min="0" step="1" aria-label="Cantidad"' + attrs(field, 'qty') + ' value="' + esc(line ? line.qty : '') + '" placeholder="Cantidad">' +
      '<select class="gw-select" aria-label="Referencia"' + attrs(field, 'ref') + (t.refs.length ? '' : ' disabled') + '>' + optionsHtml(t.refs, line && line.ref, t.refs.length ? 'Referencia…' : '') + '</select>' +
      '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-evf-act="inv-del" aria-label="Quitar esta línea">Quitar</button></div>';
  }

  function control(field, value, ctx) {
    var k = ids(field, ctx), cfg = field.config || {}, ro = ctx && ctx.readonly && ctx.readonly[field.key] ? ' readonly' : '', req = field.required ? ' aria-required="true"' : '';
    var id = ' id="' + esc(k.id) + '"';
    switch (field.type) {
      case 'text_short': return '<input class="gw-input"' + id + ' type="text" maxlength="' + (Number(cfg.max_len) || 200) + '"' + attrs(field, 'v') + ' value="' + esc(value) + '" autocomplete="off"' + ro + req + '>';
      case 'text_long': return '<textarea class="gw-textarea"' + id + ' maxlength="' + (Number(cfg.max_len) || 2000) + '"' + attrs(field, 'v') + ro + req + '>' + esc(value) + '</textarea>';
      case 'select': return '<select class="gw-select"' + id + attrs(field, 'v') + req + '>' + optionsHtml(field.options || [], value, 'Elige…') + '</select>';
      case 'money': return '<div class="gw-evf__money"><span class="gw-evf__unit" aria-hidden="true">' + esc(CURRENCY[cfg.currency] || '$') + '</span><input class="gw-input"' + id + ' type="text" inputmode="decimal"' + attrs(field, 'v') + ' value="' + esc(value) + '" autocomplete="off"' + req + ' aria-label="' + esc(field.title + ' en ' + (cfg.currency || 'COP')) + '"></div>';
      case 'number': return '<input class="gw-input"' + id + ' type="text" inputmode="decimal"' + attrs(field, 'v') + ' value="' + esc(value) + '" autocomplete="off"' + req + '>';
      case 'commercial': case 'coordinator': return '<select class="gw-select"' + id + attrs(field, 'v', ' data-evf-enhance="combobox"') + req + (ro ? ' disabled' : '') + '>' + optionsHtml(peopleOptions(ctx, field.type), value, 'Elige…') + '</select>';
      case 'super_event': return '<select class="gw-select"' + id + attrs(field, 'v') + '>' + optionsHtml(((ctx && ctx.superEvents) || []).map(function (s) { return { value: s.id, label: s.name + (s.events != null ? ' (' + s.events + ' eventos)' : '') }; }), value, '— Ninguno —') + '</select>';
      case 'date': return '<input class="gw-input"' + id + ' type="date"' + attrs(field, 'v') + ' value="' + esc(value) + '"' + req + '>';
      case 'time': return '<input class="gw-input clock-time"' + id + ' type="text"' + attrs(field, 'v') + ' value="' + esc(value) + '" autocomplete="off"' + req + '>';
      case 'datetime': {
        var p = String(value || '').split('T');
        return '<div class="gw-fields-row gw-fields-row--2"><input class="gw-input"' + id + ' type="date" aria-label="' + esc(field.title + ': fecha') + '"' + attrs(field, 'date') + ' value="' + esc(p[0] || '') + '"' + req + '>' +
          '<input class="gw-input clock-time" type="text" aria-label="' + esc(field.title + ': hora') + '"' + attrs(field, 'time') + ' value="' + esc(p[1] || '') + '" autocomplete="off"></div>';
      }
      case 'country': return '<input class="gw-input"' + id + ' type="text" list="' + esc(k.p + '_dl_countries') + '"' + attrs(field, 'v', ' data-evf-enhance="country"') + ' value="' + esc(value) + '" autocomplete="off"' + req + '>' +
        '<datalist id="' + esc(k.p + '_dl_countries') + '">' + ((ctx && ctx.countries) || []).map(function (c) { return '<option value="' + esc(c) + '">'; }).join('') + '</datalist>';
      case 'city': return '<input class="gw-input"' + id + ' type="text" list="' + esc(k.p + '_dl_' + field.key) + '"' + attrs(field, 'v', ' data-evf-enhance="city" data-evf-country="' + esc(cfg.country_key || '') + '"') + ' value="' + esc(value) + '" autocomplete="off"' + req + '>' +
        '<datalist id="' + esc(k.p + '_dl_' + field.key) + '"></datalist>';
      case 'address_map': {
        var a = value || {};
        return '<div data-evf-enhance="map"><input class="gw-input"' + id + ' type="text" maxlength="200"' + attrs(field, 'text') + ' value="' + esc(a.text) + '" autocomplete="off"' + req + '>' +
          '<input type="hidden"' + attrs(field, 'lat') + ' value="' + esc(a.lat == null ? '' : a.lat) + '"><input type="hidden"' + attrs(field, 'lng') + ' value="' + esc(a.lng == null ? '' : a.lng) + '"></div>';
      }
      case 'contact': {
        var c = value || {};
        return '<div class="gw-fields-row gw-fields-row--2"><input class="gw-input"' + id + ' type="text" maxlength="100" placeholder="Nombre" aria-label="' + esc(field.title + ': nombre') + '"' + attrs(field, 'name') + ' value="' + esc(c.name) + '" autocomplete="off"' + req + '>' +
          '<input class="gw-input" type="tel" inputmode="tel" maxlength="30" placeholder="Celular" aria-label="' + esc(field.title + ': celular') + '"' + attrs(field, 'phone') + ' value="' + esc(c.phone) + '" autocomplete="off"></div>';
      }
      case 'bandana_colors': {
        var max = Number(cfg.max) || 1, list = Array.isArray(value) ? value : [], html = '';
        for (var i = 0; i < max; i++) html += bandanaSlot(field, i, list[i] || null, max > 1);
        return '<div data-evf-enhance="colors">' + html + '</div>';
      }
      case 'inventory': {
        var lines = Array.isArray(value) && value.length ? value : [];
        return '<div data-evf-enhance="inventory"><div data-evf-lines>' + lines.map(function (l) { return inventoryRow(field, l); }).join('') + '</div>' +
          '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-evf-act="inv-add" data-evf-for="' + esc(field.key) + '">Agregar línea</button></div>';
      }
      case 'workday': return '<input class="gw-input" type="text" readonly tabindex="-1"' + id + attrs(field, 'v', ' data-evf-workday') + ' value="' + esc(typeof value === 'string' ? value : (value && value.label ? formatValue(field, value) : '—')) + '" aria-live="polite">';
      case 'switch': return '<label class="gw-check"><input type="checkbox"' + id + attrs(field, 'v') + (value ? ' checked' : '') + '> <span class="gw-choice__text">' + esc(field.title) + '</span></label>';
      case 'client':
        if (ctx && ctx.pickTenant) return '<input class="gw-input"' + id + ' type="text" data-gw-combobox autocomplete="off" required placeholder="Elige o escribe el nombre del cliente" data-evf-key="client" data-evf-part="v">';
        return '<input class="gw-input"' + id + ' type="text" readonly value="' + esc((ctx && ctx.tenantName) || '') + '" data-evf-key="client" data-evf-part="v">';
      default: return '';
    }
  }

  function renderField(field, opts) {
    opts = opts || {}; var ctx = opts.ctx || {};
    if (ctx.hidden && ctx.hidden[field.key]) return '';
    var k = ids(field, ctx), isSwitch = field.type === 'switch';
    var labelHtml = isSwitch ? '' : '<label class="gw-label" for="' + esc(k.id) + '">' + esc(field.title) + (field.required ? ' <span class="gw-req" aria-hidden="true">*</span>' : ' <span class="gw-hint">(' + (field.type === 'workday' ? 'calculada' : 'opcional') + ')</span>') + '</label>';
    var hint = field.help ? '<small class="gw-hint" id="' + esc(k.id) + '_h">' + esc(field.help) + '</small>' : '';
    var wide = { text_long: 1, address_map: 1, inventory: 1, bandana_colors: 1, contact: 1, datetime: 1 }[field.type] ? ' gw-evf--wide' : '';
    return '<div class="gw-field gw-evf' + wide + '" data-evf-field="' + esc(field.key) + '" data-evf-type="' + esc(field.type) + '">' + labelHtml + control(field, opts.value, ctx) + hint + '</div>';
  }

  /* ---------------------------------------------------------------------------------------------------- leer (de los controles) */
  function partsOf(field, rootEl) {
    var els = rootEl.querySelectorAll('[data-evf-key="' + field.key + '"]'), parts = {};
    for (var i = 0; i < els.length; i++) { var p = els[i].dataset.evfPart; (parts[p] = parts[p] || []).push(els[i]); }
    return parts;
  }
  var val = function (el) { return el ? String(el.value == null ? '' : el.value).trim() : ''; };
  function readField(field, rootEl) {
    var p = partsOf(field, rootEl);
    switch (field.type) {
      case 'switch': return p.v && p.v[0] ? !!p.v[0].checked : null;
      case 'client': case 'workday': return null;
      case 'datetime': { var d = val(p.date && p.date[0]), t = val(p.time && p.time[0]); return d || t ? d + 'T' + t : null; }
      case 'address_map': {
        var text = val(p.text && p.text[0]), lat = val(p.lat && p.lat[0]), lng = val(p.lng && p.lng[0]);
        return text || lat || lng ? { text: text, lat: lat === '' ? null : Number(lat), lng: lng === '' ? null : Number(lng) } : null;
      }
      case 'contact': { var n = val(p.name && p.name[0]), ph = val(p.phone && p.phone[0]); return n || ph ? { name: n, phone: ph } : null; }
      case 'bandana_colors': {
        var out = [], hexes = p.hex || [], names = p.name || [], uses = p.use || [], multi = uses.length > 0;
        for (var i = 0; i < hexes.length; i++) if (!multi || uses[i].checked) out.push({ name: val(names[i]), hex: val(hexes[i]) });
        return out.length ? out : null;
      }
      case 'inventory': {
        var types = p.type || [], qtys = p.qty || [], refs = p.ref || [], lines = [];
        for (var j = 0; j < types.length; j++) lines.push({ type: val(types[j]), qty: val(qtys[j]) === '' ? null : Number(val(qtys[j])), ref: val(refs[j]) || null });
        return lines.length ? lines : null;
      }
      case 'commercial': case 'coordinator': case 'super_event': { var s = val(p.v && p.v[0]); return s === '' ? null : Number(s); }
      default: { var x = val(p.v && p.v[0]); return x === '' ? null : x; }
    }
  }

  /* ---------------------------------------------------------------------------------------------------- jornada en vivo
     bindWorkday(host, {read, targets}): al cambiar las horas dentro de `host` (input/change, también el reloj) reescribe los controles [data-evf-workday] (o `targets`) con «Jornada completa · 10 h» o «—».
     `read()` devuelve {start, end}; por defecto lee los campos event_time_start/event_time_end de la plantilla dentro de `host`. Devuelve la función `refresh` (también se llama una vez al enganchar). */
  function bindWorkday(host, opts) {
    opts = opts || {};
    var read = opts.read || function () {
      var a = host.querySelector('[data-evf-key="event_time_start"][data-evf-part="v"]'), b = host.querySelector('[data-evf-key="event_time_end"][data-evf-part="v"]');
      return { start: a ? a.value : '', end: b ? b.value : '' };
    };
    function refresh() {
      var t = read(), text = workdayText(t.start, t.end), outs = host.querySelectorAll(opts.targets || '[data-evf-workday]');
      for (var i = 0; i < outs.length; i++) outs[i].value = text;
    }
    host.addEventListener('input', refresh);
    host.addEventListener('change', refresh);
    refresh();
    return refresh;
  }

  /* ---------------------------------------------------------------------------------------------------- edición de un evento (campos personalizados)
     customFields(tpl): los campos personalizados ACTIVOS (clave c_…, sin interruptores ni cliente) en el orden de «Nuevo evento»; los base siguen en su sitio de la pantalla.
     diffExtra(fields, original, read): arma el `extra` del PATCH con SOLO lo que cambió ({clave: valor|null}); valida cada cambio. Un obligatorio que el evento viejo nunca tuvo no bloquea; vaciar uno que sí tenía, sí.
     Devuelve {extra} o {error, key}. */
  function customFields(tpl) {
    var byKey = {}, ordered = [];
    ((tpl && tpl.fields) || []).forEach(function (f) { if (/^c_/.test(f.key) && !f.retired && f.type !== 'switch' && f.type !== 'client') byKey[f.key] = f; });
    (((tpl && tpl.creation_layout) || {}).sections || []).forEach(function (s) { (s.keys || []).forEach(function (k) { if (byKey[k]) { ordered.push(byKey[k]); delete byKey[k]; } }); });
    return ordered.concat(Object.keys(byKey).map(function (k) { return byKey[k]; }));
  }
  function sameValue(a, b) {
    if (a != null && typeof a !== 'object' && b != null && typeof b !== 'object') return String(a) === String(b);
    return JSON.stringify(a == null ? null : a) === JSON.stringify(b == null ? null : b);
  }
  function diffExtra(fields, original, read) {
    var extra = {}, before = original || {};
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i], v = read(f), b = before[f.key] == null ? null : before[f.key];
      if (sameValue(v, b)) continue;
      var msg = validateValue(f, v);
      if (msg) return { error: msg, key: f.key };
      extra[f.key] = v;
    }
    return { extra: extra };
  }

  /* ---------------------------------------------------------------------------------------------------- comportamiento (solo navegador) */
  function bind(host, opts) {
    opts = opts || {};
    host.addEventListener('click', function (e) {
      var add = e.target.closest && e.target.closest('[data-evf-act="inv-add"]');
      if (add) {
        var key = add.getAttribute('data-evf-for'), field = (opts.fields || {})[key];
        if (field) { var box = add.parentNode.querySelector('[data-evf-lines]'); box.insertAdjacentHTML('beforeend', inventoryRow(field, null)); }
        return;
      }
      var del = e.target.closest && e.target.closest('[data-evf-act="inv-del"]');
      if (del) { var row = del.closest('[data-evf-line]'); if (row) row.remove(); host.dispatchEvent(new Event('input', { bubbles: true })); }
    });
    host.addEventListener('change', function (e) {
      var sel = e.target;
      if (sel.dataset && sel.dataset.evfPart === 'type' && sel.closest && sel.closest('[data-evf-line]')) {          // cambió el tipo de inventario: cambian sus referencias
        var field = (opts.fields || {})[sel.dataset.evfKey], t = field && ((field.config || {}).inventory_types || []).filter(function (x) { return x.key === sel.value; })[0];
        var ref = sel.closest('[data-evf-line]').querySelector('[data-evf-part="ref"]');
        if (t && ref) { ref.innerHTML = optionsHtml(t.refs, '', t.refs.length ? 'Referencia…' : ''); ref.disabled = !t.refs.length; }
      }
      if (sel.dataset && sel.dataset.evfEnhance === 'country') cityDeps(host, sel.dataset.evfKey, sel.value, opts);
    });
  }
  /* ---------------------------------------------------------------------------------------------------- país y ciudad (GWGeo + GWCombobox)
     País = todos los países con búsqueda al escribir; ciudad = las del país elegido, y si no está en la lista se queda el texto que se escribió (texto libre).
     Lo que se guarda SIEMPRE es el texto (nombre del país / de la ciudad), igual que antes en `country`/`city`. Sin GWGeo/GWCombobox o si falla la carga de geo.json, queda el campo de texto con
     sugerencias del servidor (datalist + /api/cities), como antes. */
  var geoState = { promise: null, ok: null };
  function loadGeo(url) {
    if (geoState.promise) return geoState.promise;
    if (!root.GWGeo || !root.GWCombobox || !url) { geoState.ok = false; return Promise.resolve(false); }          // sin url no se memoiza: otra llamada puede traerla
    geoState.promise = Promise.resolve(root.GWGeo.load(url)).then(function () { geoState.ok = true; return true; }, function () { geoState.ok = false; geoState.promise = null; return false; });
    return geoState.promise;
  }
  function codeOf(text) { var c = String(text || '').trim() ? root.GWGeo.findCountry(text) : null; return c ? c.value : ''; }
  function citiesFor(text) { var code = codeOf(text); return code ? root.GWGeo.citiesOf(code) : []; }
  /* Engancha el combobox SIN avisar de cambios por el valor que ya traía el campo (así «Hay cambios sin guardar» no salta solo). */
  function comboAttach(input, cfg, resolve) {
    var v = input.value; input.value = '';
    var cb = root.GWCombobox.attach(input, cfg);
    if (v) cb.setValue(resolve ? resolve(v) : v, true);
    return cb;
  }
  function dropDatalist(input) {
    var id = input.getAttribute('list'); input.removeAttribute('list');
    var dl = id && input.ownerDocument ? input.ownerDocument.getElementById(id) : null;
    if (dl && dl.parentNode === input.parentNode) dl.parentNode.removeChild(dl);
  }
  function enhanceCountry(input) {
    if (input.dataset.evfGeo) return input._gwCombobox;
    input.dataset.evfGeo = '1'; dropDatalist(input);
    return comboAttach(input, { allowFreeText: true, limit: 300, placeholder: 'Escribe para buscar el país', options: root.GWGeo.searchCountries('', 300) }, function (t) { return codeOf(t) || t; });
  }
  function enhanceCity(input, countryInput) {
    if (input.dataset.evfGeo) return input._gwCombobox;
    input.dataset.evfGeo = '1'; dropDatalist(input);
    var cb = comboAttach(input, { allowFreeText: true, limit: 80, placeholder: 'Escribe para buscar o usa otra ciudad', options: countryInput ? citiesFor(countryInput.value) : [] });
    var st = input._evfGeo = { last: countryInput ? codeOf(countryInput.value) : '', cb: cb };
    if (countryInput) {
      var refresh = function (ev) {
        var text = countryInput.value, code = codeOf(text);
        if (!code && String(text).trim() && !(ev && ev.type === 'focusout')) return;          // a medio escribir el país: se conservan las ciudades hasta que quede definido
        if (code === st.last) return;
        st.last = code; cb.setOptions(code ? root.GWGeo.citiesOf(code) : []);                 // el país cambió: ciudades nuevas; una ciudad de la lista que ya no aplica se suelta, un texto libre se conserva
      };
      countryInput.addEventListener('gw:combobox-change', refresh);
      countryInput.addEventListener('focusout', refresh);
    }
    return cb;
  }
  /* Para pantallas con campos fijos (Editar evento): enlaza un par país/ciudad. Devuelve una promesa con {set(país, ciudad)} que sirve antes y después de que cargue la lista. */
  function geoPair(countryInput, cityInput, geoUrl) {
    var api = {
      ready: false,
      set: function (country, city) {
        if (!api.ready) { if (countryInput) countryInput.value = country || ''; if (cityInput) cityInput.value = city || ''; return; }
        if (countryInput && countryInput._gwCombobox) countryInput._gwCombobox.setValue(codeOf(country) || country || '', true);
        if (cityInput && cityInput._gwCombobox) {
          var st = cityInput._evfGeo; if (st) st.last = codeOf(country);
          cityInput._gwCombobox.setOptions(citiesFor(country)); cityInput._gwCombobox.setValue(city || '', true);
        }
      }
    };
    return loadGeo(geoUrl).then(function (ok) {
      if (!ok) return api;
      if (countryInput) enhanceCountry(countryInput);
      if (cityInput) enhanceCity(cityInput, countryInput);
      api.ready = true;
      return api;
    });
  }
  function cityDeps(host, countryKey, country, opts) {
    if (geoState.ok !== false) return;          // con GWGeo activo (o cargando) las ciudades las resuelve el combobox; esto es solo el respaldo del servidor
    var cities = host.querySelectorAll('[data-evf-enhance="city"][data-evf-country="' + countryKey + '"]');
    Array.prototype.forEach.call(cities, function (input) {
      var dl = host.querySelector('#' + (input.getAttribute('list') || '__'));
      if (!dl) return;
      if (typeof opts.loadCities !== 'function' || !String(country || '').trim()) { dl.innerHTML = ''; return; }
      Promise.resolve(opts.loadCities(String(country).trim())).then(function (list) {
        dl.innerHTML = (list || []).map(function (c) { return '<option value="' + esc(c) + '">'; }).join('');
      }).catch(function () { dl.innerHTML = ''; });
    });
  }
  /* Después de pintar: relojes, librería de colores (en cada color del campo), enganches de mapa/inventario y país/ciudad (GWGeo). Devuelve una promesa (true si se usó GWGeo). */
  function afterMount(host, opts) {
    opts = opts || {};
    if (typeof root.attachClockPicker === 'function') {
      Array.prototype.forEach.call(host.querySelectorAll('.clock-time'), function (input) {
        if (input.dataset.evfClock) return; input.dataset.evfClock = '1';
        root.attachClockPicker(input);
        input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); input.click(); } });          // con teclado, Enter o Espacio abren el reloj
      });
    }
    if (root.ColorLibrary && typeof root.ColorLibrary.attach === 'function') {
      Array.prototype.forEach.call(host.querySelectorAll('[data-evf-enhance="colors"] [data-evf-slot]'), function (slot) {          // la misma librería de colores guardados que el formulario, en cada color del campo
        if (slot.dataset.evfLib) return; slot.dataset.evfLib = '1';
        root.ColorLibrary.attach(slot.querySelector('input[type="color"]'), slot.querySelector('input[type="text"]'));
        var use = slot.querySelector('input[type="checkbox"]'), next = slot.nextElementSibling, pick = next && next.querySelector ? next.querySelector('.cl-select') : null;
        if (use && pick) pick.addEventListener('change', function () { if (pick.value) use.checked = true; });          // elegir un color guardado activa ese color
      });
    }
    Array.prototype.forEach.call(host.querySelectorAll('[data-evf-enhance="map"]'), function (el) { if (root.GWMap) root.GWMap.enhance(el, opts); });                 // enganche del widget de mapa (gw-map.js)
    Array.prototype.forEach.call(host.querySelectorAll('[data-evf-enhance="inventory"]'), function (el) { if (root.GWInventory) root.GWInventory.enhance(el, opts); });   // enganche del widget de inventario (gw-inventory.js)
    var countries = host.querySelectorAll('[data-evf-enhance="country"]'), cities = host.querySelectorAll('[data-evf-enhance="city"]');
    return loadGeo(opts.geoUrl).then(function (ok) {
      if (!ok) { Array.prototype.forEach.call(countries, function (c) { cityDeps(host, c.dataset.evfKey, c.value, opts); }); return false; }
      Array.prototype.forEach.call(countries, enhanceCountry);
      Array.prototype.forEach.call(cities, function (c) {
        var ck = c.dataset.evfCountry, ci = ck ? host.querySelector('[data-evf-key="' + ck + '"][data-evf-part="v"]') : null;
        enhanceCity(c, ci);
      });
      return true;
    });
  }

  var api = { renderField: renderField, readField: readField, validateValue: validateValue, formatValue: formatValue, valueOf: valueOf, displayValue: displayValue, calendarLayout: calendarLayout, cardModel: cardModel, bind: bind, afterMount: afterMount, geoPair: geoPair, loadGeo: loadGeo, customFields: customFields, workdayText: workdayText, bindWorkday: bindWorkday, diffExtra: diffExtra, sameValue: sameValue, _geo: { codeOf: codeOf, citiesFor: citiesFor, state: geoState }, esc: esc, inventoryRow: inventoryRow };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
  root.EventFields = api;
})(typeof window !== 'undefined' ? window : globalThis);
