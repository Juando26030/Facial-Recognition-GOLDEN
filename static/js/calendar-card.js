/* Tarjeta del evento en el Calendario (Fase 2, entrega 1).
   Archivo AISLADO: no toca el DOM ni la red; solo convierte un evento en HTML. Otro agente construirá el diseñador de plantilla («Vista de calendario»)
   que producirá el `layout`; mientras tanto se usa DEFAULT_LAYOUT.

   CONTRATO — renderCalendarCard(event, layout) -> string (HTML ya escapado, listo para ponerse dentro de un <button> o <div>)

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
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else { root.renderCalendarCard = api.renderCalendarCard; root.CalendarCard = api; }
})(typeof window !== 'undefined' ? window : this, function () {
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

  function renderCalendarCard(event, layout) {
    var ev = event || {};
    var fields = (validLayout(layout) ? layout : DEFAULT_LAYOUT).fields;
    var out = { left: '', right: '', bottom: '' };
    fields.forEach(function (spec) {
      if (!spec || !Object.prototype.hasOwnProperty.call(FIELD_CATALOG, spec.key)) return;
      var zone = ZONES.indexOf(spec.zone) >= 0 ? spec.zone : 'left';
      out[zone] += fieldHtml(FIELD_CATALOG[spec.key], spec, ev);
    });
    var cols = (out.left ? '<span class="cal-card__col cal-card__col--left">' + out.left + '</span>' : '') +
      (out.right ? '<span class="cal-card__col cal-card__col--right">' + out.right + '</span>' : '');
    return '<span class="cal-card">' + (cols ? '<span class="cal-card__cols">' + cols + '</span>' : '') +
      (out.bottom ? '<span class="cal-card__bottom">' + out.bottom + '</span>' : '') + '</span>';
  }

  return { renderCalendarCard: renderCalendarCard, DEFAULT_LAYOUT: DEFAULT_LAYOUT, FIELD_CATALOG: FIELD_CATALOG, ZONES: ZONES };
});
