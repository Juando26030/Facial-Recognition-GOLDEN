/* Panel de gastos — pestaña «Eventos» (Fase 9 D): satisfacción de los clientes y tiempos de cierre/facturación. Solo administradores (la API lo exige).
   Gráficos SVG propios, sin librerías ni costo. Todo texto que viene del servidor entra con textContent (nunca innerHTML): los comentarios son texto libre del cliente. */
(function () {
  'use strict';
  var root = document.getElementById('gw-gastos-eventos');
  if (!root) return;
  var API = root.getAttribute('data-api') || '/api/gastos/eventos';
  var SVGNS = 'http://www.w3.org/2000/svg';
  var form = document.getElementById('gw-ge-filters');
  var timer = null;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function svg(tag, attrs, text) {
    var n = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function num(v, d) { return v == null ? '—' : (Math.round(v * Math.pow(10, d == null ? 1 : d)) / Math.pow(10, d == null ? 1 : d)).toString().replace('.', ','); }
  function empty(node, msg) { clear(node).appendChild(el('p', 'gw-ge__empty', msg || 'Sin datos en este periodo.')); }
  function toast(msg, type) { if (window.showToast) window.showToast(msg, type || 'error'); }

  /* ---------- tablas ---------- */
  function table(node, cols, rows, linkFn) {
    clear(node);
    if (!rows || !rows.length) return empty(node);
    var wrap = el('div', 'gw-table-wrap gw-scroll-x'), t = el('table', 'gw-table'), head = el('tr');
    cols.forEach(function (c) { var th = el('th', null, c.h); th.scope = 'col'; head.appendChild(th); });
    var thead = el('thead'); thead.appendChild(head); t.appendChild(thead);
    var tb = el('tbody');
    rows.forEach(function (r) {
      var tr = el('tr');
      cols.forEach(function (c) {
        var td = el('td'), v = c.v(r);
        if (c.link && linkFn) { var a = el('a', null, v == null ? '—' : String(v)); a.href = linkFn(r); td.appendChild(a); } else td.textContent = v == null ? '—' : String(v);
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb); wrap.appendChild(t); node.appendChild(wrap);
  }
  function eventLink(r) { return '/kiosk/' + encodeURIComponent(r.event_id); }

  /* ---------- gráficos ---------- */
  function hbars(node, items, max, fmt) {
    /* items: [{label, value, cls}] — barras horizontales */
    clear(node);
    if (!items.length) return empty(node);
    var rowH = 30, left = 230, w = 640, h = items.length * rowH + 8;
    var s = svg('svg', { viewBox: '0 0 ' + w + ' ' + h, class: 'gw-ge__svg', role: 'img', 'aria-label': 'Gráfico de barras' });
    items.forEach(function (it, i) {
      var y = i * rowH + 4, bw = it.value == null ? 0 : Math.max(2, (w - left - 60) * it.value / max);
      s.appendChild(svg('text', { x: left - 8, y: y + 17, 'text-anchor': 'end' }, it.label.length > 34 ? it.label.slice(0, 33) + '…' : it.label));
      var bar = svg('rect', { x: left, y: y + 3, width: bw, height: rowH - 10, rx: 4, class: 'gw-ge__bar ' + (it.cls || '') });
      bar.appendChild(svg('title', {}, it.label + ': ' + (fmt ? fmt(it.value) : num(it.value, 2))));
      s.appendChild(bar);
      s.appendChild(svg('text', { x: left + bw + 6, y: y + 17 }, fmt ? fmt(it.value) : num(it.value, 2)));
    });
    node.appendChild(s);
  }
  function columns(node, labels, values, label) {
    /* columnas verticales (distribución 0..10) */
    clear(node);
    var w = 560, h = 220, pad = 28, max = Math.max.apply(null, values.concat([1]));
    if (!values.some(function (v) { return v > 0; })) return empty(node);
    var s = svg('svg', { viewBox: '0 0 ' + w + ' ' + h, class: 'gw-ge__svg', role: 'img', 'aria-label': label });
    var bw = (w - pad * 2) / values.length;
    s.appendChild(svg('line', { x1: pad, y1: h - pad, x2: w - pad, y2: h - pad, class: 'gw-ge__axis' }));
    values.forEach(function (v, i) {
      var bh = (h - pad * 2) * v / max, x = pad + i * bw + 4, cls = i <= 6 ? 'gw-ge__bar--bad' : (i <= 8 ? 'gw-ge__bar--good' : 'gw-ge__bar--excellent');
      var r = svg('rect', { x: x, y: h - pad - bh, width: bw - 8, height: bh, rx: 3, class: 'gw-ge__bar ' + cls });
      r.appendChild(svg('title', {}, labels[i] + ': ' + v));
      s.appendChild(r);
      s.appendChild(svg('text', { x: x + (bw - 8) / 2, y: h - 10, 'text-anchor': 'middle' }, labels[i]));
      if (v) s.appendChild(svg('text', { x: x + (bw - 8) / 2, y: h - pad - bh - 4, 'text-anchor': 'middle' }, String(v)));
    });
    node.appendChild(s);
  }
  function lines(node, months, series) {
    /* series: [{name, values:[...], max, cls}] — dos escalas relativas: cada línea se dibuja de 0 a su máximo, con el valor en cada punto */
    clear(node);
    if (!months.length) return empty(node);
    var w = 640, h = 240, padL = 36, padR = 16, padT = 16, padB = 36, step = months.length > 1 ? (w - padL - padR) / (months.length - 1) : 0;
    var legend = el('p', 'gw-ge__legend');
    series.forEach(function (sr) { legend.appendChild(el('span', null, (sr.cls ? '- - ' : '— ') + sr.name)); });
    node.appendChild(legend);
    var s = svg('svg', { viewBox: '0 0 ' + w + ' ' + h, class: 'gw-ge__svg', role: 'img', 'aria-label': 'Evolución mensual' });
    s.appendChild(svg('line', { x1: padL, y1: h - padB, x2: w - padR, y2: h - padB, class: 'gw-ge__axis' }));
    months.forEach(function (m, i) { s.appendChild(svg('text', { x: padL + (months.length > 1 ? i * step : (w - padL - padR) / 2), y: h - 14, 'text-anchor': 'middle', class: 'gw-ge__muted' }, m)); });
    series.forEach(function (sr) {
      var pts = [];
      sr.values.forEach(function (v, i) {
        if (v == null) return;
        var x = padL + (months.length > 1 ? i * step : (w - padL - padR) / 2), y = h - padB - (h - padB - padT) * (v - sr.min) / ((sr.max - sr.min) || 1);
        pts.push([x, y, v]);
      });
      if (pts.length > 1) s.appendChild(svg('polyline', { points: pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' '), class: 'gw-ge__line ' + (sr.cls || '') }));
      pts.forEach(function (p) {
        var c = svg('circle', { cx: p[0], cy: p[1], r: 4, class: 'gw-ge__dot' });
        c.appendChild(svg('title', {}, sr.name + ': ' + num(p[2], 2)));
        s.appendChild(c);
        s.appendChild(svg('text', { x: p[0], y: p[1] - 9, 'text-anchor': 'middle' }, num(p[2], sr.digits)));
      });
    });
    node.appendChild(s);
  }

  /* ---------- tarjetas y secciones ---------- */
  function kpi(label, value, sub, tone) {
    var d = el('div', 'gw-stat' + (tone ? ' gw-stat--' + tone : ''));
    d.appendChild(el('div', 'gw-sub', label));
    d.appendChild(el('div', 'gw-title', value));
    if (sub) d.appendChild(el('div', 'gw-hint', sub));
    return d;
  }
  function renderKpis(k) {
    var n = clear($('gw-ge-kpis')), v = k.nps.value;
    n.appendChild(kpi('NPS (recomendación)', v == null ? '—' : (v > 0 ? '+' : '') + v, k.nps.promoters + ' promotores · ' + k.nps.passives + ' neutros · ' + k.nps.detractors + ' detractores', v == null ? '' : (v >= 50 ? 'ok' : (v >= 0 ? 'warn' : 'err'))));
    n.appendChild(kpi('Calidad promedio', k.avg_quality == null ? '—' : num(k.avg_quality, 2) + ' / 3', k.responses + ' encuestas', k.avg_quality == null ? '' : (k.avg_quality >= 2.5 ? 'ok' : (k.avg_quality >= 2 ? 'warn' : 'err'))));
    n.appendChild(kpi('Tasa de respuesta', k.response_rate_pct == null ? '—' : num(k.response_rate_pct) + ' %', k.responses + ' de ' + k.eligible + ' eventos entregados'));
    n.appendChild(kpi('Quieren otro evento', k.next_event.pct_yes == null ? '—' : num(k.next_event.pct_yes) + ' %', k.next_event.yes + ' de ' + k.next_event.answered + ' · ya crearon uno: ' + k.converted.converted));
    n.appendChild(kpi('Facturar (mediana)', k.bill_median_days == null ? '—' : num(k.bill_median_days) + ' días', 'desde el fin del evento'));
    n.appendChild(kpi('Finalizar (mediana)', k.close_median_days == null ? '—' : num(k.close_median_days) + ' días', 'desde el fin del evento'));
  }
  function groupTable(id, rows) {
    table($(id), [{ h: 'Nombre', v: function (r) { return r.name; } }, { h: 'Eventos', v: function (r) { return r.events; } }, { h: 'Calidad (1-3)', v: function (r) { return num(r.avg, 2); } }, { h: 'NPS', v: function (r) { return r.nps; } }], rows);
  }
  function timeGroupTable(id, rows) {
    table($(id), [{ h: 'Nombre', v: function (r) { return r.name; } }, { h: 'Eventos', v: function (r) { return r.events; } },
      { h: 'Facturar: mediana', v: function (r) { return num(r.bill.median); } }, { h: 'Promedio', v: function (r) { return num(r.bill.mean); } }, { h: 'P90', v: function (r) { return num(r.bill.p90); } },
      { h: 'Finalizar: mediana', v: function (r) { return num(r.close.median); } }], rows);
  }
  function ranking(id, rows) {
    table($(id), [{ h: 'Evento', v: function (r) { return r.name; }, link: true }, { h: 'Cliente', v: function (r) { return r.client; } }, { h: 'Calidad', v: function (r) { return num(r.avg, 2); } }, { h: 'Recomienda', v: function (r) { return r.nps_score; } }], rows, eventLink);
  }

  function render(d) {
    $('gw-ge-summary').textContent = d.events_total ? d.summary_text : 'No hay eventos en este periodo. Cambie las fechas o los filtros.';
    renderKpis(d.kpis);
    var s = d.satisfaction, t = d.times, a = d.alerts;
    hbars($('gw-ge-questions'), s.questions.map(function (q) { return { label: q.label, value: q.avg }; }), 3, function (v) { return num(v, 2); });
    columns($('gw-ge-nps'), ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10'], s.nps_distribution, 'Distribución de la recomendación');
    var months = s.monthly.map(function (m) { return m.month; });
    lines($('gw-ge-monthly'), months, [{ name: 'Calidad (1-3)', values: s.monthly.map(function (m) { return m.avg; }), min: 1, max: 3, digits: 2 },
      { name: 'NPS (−100 a 100)', values: s.monthly.map(function (m) { return m.nps; }), min: -100, max: 100, digits: 0, cls: 'gw-ge__line--alt' }]);
    ranking('gw-ge-best', s.best); ranking('gw-ge-worst', s.worst);
    groupTable('gw-ge-by-commercial', s.by_commercial); groupTable('gw-ge-by-coordinator', s.by_coordinator); groupTable('gw-ge-by-client', s.by_client); groupTable('gw-ge-by-city', s.by_city);

    table($('gw-ge-low'), [{ h: 'Evento', v: function (r) { return r.name; }, link: true }, { h: 'Cliente', v: function (r) { return r.client; } }, { h: 'Calidad', v: function (r) { return num(r.avg, 2); } }, { h: 'Motivo', v: function (r) { return r.reason; } }], a.low_satisfaction, eventLink);
    table($('gw-ge-pending'), [{ h: 'Evento', v: function (r) { return r.name; }, link: true }, { h: 'Cliente', v: function (r) { return r.client; } }, { h: 'Días', v: function (r) { return r.days_waiting; } }, { h: 'Abrió el enlace', v: function (r) { return r.link_opened ? 'Sí' : 'No'; } }], a.pending_surveys, eventLink);
    table($('gw-ge-declining'), [{ h: 'Cliente', v: function (r) { return r.client; } }, { h: 'Antes', v: function (r) { return num(r.previous_avg, 2); } }, { h: 'Ahora', v: function (r) { return num(r.last_avg, 2); } }, { h: 'Cayó', v: function (r) { return num(r.drop, 2); } }], a.declining_clients);

    var sm = t.summary, rows = [['Fin del evento → Finalizado', sm.close_days], ['Fin del evento → base final subida', sm.base_days], ['Finalizado → Facturado', sm.bill_after_final_days], ['Fin del evento → Facturado', sm.bill_after_end_days]];
    table($('gw-ge-times'), [{ h: 'Etapa', v: function (r) { return r[0]; } }, { h: 'Eventos', v: function (r) { return r[1].n; } }, { h: 'Promedio', v: function (r) { return num(r[1].mean); } }, { h: 'Mediana', v: function (r) { return num(r[1].median); } }, { h: 'P90 (9 de cada 10 tardan menos de)', v: function (r) { return num(r[1].p90); } }], rows);
    var tm = t.monthly.map(function (m) { return m.month; });
    lines($('gw-ge-times-monthly'), tm, [{ name: 'Días a facturar (promedio)', values: t.monthly.map(function (m) { return m.bill.mean; }), min: 0, max: Math.max.apply(null, t.monthly.map(function (m) { return m.bill.mean || 0; }).concat([1])), digits: 1 },
      { name: 'Días a finalizar (promedio)', values: t.monthly.map(function (m) { return m.close.mean; }), min: 0, max: Math.max.apply(null, t.monthly.map(function (m) { return m.close.mean || 0; }).concat([1])), digits: 1, cls: 'gw-ge__line--alt' }]);
    table($('gw-ge-overdue'), [{ h: 'Evento', v: function (r) { return r.name; }, link: true }, { h: 'Cliente', v: function (r) { return r.client; } }, { h: 'Comercial', v: function (r) { return r.commercial; } }, { h: 'Días esperando', v: function (r) { return r.days_waiting; } }, { h: 'Base final', v: function (r) { return r.final_db ? 'Subida' : 'Falta'; } }], t.overdue, eventLink);
    timeGroupTable('gw-ge-time-commercial', t.by_commercial); timeGroupTable('gw-ge-time-client', t.by_client);

    var box = clear($('gw-ge-comments'));
    if (!s.comments.length) empty(box, 'Ningún cliente escribió comentarios en este periodo.');
    s.comments.forEach(function (c) {
      var q = el('blockquote', 'gw-ge__comment'); q.appendChild(el('p', null, c.text));
      q.appendChild(el('cite', null, (c.client || '') + ' · ' + c.event + ' · ' + c.date)); box.appendChild(q);
    });
  }

  /* ---------- datos ---------- */
  function query() {
    var p = new URLSearchParams(), fd = new FormData(form);
    ['desde', 'hasta', 'cliente', 'comercial', 'low', 'overdue', 'wait'].forEach(function (k) { var v = (fd.get(k) || '').toString().trim(); if (v) p.set(k, v); });
    return p.toString();
  }
  function load() {
    $('gw-ge-summary').textContent = 'Calculando…';
    fetch(API + '/panel?' + query(), { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      if (r.status === 403 || r.status === 401) throw new Error('Solo los administradores pueden ver este análisis.');
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || 'No se pudo calcular el análisis.'); });
      return r.json();
    }).then(function (d) {
      if (!form.desde.value) form.desde.value = d.range.from;
      if (!form.hasta.value) form.hasta.value = d.range.to;
      render(d);
    }).catch(function (e) { $('gw-ge-summary').textContent = e.message; toast(e.message); });
  }
  function fillSelect(sel, items) {
    items.forEach(function (i) { var o = el('option', null, i.name); o.value = i.id; sel.appendChild(o); });
  }
  function init() {
    fetch(API + '/filtros', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : Promise.reject(); }).then(function (f) {
      fillSelect(form.cliente, f.clients); fillSelect(form.comercial, f.commercials);
      form.low.value = f.defaults.low_threshold; form.overdue.value = f.defaults.overdue_days; form.wait.value = f.defaults.survey_wait_days;
    }).catch(function () { /* sin filtros se usan los valores de fábrica */ }).then(load);
  }
  form.addEventListener('submit', function (e) { e.preventDefault(); load(); });
  form.addEventListener('change', function () { clearTimeout(timer); timer = setTimeout(load, 400); });
  $('gw-ge-export').addEventListener('click', function () { window.location.href = API + '/exportar?' + query(); });
  window.GW = window.GW || {};
  window.GW.gastosEventos = { refresh: load };
  init();
})();
