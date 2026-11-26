/* Estadísticas del evento — lo principal de Control de inventario y Control de zonas (rediseño 26-nov-2026).
   Recibe `data.control` del tablero del registro (app/stats_control.py, misma respuesta y mismo refresco de 30 s) y lo dibuja debajo de las cifras del registro:
     - Inventario: unidades entregadas, personas atendidas y lo que queda, en grande; luego, por cada producto, «X de Y entregadas · quedan Z» con una barra cuyo
       porcentaje es lo entregado sobre lo que había de ESE producto.
     - Zonas: personas que entraron, adentro ahora y entradas; por zona, personas únicas sobre los registrados.
   Cada sección se oculta si el módulo no está activo en el evento. Solo cifras: nada de datos de personas. Sin estilos sueltos: clases .gw-sc-* (gw-estadisticas.css). */
(function () {
  'use strict';
  var ICONS = '';
  var esc = function (t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var n = function (v) { return Number(v || 0).toLocaleString('es-CO'); };
  function pctText(p) {
    if (p == null) return '';
    var v = Number(p);
    return (v > 0 && v < 10 && v % 1 ? v.toLocaleString('es-CO', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : Math.round(v).toLocaleString('es-CO')) + '%';
  }
  function icon(name) { return '<svg class="gw-icon gw-stat__icon" aria-hidden="true"><use href="' + esc(ICONS) + '#i-' + name + '"/></svg>'; }
  function stat(ic, value, label, hint, tone) {
    return '<div class="gw-stat' + (tone ? ' gw-stat--' + tone : '') + '">' + icon(ic) + '<div class="gw-stat__value">' + esc(value) + '</div><div class="gw-stat__label">' + esc(label) + '</div>' + (hint ? '<div class="gw-stat__hint">' + esc(hint) + '</div>' : '') + '</div>';
  }
  /* Una fila con barra: nombre y porcentaje arriba, la barra (ancho = porcentaje, tope 100) y el detalle en texto debajo. */
  function bar(name, p, meta, sub) {
    var w = p == null ? 0 : Math.max(0, Math.min(100, Number(p)));
    return '<li class="gw-sc-row' + (sub ? ' gw-sc-row--sub' : '') + '"><div class="gw-sc-row__head"><span class="gw-sc-row__name">' + esc(name) + '</span>'
      + '<span class="gw-sc-row__pct">' + esc(p == null ? '—' : pctText(p)) + '</span></div>'
      + '<div class="gw-sc-bar" role="progressbar" aria-label="' + esc(name) + '" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round(w) + '"><span class="gw-sc-bar__fill" data-w="' + w + '"></span></div>'
      + '<div class="gw-sc-row__meta">' + meta + '</div></li>';
  }
  function itemMeta(r) {
    if (!r.initial) return '<b>' + n(r.delivered) + '</b> entregada(s) · sin cantidad cargada en el inventario';
    return '<b>' + n(r.delivered) + '</b> de ' + n(r.initial) + ' entregada(s) · quedan <b>' + n(r.remaining) + '</b>' + (r.people != null ? ' · ' + n(r.people) + ' persona(s)' : '');
  }

  function inventoryHtml(inv) {
    var h = '<div class="gw-stats-row">'
      + stat('inbox', n(inv.units), 'Unidades entregadas', inv.initial ? 'de ' + n(inv.initial) + ' en el inventario' : '', 'ok')
      + stat('users', n(inv.people), 'Personas atendidas', 'recibieron al menos una cosa')
      + stat('chart', n(inv.remaining), 'Quedan en el inventario', 'unidades disponibles', inv.initial && inv.remaining <= 0 ? 'err' : '')
      + '</div>';
    (inv.groups || []).forEach(function (g) {
      h += '<div class="gw-sc-group"><h3 class="gw-sc-group__title">' + esc(g.name) + '</h3>'
        + '<p class="gw-sc-group__sum"><b>' + n(g.units) + '</b> unidad(es) entregada(s) · <b>' + n(g.people) + '</b> persona(s) atendida(s)'
        + (g.initial ? ' · quedan <b>' + n(g.remaining) + '</b> de ' + n(g.initial) + (g.pct != null ? ' (' + pctText(g.pct) + ' entregado)' : '') : '') + '</p>'
        + (g.items && g.items.length ? '<ul class="gw-sc-list">' + g.items.map(function (r) { return bar(r.name, r.pct, itemMeta(r)); }).join('') + '</ul>' : '')
        + '</div>';
    });
    if (inv.items && inv.items.length) {
      h += '<div class="gw-sc-group">' + (inv.groups && inv.groups.length ? '<h3 class="gw-sc-group__title">Otros productos</h3>' : '')
        + '<ul class="gw-sc-list">' + inv.items.map(function (r) { return bar(r.name, r.pct, itemMeta(r)); }).join('') + '</ul></div>';
    }
    return h;
  }

  function zoneMeta(z, registered) {
    return '<b>' + n(z.people) + '</b> persona(s)' + (registered ? ' de ' + n(registered) + ' registrada(s)' : '') + ' · adentro ahora <b>' + n(z.inside) + '</b> · ' + n(z.entries) + ' entrada(s) · ' + n(z.exits) + ' salida(s)';
  }
  function zonesHtml(zs) {
    var h = '<div class="gw-stats-row">'
      + stat('arrow-in', n(zs.people), 'Personas que entraron', zs.registered ? pctText(zs.pct) + ' de los registrados' : 'aún no hay registrados', 'ok')
      + stat('users', n(zs.inside), 'Adentro ahora', 'su última marca es una entrada')
      + stat('arrow-out', n(zs.entries), 'Entradas', n(zs.exits) + ' salida(s)')
      + '</div><ul class="gw-sc-list">';
    (zs.zones || []).forEach(function (z) {
      h += bar(z.name, z.pct, zoneMeta(z, zs.registered));
      (z.children || []).forEach(function (c) { h += bar(c.name, c.pct, zoneMeta(c, zs.registered), true); });
    });
    return h + '</ul>';
  }

  function fill(section, html) {
    var body = section.querySelector('[data-sc-body]');
    body.innerHTML = html;
    Array.prototype.forEach.call(body.querySelectorAll('.gw-sc-bar__fill'), function (el) { el.style.width = el.getAttribute('data-w') + '%'; });          // ancho calculado con los datos
  }

  function render(data) {
    var c = (data && data.control) || {};
    var inv = document.getElementById('statsInv'), zones = document.getElementById('statsZones');
    if (inv) { inv.hidden = !c.inventory; if (c.inventory) fill(inv, inventoryHtml(c.inventory)); }
    if (zones) { zones.hidden = !c.zones; if (c.zones) fill(zones, zonesHtml(c.zones)); }
  }

  window.GWStatsControl = { render: render, setIcons: function (url) { ICONS = url || ''; }, _pctText: pctText, _inventoryHtml: inventoryHtml, _zonesHtml: zonesHtml };
})();
