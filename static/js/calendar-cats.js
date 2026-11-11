/* Filtros clicables de categorías de evento del Calendario (Fase 10, bloque C). Lógica PURA (sin DOM): corre en el navegador (window.CalendarCats) y en Node (tests/js/calendar_cats_check.js).
   La «categoría» de un evento es su TIPO DE EVENTO (Feria, Congreso…: la lista que el super_admin administra en Configuración › Tipos de evento y que se elige al crear o editar el evento).
   Un evento sin tipo cae en «Sin categoría». Se ve igual para cualquiera que vea el calendario (no depende del rol). Varias categorías pueden estar activas a la vez; ninguna activa = se ven todas.

   categoryOf(evento)            -> { key, label, color }
   build(eventos, activas, conocidas, catalogo) -> [{ key, label, color, count, active }] (TODOS los tipos del catálogo y «Sin categoría» con su conteo, aunque sea 0, + los de eventos + las activas); «Sin categoría» al final, el resto alfabético
   toggle(activas, key)          -> nuevo Set con la categoría puesta o quitada
   matches(evento, activas)      -> true si no hay ninguna activa o el evento es de una activa                                                                       */
(function () {
  var NONE = { key: 'none', label: 'Sin categoría', color: '' };

  function categoryOf(e) {
    var ev = e || {};
    if (ev.event_type_id != null && ev.event_type_name) return { key: 't' + ev.event_type_id, label: String(ev.event_type_name), color: ev.event_type_color || '' };
    return { key: NONE.key, label: NONE.label, color: NONE.color };
  }

  function build(events, active, known, catalog) {
    var on = active || new Set(), map = {};
    (catalog || []).forEach(function (t) { map['t' + t.id] = { key: 't' + t.id, label: String(t.name), color: t.color || '', count: 0, active: on.has('t' + t.id) }; });          // los tipos vigentes salen SIEMPRE, aunque hoy tengan 0 eventos
    map[NONE.key] = { key: NONE.key, label: NONE.label, color: NONE.color, count: 0, active: on.has(NONE.key) };          // «Sin categoría» también
    (events || []).forEach(function (e) {
      var c = categoryOf(e);
      if (!map[c.key]) map[c.key] = { key: c.key, label: c.label, color: c.color, count: 0, active: on.has(c.key) };          // un tipo archivado que un evento aún tiene
      map[c.key].count += 1;
    });
    on.forEach(function (key) {          // una activa que hoy no tiene eventos sigue visible (para poder quitarla); `known` = {clave: {label, color}} de lo ya visto en otros periodos
      if (map[key]) return;
      var k = (known && known[key]) || {};
      map[key] = { key: key, label: key === NONE.key ? NONE.label : (k.label || 'Categoría'), color: k.color || '', count: 0, active: true };
    });
    return Object.keys(map).map(function (k) { return map[k]; }).sort(function (a, b) {
      if (a.key === NONE.key || b.key === NONE.key) return a.key === NONE.key ? 1 : -1;
      return a.label.localeCompare(b.label, 'es');
    });
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
