/* Tarjeta del evento en el Calendario (Fase 2, entrega 1).
   Archivo AISLADO: no toca el DOM ni la red; solo convierte un evento en HTML. Otro agente construirá el diseñador de plantilla («Vista de calendario»)
   que producirá el `layout`; mientras tanto se usa DEFAULT_LAYOUT.

   CONTRATO ÚNICO (Fase 2, enlace): el `layout` que pinta la tarjeta es el que produce la PLANTILLA DE EVENTO:
       const tpl = await (await fetch('/api/event-template')).json();
       const layout = EventFields.calendarLayout(tpl);      // {zones:{top,left,right,bottom}, fields:{clave:campo}, ctx, version}
       renderCalendarCard(event, layout)                    // event = elemento de /api/events/calendar (trae `extra`, `switches`)
   Con ese layout el modelo lo arma EventFields.cardModel (static/js/event-field-render.js; campos base Y personalizados: texto, dinero COP, fechas, comercial, coordinador, país/ciudad, contacto,
   pañoletas, interruptores como insignias «Sí/No», inventario resumido) y aquí solo se DIBUJA: top = encabezado a todo el ancho (el primero grande), left/right = dos columnas, bottom = franja inferior.
   Los campos retirados o sin valor no se pintan; todo texto sale escapado. La forma antigua `{fields:[{key,zone,label}]}` (FIELD_CATALOG, más abajo) queda SOLO como respaldo: es lo que se usa cuando
   la plantilla no se pudo cargar (layout null) para que el calendario nunca se quede sin tarjeta.

   Forma de respaldo — renderCalendarCard(event, layout) -> string (HTML ya escapado, listo para ponerse dentro de un <button> o <div>)

   event   El mismo objeto que entrega GET /api/events/calendar (app/routers/events.py `_serialize`): id, event_code, name, tenant_name, location, city, address,
           country, status, start_date / end_date / setup_date (ISO aaaa-mm-dd), event_time_start / event_time_end, setup_time_start / setup_time_end,
           commercial_name, coordinator_name, bandana_color_name, notes.
   layout  { fields: [ { key, zone, label } , ... ] }   (null/inválido -> DEFAULT_LAYOUT)
             key    Uno de FIELD_CATALOG (ver abajo). Una clave desconocida se ignora sin error (así una plantilla guardada con campos nuevos no rompe el calendario).
             zone   'left' | 'right' | 'bottom'   (izquierda, derecha, abajo a todo el ancho). Cualquier otro valor cae en 'left'.
             label  true (por defecto: muestra el título del catálogo) | false (solo el valor) | 'texto' (título propio).
           El orden dentro de cada zona es el orden del arreglo. Un campo sin valor en ese evento NO se pinta (ni su título).
   Claves del catálogo: name, event_code, tenant_name, place (lugar · ciudad), address, country, dates (inicio – fin), setup_date, times (horario del evento),
           setup_times, status, commercial_name, coordinator_name, bandana_color_name, notes.
   Salida  <span class="cal-card"> <span class="cal-card__cols"> <span class="cal-card__col cal-card__col--left">…</span> <span class="cal-card__col cal-card__col--right">…</span> </span>
           <span class="cal-card__bottom">…</span> </span>   (solo clases .cal-card* de static/css/p-calendario.css; sin estilos en línea).
   Un día con un solo evento deja espacio: la tarjeta puede ser larga, por eso ninguna zona recorta texto. */
(function (root, factory) {
  var api = factory(root);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else { root.renderCalendarCard = api.renderCalendarCard; root.renderCalendarMini = api.renderCalendarMini; root.CalendarCard = api; }
})(typeof window !== 'undefined' ? window : this, function (root) {
  'use strict';

  var STATUS_LABELS = { creado: 'Creado', en_proceso: 'En Proceso', finalizado: 'Finalizado' };
  var ZONES = ['left', 'right', 'bottom'];

  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]; }); }
  function fmtDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? m[3] + '/' + m[2] + '/' + m[1] : '';
  }
  function range(a, b, sep) {
    var x = a || '', y = b || '';
    if (x && y && x !== y) return x + sep + y;
    return x || y;
  }

  /* Cada campo: título por defecto, valor (texto plano; se escapa al pintar) y si va resaltado. */
  var FIELD_CATALOG = {
    name: { label: 'Evento', strong: true, value: function (e) { return e.name; } },
    event_code: { label: 'Código', value: function (e) { return e.event_code; } },
    tenant_name: { label: 'Cliente', value: function (e) { return e.tenant_name; } },
    place: { label: 'Lugar', value: function (e) { return [e.location, e.city].filter(Boolean).join(' · '); } },
    address: { label: 'Dirección', value: function (e) { return e.address; } },
    country: { label: 'País', value: function (e) { return e.country; } },
    dates: { label: 'Fechas', value: function (e) { return range(fmtDate(e.start_date), fmtDate(e.end_date), ' – '); } },
    setup_date: { label: 'Montaje', value: function (e) { return fmtDate(e.setup_date); } },
    times: { label: 'Horario', value: function (e) { return range(e.event_time_start, e.event_time_end, ' – '); } },
    setup_times: { label: 'Horario de montaje', value: function (e) { return range(e.setup_time_start, e.setup_time_end, ' – '); } },
    status: { label: 'Estado', value: function (e) { return STATUS_LABELS[e.status] || e.status; } },
    commercial_name: { label: 'Comercial', value: function (e) { return e.commercial_name; } },
    coordinator_name: { label: 'Coordinador', value: function (e) { return e.coordinator_name; } },
    bandana_color_name: { label: 'Pañoleta', value: function (e) { return e.bandana_color_name; } },
    notes: { label: 'Notas', value: function (e) { return e.notes; } }
  };

  /* Por defecto: lo que el evento ya tiene hoy, ordenado en dos columnas y una franja de equipo abajo. */
  var DEFAULT_LAYOUT = {
    fields: [
      { key: 'name', zone: 'left', label: false },
      { key: 'event_code', zone: 'left' },
      { key: 'tenant_name', zone: 'left' },
      { key: 'place', zone: 'left' },
      { key: 'dates', zone: 'right' },
      { key: 'times', zone: 'right' },
      { key: 'status', zone: 'right' },
      { key: 'commercial_name', zone: 'bottom' },
      { key: 'coordinator_name', zone: 'bottom' },
      { key: 'bandana_color_name', zone: 'bottom' }
    ]
  };

  function validLayout(layout) { return !!layout && Array.isArray(layout.fields); }

  function fieldHtml(def, spec, event) {
    var value = def.value(event);
    if (value == null || String(value).trim() === '') return '';
    var showLabel = spec.label !== false;
    var label = typeof spec.label === 'string' && spec.label ? spec.label : def.label;
    return '<span class="cal-card__f' + (def.strong ? ' cal-card__f--strong' : '') + '">' +
      (showLabel ? '<span class="cal-card__k">' + esc(label) + '</span> ' : '') +
      '<span class="cal-card__v">' + esc(value) + '</span></span>';
  }

  /* Resuelve EventFields (navegador: global; node: el módulo hermano). */
  function fieldsApi() {
    if (root && root.EventFields) return root.EventFields;
    try { return require('./event-field-render.js'); } catch (e) { return null; }
  }

  /* «Revisar el detalle» (0143): triángulo rojo con «!» si la comercial lo marcó; sin marca no sale nada. Va en el encabezado de la tarjeta y en la mini del mes (sin importar la zona de la plantilla). */
  function reviewHtml(ev) {
    if (!ev || !ev.review_detail) return '';
    return '<span class="cal-card__review" role="img" aria-label="Revisar el detalle del evento" title="Revisar el detalle del evento">' +
      '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path d="M12 2.5 22.5 21h-21z" fill="currentColor"/><path d="M12 9v5.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/><circle cx="12" cy="17.6" r="1.3" fill="#fff"/></svg></span>';
  }

  function itemHtml(it, strong) {
    if (it.key === 'sw_review_detail') return '';          // ya se pinta como triángulo en el encabezado
    if (it.type === 'switch') {          // interruptor: píldora con ícono donde el nombre y la respuesta van JUNTOS («✓ Impresión compartida: Sí»), para que un Sí/No nunca parezca de otro campo
      var on = it.text === 'Sí';
      return '<span class="cal-card__f cal-card__sw-row cal-card__sw-row--' + (on ? 'on' : 'off') + '" data-field="' + esc(it.key) + '">' +
        '<span class="cal-card__sw-ic" aria-hidden="true">' + (on ? '✓' : '✕') + '</span>' +
        '<span class="cal-card__sw-tx">' + esc(it.title) + ': <strong class="cal-card__sw-st">' + esc(it.text) + '</strong></span></span>';
    }
    if (it.type === 'workday') {          // jornada (Fase 5): insignia informativa; con «mostrar el nombre del campo» lleva su título delante
      return '<span class="cal-card__f cal-card__wd" data-field="' + esc(it.key) + '">' + (it.label ? '<span class="cal-card__k">' + esc(it.title) + '</span> ' : '') +
        '<span class="gw-badge gw-badge--info cal-card__wd-b">' + esc(it.text) + '</span></span>';
    }
    var cls = 'cal-card__f' + (strong ? ' cal-card__f--strong' : '') + (it.type === 'text_long' ? ' cal-card__f--long' : '');
    return '<span class="' + cls + '" data-field="' + esc(it.key) + '">' +
      (it.label ? '<span class="cal-card__k">' + esc(it.title) + '</span> ' : '') + '<span class="cal-card__v">' + esc(it.text) + '</span></span>';
  }
  /* Dibuja el modelo de EventFields.cardModel: {top,left,right,bottom: [{key,type,title,label,text}]}. `extraTop` = HTML ya escapado que se agrega al encabezado (p. ej. el estado). */
  function renderCardModel(model, extraTop, root_ev) {
    var m = model || {};
    function zone(z) { return (m[z] || []).map(function (it, i) { return itemHtml(it, z === 'top' && i === 0); }).join(''); }
    var top = zone('top') + (extraTop || ''), left = zone('left'), right = zone('right'), bottom = zone('bottom');
    var cols = (left ? '<span class="cal-card__col cal-card__col--left">' + left + '</span>' : '') +
      (right ? '<span class="cal-card__col cal-card__col--right">' + right + '</span>' : '');
    return '<span class="cal-card cal-card--tpl"><span class="cal-card__head">' + swatchesHtml(root_ev) + reviewHtml(root_ev) + (top ? '<span class="cal-card__top">' + top + '</span>' : '') + '</span>' +
      (cols ? '<span class="cal-card__cols">' + cols + '</span>' : '') + (bottom ? '<span class="cal-card__bottom">' + bottom + '</span>' : '') + '</span>';
  }
  /* Recuadros grandes con el color de la pañoleta (uno por color). El color va en data-bandana y lo aplica la página por DOM (no hay estilos en línea). Sin color: recuadro punteado vacío. */
  function swatchesHtml(ev, omitEmpty) {
    var list = (ev && ev.bandana_colors && ev.bandana_colors.length) ? ev.bandana_colors : (ev && ev.bandana_color ? [{ hex: ev.bandana_color, name: ev.bandana_color_name }] : []);
    if (!list.length && omitEmpty) return '';
    if (!list.length) return '<span class="cal-card__swatches" aria-hidden="true"><span class="cal-card__sw cal-card__sw--empty" title="Sin color de pañoleta"></span></span>';
    return '<span class="cal-card__swatches">' + list.map(function (c) {
      var nm = c.name || c.hex || '';
      return '<span class="cal-card__sw" data-bandana="' + esc(c.hex) + '" title="Pañoleta: ' + esc(nm) + '" role="img" aria-label="Color de pañoleta: ' + esc(nm) + '"></span>';
    }).join('') + '</span>';
  }
  /* El estado no es un campo de la plantilla, pero en el calendario siempre se necesita: va como insignia al final del encabezado. */
  function statusBadge(ev) {
    var t = ev.state_name || STATUS_LABELS[ev.status] || '';
    return t ? '<span class="gw-badge cal-card__status" data-field="status">' + esc(t) + '</span>' : '';
  }

  /* Línea resumida (calendario plegado): recuadro(s) de color de pañoleta + nombre + código. Todo escapado. */
  function renderCalendarMini(event) {
    var ev = event || {};
    return '<span class="cal-mini">' + swatchesHtml(ev) + reviewHtml(ev) + '<span class="cal-mini__name">' + esc(ev.name) + '</span>' +
      (ev.event_code ? '<span class="cal-mini__code">' + esc(ev.event_code) + '</span>' : '') + '</span>';
  }

  function renderCalendarCard(event, layout) {
    var ev = event || {};
    if (layout && layout.zones && layout.fields && !Array.isArray(layout.fields)) {
      var api = fieldsApi();
      if (api && typeof api.cardModel === 'function') {
        try { return renderCardModel(api.cardModel(ev, layout), statusBadge(ev), ev); } catch (e) { /* plantilla rara: cae al respaldo */ }
      }
      layout = null;
    }
    var fields = (validLayout(layout) ? layout : DEFAULT_LAYOUT).fields;
    var out = { left: '', right: '', bottom: '' };
    fields.forEach(function (spec) {
      if (!spec || !Object.prototype.hasOwnProperty.call(FIELD_CATALOG, spec.key)) return;
      var zone = ZONES.indexOf(spec.zone) >= 0 ? spec.zone : 'left';
      out[zone] += fieldHtml(FIELD_CATALOG[spec.key], spec, ev);
    });
    var cols = (out.left ? '<span class="cal-card__col cal-card__col--left">' + out.left + '</span>' : '') +
      (out.right ? '<span class="cal-card__col cal-card__col--right">' + out.right + '</span>' : '');
    return '<span class="cal-card">' + ((swatchesHtml(ev, true) || reviewHtml(ev)) ? '<span class="cal-card__head">' + swatchesHtml(ev, true) + reviewHtml(ev) + '</span>' : '') + (cols ? '<span class="cal-card__cols">' + cols + '</span>' : '') +
      (out.bottom ? '<span class="cal-card__bottom">' + out.bottom + '</span>' : '') + '</span>';
  }

  return { renderCalendarCard: renderCalendarCard, renderCalendarMini: renderCalendarMini, renderCardModel: renderCardModel, swatchesHtml: swatchesHtml, DEFAULT_LAYOUT: DEFAULT_LAYOUT, FIELD_CATALOG: FIELD_CATALOG, ZONES: ZONES };
});
