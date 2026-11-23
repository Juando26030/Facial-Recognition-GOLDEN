/* Grupo «Tipo de evento» (chips) COMPARTIDO por el Calendario y por Inventario › Dónde está cada equipo: misma apariencia en las dos pantallas.
   window.CalendarCatsUI.paint(host, cats, anyActive) pinta el título, el chip «Todos» (activo cuando no hay ninguno elegido) y un chip por tipo con su conteo.
   Clic en un tipo -> botón con data-cat; clic en «Todos» -> botón con data-cat-all. Quien lo usa delega el clic en `host` (la lógica de elegir está en calendar-cats.js). */
(function (root) {
  'use strict';
  var esc = function (t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var HEX = /^#[0-9a-fA-F]{6}$/;
  function paint(host, cats, anyActive, opts) {
    var title = (opts && opts.title) || 'Tipo de evento', aria = (opts && opts.aria) || 'Filtrar por tipo de evento';
    host.hidden = false;
    host.innerHTML = '<span class="gw-label cal-cats__title">' + esc(title) + '</span><div class="cal-cats__list" role="group" aria-label="' + esc(aria) + '">' +
      '<button type="button" class="gw-chip cal-cat" data-cat-all aria-pressed="' + (anyActive ? 'false' : 'true') + '"><span class="cal-cat__name">Todos</span></button>' +
      cats.map(function (c) {
        return '<button type="button" class="gw-chip cal-cat" data-cat="' + esc(c.key) + '" aria-pressed="' + (c.active ? 'true' : 'false') + '">' +
          (HEX.test(c.color || '') ? '<span class="cal-cat__dot" data-color="' + esc(c.color) + '" aria-hidden="true"></span>' : '') +
          '<span class="cal-cat__name">' + esc(c.label) + '</span><span class="cal-cat__n">' + c.count + '</span></button>';
      }).join('') + '</div>';
    host.querySelectorAll('.cal-cat__dot[data-color]').forEach(function (d) { d.style.backgroundColor = d.dataset.color; });          // por JS (la política CSP no admite style="" en el HTML)
  }
  /* Los tipos vigentes (para mostrarlos aunque hoy no tengan eventos). Si la cuenta no puede leerlos, queda en null y solo salen los que traen los eventos. */
  function loadCatalog() {
    return fetch('/api/event-types', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) { return d && d.types ? d.types : null; }).catch(function () { return null; });
  }
  root.CalendarCatsUI = { paint: paint, loadCatalog: loadCatalog };
})(window);
