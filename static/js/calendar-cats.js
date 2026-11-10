/* Filtros clicables de categorías de evento del Calendario (Fase 10, bloque C). Lógica PURA (sin DOM): corre en el navegador (window.CalendarCats) y en Node (tests/js/calendar_cats_check.js).
   La «categoría» de un evento es su ESTADO (los que el equipo define en Configuración › Estados de evento, con su color; si el evento no tiene uno propio, Creado / En proceso / Finalizado).
   Se ve igual para cualquiera que vea el calendario (no depende del rol). Varias categorías pueden estar activas a la vez; ninguna activa = se ven todas.

   categoryOf(evento)            -> { key, label, color }
   build(eventos, activas)       -> [{ key, label, color, count, active }] (las que hay en el periodo + las activas aunque hoy no tengan eventos), en orden alfabético
   toggle(activas, key)          -> nuevo Set con la categoría puesta o quitada
   matches(evento, activas)      -> true si no hay ninguna activa o el evento es de una activa                                                                       */
(function () {
  var STATUS_LABELS = { creado: 'Creado', en_proceso: 'En proceso', finalizado: 'Finalizado' };

  function categoryOf(e) {
    var ev = e || {};
    if (ev.state_id != null && ev.state_name) return { key: 's' + ev.state_id, label: String(ev.state_name), color: ev.state_color || '' };
    return { key: 'st:' + (ev.status || ''), label: STATUS_LABELS[ev.status] || String(ev.status || 'Sin categoría'), color: '' };
  }

  function build(events, active) {
    var on = active || new Set(), map = {};
    (events || []).forEach(function (e) {
      var c = categoryOf(e);
      if (!map[c.key]) map[c.key] = { key: c.key, label: c.label, color: c.color, count: 0, active: on.has(c.key) };
      map[c.key].count += 1;
    });
    on.forEach(function (key) { if (!map[key]) map[key] = { key: key, label: key.indexOf('st:') === 0 ? (STATUS_LABELS[key.slice(3)] || key.slice(3)) : key, color: '', count: 0, active: true }; });
    return Object.keys(map).map(function (k) { return map[k]; }).sort(function (a, b) { return a.label.localeCompare(b.label, 'es'); });
  }

  function toggle(active, key) {
    var next = new Set(active || []);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  }

  function matches(e, active) { return !active || !active.size || active.has(categoryOf(e).key); }

  var api = { categoryOf: categoryOf, build: build, toggle: toggle, matches: matches };
  if (typeof window !== 'undefined') window.CalendarCats = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
