/* Jornada del evento (Fase 5): espejo en el navegador de app/workday.py. Mismos límites y mismas reglas; lo fija tests/js/workday_check.js y el servidor es quien manda.
   La jornada es INFORMATIVA: se calcula de la hora de inicio y la de fin del evento (duración del día de trabajo; si el fin es menor que el inicio cruza la medianoche; sin horas o con inicio = fin: sin jornada).
   Límites (tope superior INCLUSIVO): <= 6 h Media jornada · <= 9 h Jornada intermedia · <= 12 h Jornada completa · más de 12 h Jornada extendida.
   Workday.compute(inicio, fin) -> null | {key, label, hours, hours_text} · Workday.text(inicio, fin) -> «Jornada completa · 10 h» o '' · Workday.TIERS · Workday.NO_VALUE ('—'). */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Workday = api;
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';
  var TIERS = [
    { key: 'media', max: 6, label: 'Media jornada' },
    { key: 'intermedia', max: 9, label: 'Jornada intermedia (entre media y completa)' },
    { key: 'completa', max: 12, label: 'Jornada completa' },
    { key: 'extendida', max: null, label: 'Jornada extendida' }
  ];
  var NO_VALUE = '—';
  var TIME_RE = /^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$/;

  function minutes(v) {
    var m = TIME_RE.exec(String(v == null ? '' : v));
    if (!m) return null;
    var h = +m[1], mi = +m[2];
    return h > 23 || mi > 59 ? null : h * 60 + mi;
  }
  function classify(hours) {
    for (var i = 0; i < TIERS.length; i++) if (TIERS[i].max == null || hours <= TIERS[i].max) return TIERS[i];
    return TIERS[TIERS.length - 1];
  }
  function hoursText(hours) {
    var r = Math.round(hours * 100) / 100;
    return (r === Math.floor(r) ? String(r) : r.toFixed(2).replace(/0+$/, '').replace('.', ',')) + ' h';
  }
  function compute(start, end) {
    var a = minutes(start), b = minutes(end);
    if (a == null || b == null || a === b) return null;
    var mins = (((b - a) % 1440) + 1440) % 1440, hours = mins / 60, tier = classify(hours);
    return { key: tier.key, label: tier.label, hours: Math.round(hours * 100) / 100, hours_text: hoursText(hours) };
  }
  function text(start, end) {
    var w = compute(start, end);
    return w ? w.label + ' · ' + w.hours_text : '';
  }
  return { compute: compute, text: text, TIERS: TIERS, NO_VALUE: NO_VALUE, minutes: minutes };
});
