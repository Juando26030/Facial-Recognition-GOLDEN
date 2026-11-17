/* Gastos (/gastos) — pestaña «Infraestructura» (Fase 9C). Gráficos propios en SVG (sin librerías ni CDN): barras apiladas por mes y proveedor, tendencia y costo por evento.
   Cada gráfico tiene su vista de tabla. Eventos delegados (nada de onclick inline); avisos con showToast / showConfirm. */
(function () {
  'use strict';
  var root = document.getElementById('gxRoot');
  var tabs = document.getElementById('gastosTabs');
  var NS = 'http://www.w3.org/2000/svg';
  var GROUPS = ['google', 'neon', 'microsoft', 'cloudflare', 'otros'];
  var data = null;           // último resumen
  var costs = [];            // gastos del rango
  var evFilter = '';         // id del evento elegido en «Costo de un evento» ('' = ninguno)
  var tableViews = {};       // gráfico -> mostrar tabla
  var nf = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 0 });

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function cop(n) { return '$ ' + nf.format(Math.round(n || 0)); }
  function compact(n) {
    var a = Math.abs(n);
    if (a >= 1e6) return (n / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M';
    if (a >= 1e3) return nf.format(Math.round(n / 1e3)) + ' mil';
    return nf.format(Math.round(n));
  }
  var MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  function mlabel(m) { return MONTHS[parseInt(m.slice(5, 7), 10) - 1] + ' ' + m.slice(2, 4); }
  function toast(msg, type) { if (window.showToast) window.showToast(msg, type || 'ok'); }
  function api(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
    if (opts.body && !(opts.body instanceof FormData)) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(opts.body); }
    return fetch(url, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (j) {
        if (!res.ok) { var e = new Error(typeof j.detail === 'string' ? j.detail : 'No se pudo completar la acción'); e.status = res.status; throw e; }
        return j;
      });
    });
  }
  function svg(tag, attrs) { var el = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); }); return el; }

  // ---------------------------------------------------------------- pestañas
  if (tabs) {
    tabs.addEventListener('click', function (e) {
      var t = e.target.closest('[role="tab"]');
      if (!t || !tabs.contains(t)) return;
      selectTab(t.getAttribute('data-tab'));
    });
    tabs.addEventListener('keydown', function (e) {
      var t = e.target.closest('[role="tab"]');
      if (!t || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
      var all = Array.prototype.slice.call(tabs.querySelectorAll('[role="tab"]'));
      var next = all[(all.indexOf(t) + (e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length];
      e.preventDefault(); next.focus(); selectTab(next.getAttribute('data-tab'));
    });
  }
  function selectTab(name) {
    tabs.querySelectorAll('[role="tab"]').forEach(function (b) {
      var on = b.getAttribute('data-tab') === name;
      b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1;
      var p = document.getElementById(b.getAttribute('aria-controls')); if (p) p.hidden = !on;
    });
    document.dispatchEvent(new CustomEvent('gastos:tab', { detail: name }));      // la pestaña «Eventos» (otra pieza) puede escucharlo para cargar sus datos
    try { history.replaceState(null, '', '#' + name); } catch (e) { /* sin historial */ }
  }
  if (tabs) { var h = (location.hash || '').slice(1); if (h === 'eventos') selectTab('eventos'); }

  // ---------------------------------------------------------------- carga
  function curMonth() { var d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); }
  function addMonths(m, n) { var t = parseInt(m.slice(0, 4), 10) * 12 + parseInt(m.slice(5, 7), 10) - 1 + n; return Math.floor(t / 12) + '-' + String(t % 12 + 1).padStart(2, '0'); }
  function range() { return { from: document.getElementById('gxFrom').value, to: document.getElementById('gxTo').value }; }
  function qs(r) { return '?from=' + encodeURIComponent(r.from) + '&to=' + encodeURIComponent(r.to); }

  var status = null;         // /api/gastos/infra/status: conexiones y si la tabla existe

  function connPanel() {
    if (!status) return '';
    var badge = { ok: ['gw-badge gw-badge--ok', 'Conectado'], missing: ['gw-badge gw-badge--warn', 'No conectado'], error: ['gw-badge gw-badge--err', 'Hay que revisarlo'] };
    var rows = status.connections.map(function (c) {
      var b = badge[c.state] || badge.missing, more = '';
      if (c.state !== 'ok' && (c.steps.length || c.env.length || c.iam.length)) {
        more = '<details class="gw-gx__help"><summary>Cómo conectarlo</summary>' +
          (c.steps.length ? '<ol>' + c.steps.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ol>' : '') +
          (c.env.length ? '<p class="gw-hint">Variables que faltan: ' + c.env.map(function (v) { return '<code>' + esc(v) + '</code>'; }).join(', ') + '</p>' : '') +
          (c.iam.length ? '<p class="gw-hint">Permisos de Google Cloud: ' + c.iam.map(esc).join('; ') + '.</p>' : '') + '</details>';
      }
      return '<li class="gw-gx__conn"><div><strong>' + esc(c.title) + '</strong> <span class="' + b[0] + '">' + b[1] + '</span><br><span class="gw-hint">' + esc(c.summary) + '</span>' +
        (c.last_import ? '<br><span class="gw-hint">Última importación: ' + esc(c.last_import.slice(0, 10)) + '</span>' : '') + more + '</div></li>';
    }).join('');
    var alert = status.table_ready ? '' : '<div class="gw-alert gw-alert--err" role="alert"><div class="gw-alert__body"><p class="gw-alert__title">La base de datos de este entorno no tiene la tabla de gastos</p><p>' + esc(status.table_message || '') + '</p></div></div>';
    return alert + '<section class="gw-gx__panel"><h3 class="gw-gx__panel-title">Conexiones</h3><p class="gw-hint">Ninguna es obligatoria: sin conexión puedes registrar los gastos a mano o subir un archivo de Excel (CSV). Columnas del archivo: ' + esc(status.csv_columns) + '.</p><ul class="gw-gx__conns">' + rows + '</ul></section>';
  }
  function loadStatus() {
    var box = document.getElementById('gxConn');
    return api('/api/gastos/infra/status').then(function (r) { status = r; box.innerHTML = connPanel(); }).catch(function (e) {
      status = null;
      box.innerHTML = '<div class="gw-alert gw-alert--warn" role="status"><div class="gw-alert__body"><p class="gw-alert__title">No se pudo revisar las conexiones</p><p>' + esc(e.message) + '</p></div></div>';
    });
  }

  function load() {
    var r = range();
    root.setAttribute('aria-busy', 'true');
    var st = loadStatus();
    return Promise.all([api('/api/gastos/infra/summary' + qs(r)), api('/api/gastos/infra/costs' + qs(r))]).then(function (res) {
      data = res[0]; costs = res[1].costs; render();
    }).catch(function (e) {
      var msg = e.status === 403 ? 'Tu cuenta no tiene permiso para ver los gastos de la plataforma.' : e.message;
      document.getElementById('gxBody').innerHTML = '<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudo cargar los gastos</p><p class="gw-state__text">' + esc(msg) + '</p></div>';
    }).then(function () { return st; }).then(function () { root.setAttribute('aria-busy', 'false'); });
  }

  // ---------------------------------------------------------------- gráficos
  function niceMax(v) {
    if (v <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v))), f = v / p;
    var n = f <= 1 ? 1 : f <= 1.2 ? 1.2 : f <= 2 ? 2 : f <= 2.4 ? 2.4 : f <= 3.2 ? 3.2 : f <= 4 ? 4 : f <= 6 ? 6 : f <= 8 ? 8 : 10;
    return n * p;
  }
  function frame(w, h, max, ml) {
    var s = svg('svg', { viewBox: '0 0 ' + w + ' ' + h, class: 'gw-gx__svg', role: 'img' });
    for (var i = 0; i <= 4; i++) {
      var y = 10 + (h - 40) * (1 - i / 4);
      s.appendChild(svg('line', { x1: ml, x2: w - 8, y1: y, y2: y, class: i === 0 ? 'gw-gx__axis' : 'gw-gx__grid' }));
      var t = svg('text', { x: ml - 8, y: y + 4, 'text-anchor': 'end' }); t.textContent = compact(max * i / 4); s.appendChild(t);
    }
    return s;
  }
  function roundedTop(x, y, w, h, r) {            // barra con las dos esquinas de arriba redondeadas (el extremo del dato); abajo recta contra la base
    r = Math.min(r, w / 2, h);
    return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y + 'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
  }

  function compact(n) {
    n = Math.round(n || 0);
    if (n >= 1e6) return '$ ' + (n / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M';
    if (n >= 1e3) return '$ ' + Math.round(n / 1e3) + ' mil';
    return '$ ' + n;
  }
  // Barras SEPARADAS por proveedor y una más para el total del mes (antes iban apiladas en una sola barra).
  function stackedChart() {
    var months = data.months, W = 760, H = 320, ML = 56, MB = 30;
    var present = GROUPS.filter(function (g) { return data.series[g].some(function (v) { return v > 0; }); });
    var keys = present.concat(['total']);
    var max = niceMax(Math.max.apply(null, data.totals.concat([1])) * 1.25);          // aire arriba para la cifra de la barra más alta
    var s = frame(W, H, max, ML);
    var slot = (W - ML - 8) / months.length, gap = 2, n = keys.length;
    var bw = Math.max(6, Math.min(26, (slot * 0.86 - gap * (n - 1)) / n)), gw = bw * n + gap * (n - 1), base = H - MB;
    months.forEach(function (m, i) {
      var x0 = ML + slot * i + (slot - gw) / 2;
      keys.forEach(function (k, idx) {
        var v = k === 'total' ? data.totals[i] : data.series[k][i];
        if (!(v > 0)) return;
        var x = x0 + idx * (bw + gap), h = (H - 40) * v / max, y = base - h;
        var el = svg('path', { d: roundedTop(x, y, bw, h, 3) });
        el.setAttribute('class', 'gw-gx__seg gw-gx-c-' + k); el.setAttribute('tabindex', '0');
        el.setAttribute('data-tip', mlabel(m) + '|' + (k === 'total' ? 'Total del mes' : data.group_labels[k]) + ': ' + cop(v) + '|Total del mes: ' + cop(data.totals[i]));
        s.appendChild(el);
        var t = svg('text', { x: x + bw / 2, y: y - 5, class: 'gw-gx__val', 'text-anchor': 'start', transform: 'rotate(-90 ' + (x + bw / 2) + ' ' + (y - 5) + ')' });
        t.textContent = compact(v); s.appendChild(t);
      });
      var lab = svg('text', { x: x0 + gw / 2, y: H - 10, 'text-anchor': 'middle' }); lab.textContent = mlabel(m); s.appendChild(lab);
    });
    s.setAttribute('aria-label', 'Gasto por mes: una barra por proveedor y una barra con el total del mes, en pesos');
    return s;
  }

  function trendChart() {
    var months = data.months, W = 760, H = 220, ML = 56, MB = 30;
    var max = niceMax(Math.max.apply(null, data.totals.concat([1])));
    var s = frame(W, H, max, ML);
    var slot = (W - ML - 8) / months.length, pts = [];
    months.forEach(function (m, i) {
      var x = ML + slot * i + slot / 2, y = 10 + (H - 40) * (1 - data.totals[i] / max);
      pts.push([x, y]);
      var lab = svg('text', { x: x, y: H - 10, 'text-anchor': 'middle' }); lab.textContent = mlabel(m); s.appendChild(lab);
    });
    if (pts.length > 1) s.appendChild(svg('polyline', { points: pts.map(function (p) { return p.join(','); }).join(' '), class: 'gw-gx__line' }));
    pts.forEach(function (p, i) {
      var hit = svg('circle', { cx: p[0], cy: p[1], r: 16, class: 'gw-gx__hit', tabindex: '0' });
      hit.setAttribute('data-tip', mlabel(months[i]) + '|Total: ' + cop(data.totals[i]));
      s.appendChild(hit); s.appendChild(svg('circle', { cx: p[0], cy: p[1], r: 5, class: 'gw-gx__dot' }));
    });
    var last = pts[pts.length - 1];
    if (last) { var t = svg('text', { x: last[0], y: Math.max(14, last[1] - 18), 'text-anchor': 'end', class: 'gw-gx__val' }); t.textContent = cop(data.totals[data.totals.length - 1]); s.appendChild(t); }
    s.setAttribute('aria-label', 'Tendencia del gasto total por mes, en pesos');
    return s;
  }

  function eventsChart() {
    var rows = data.events.filter(function (r) { return r.total > 0; }).slice(0, 12), W = 760, rowH = 34, ML = 190, H = rows.length * rowH + 40;
    var max = niceMax(Math.max.apply(null, rows.map(function (r) { return r.total; }).concat([1])));
    var s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'gw-gx__svg', role: 'img', 'aria-label': 'Costo de infraestructura por evento, en pesos' });
    var plot = W - ML - 70;
    for (var i = 0; i <= 4; i++) {
      var x = ML + plot * i / 4;
      s.appendChild(svg('line', { x1: x, x2: x, y1: 0, y2: rows.length * rowH, class: i === 0 ? 'gw-gx__axis' : 'gw-gx__grid' }));
      var t = svg('text', { x: x, y: rows.length * rowH + 18, 'text-anchor': 'middle' }); t.textContent = compact(max * i / 4); s.appendChild(t);
    }
    rows.forEach(function (r, k) {
      var y = k * rowH + 6, bh = 20;
      var nm = svg('text', { x: ML - 8, y: y + 14, 'text-anchor': 'end' });
      nm.textContent = r.name.length > 26 ? r.name.slice(0, 25) + '…' : r.name; s.appendChild(nm);
      var wf = plot * r.fixed / max, wv = plot * r.variable / max;
      var tip = r.name + '|Fijo: ' + cop(r.fixed) + ' · Variable: ' + cop(r.variable) + '|Ingresos: ' + nf.format(r.activity) + ' · Días activos: ' + r.days;
      if (wf > 0) { var a = svg('rect', { x: ML, y: y, width: wf, height: bh, class: 'gw-gx__seg gw-gx-c-fixed', tabindex: '0' }); a.setAttribute('data-tip', tip); s.appendChild(a); }
      if (wv > 0) { var b = svg('path', { d: 'M' + (ML + wf) + ',' + y + 'H' + (ML + wf + wv - 4) + 'Q' + (ML + wf + wv) + ',' + y + ' ' + (ML + wf + wv) + ',' + (y + 4) + 'V' + (y + bh - 4) + 'Q' + (ML + wf + wv) + ',' + (y + bh) + ' ' + (ML + wf + wv - 4) + ',' + (y + bh) + 'H' + (ML + wf) + 'Z', class: 'gw-gx__seg gw-gx-c-variable', tabindex: '0' }); b.setAttribute('data-tip', tip); s.appendChild(b); }
      var v = svg('text', { x: ML + wf + wv + 6, y: y + 14, class: 'gw-gx__val' }); v.textContent = cop(r.total); s.appendChild(v);
    });
    return s;
  }

  // ---------------------------------------------------------------- piezas de la pantalla
  function legend(items) {
    return '<ul class="gw-gx__legend" aria-label="Leyenda">' + items.map(function (i) { return '<li><span class="gw-gx__sw gw-gx-c-' + i[0] + '" aria-hidden="true"></span>' + esc(i[1]) + '</li>'; }).join('') + '</ul>';
  }
  function panel(id, title, legendHtml, chartHtmlOrNode, tableHtml, extra) {
    var showTable = !!tableViews[id];
    return '<section class="gw-gx__panel" data-chart="' + id + '"><div class="gw-gx__panel-head"><h3 class="gw-gx__panel-title">' + esc(title) + '</h3>' +
      '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-act="toggle-table" data-chart="' + id + '" aria-pressed="' + showTable + '">' + (showTable ? 'Ver gráfico' : 'Ver como tabla') + '</button></div>' +
      (showTable ? '' : legendHtml) + '<div class="gw-gx__chart" data-slot="' + id + '"' + (showTable ? ' hidden' : '') + '></div>' +
      (showTable ? '<div class="gw-table-wrap gw-scroll-x">' + tableHtml + '</div>' : '') + (extra || '') + '</section>';
  }
  function monthTable() {
    var head = '<tr><th scope="col">Mes</th>' + GROUPS.map(function (g) { return '<th scope="col" class="gw-gx__num">' + esc(data.group_labels[g]) + '</th>'; }).join('') + '<th scope="col" class="gw-gx__num">Total</th></tr>';
    var body = data.months.map(function (m, i) { return '<tr><th scope="row">' + esc(mlabel(m)) + '</th>' + GROUPS.map(function (g) { return '<td class="gw-gx__num">' + cop(data.series[g][i]) + '</td>'; }).join('') + '<td class="gw-gx__num"><strong>' + cop(data.totals[i]) + '</strong></td></tr>'; }).join('');
    return '<table class="gw-table"><caption>Gasto por mes y proveedor (COP)</caption><thead>' + head + '</thead><tbody>' + body + '</tbody></table>';
  }
  function trendTable() {
    return '<table class="gw-table"><caption>Gasto total por mes (COP)</caption><thead><tr><th scope="col">Mes</th><th scope="col" class="gw-gx__num">Total</th></tr></thead><tbody>' +
      data.months.map(function (m, i) { return '<tr><th scope="row">' + esc(mlabel(m)) + '</th><td class="gw-gx__num">' + cop(data.totals[i]) + '</td></tr>'; }).join('') + '</tbody></table>';
  }
  function eventsTable() {
    if (!data.events.length) return '<p class="gw-hint">Aún no hay eventos con costo asignado en este periodo.</p>';
    return '<table class="gw-table"><caption>Costo de infraestructura por evento (COP)</caption><thead><tr><th scope="col">Evento</th><th scope="col" class="gw-gx__num">Total</th><th scope="col" class="gw-gx__num">Parte fija</th><th scope="col" class="gw-gx__num">Parte variable</th><th scope="col" class="gw-gx__num">Ingresos</th><th scope="col" class="gw-gx__num">Días activos</th></tr></thead><tbody>' +
      data.events.map(function (e) { return '<tr><th scope="row">' + esc(e.name) + ' <span class="gw-muted">' + esc(e.code) + '</span></th><td class="gw-gx__num"><strong>' + cop(e.total) + '</strong></td><td class="gw-gx__num">' + cop(e.fixed) + '</td><td class="gw-gx__num">' + cop(e.variable) + '</td><td class="gw-gx__num">' + nf.format(e.activity) + '</td><td class="gw-gx__num">' + e.days + '</td></tr>'; }).join('') + '</tbody></table>';
  }

  function eventDetailPanel() {
    if (!data.events.length) return '';
    var opts = '<option value="">Elige un evento…</option>' + data.events.map(function (e) {
      return '<option value="' + e.event_id + '"' + (String(e.event_id) === evFilter ? ' selected' : '') + '>' + esc(e.name) + ' (' + esc(e.code) + ') · ' + cop(e.total) + '</option>';
    }).join('');
    var ev = data.events.filter(function (e) { return String(e.event_id) === evFilter; })[0];
    var detail = '<p class="gw-hint">Elige un evento para ver cuánto costó, mes por mes, y de dónde sale su parte.</p>';
    if (ev) {
      var rows = data.months.map(function (m) { return [m, ev.by_month[m] || 0]; }).filter(function (r) { return r[1] > 0; });
      detail = '<div class="gw-gx__kpis">' +
        '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Costo total</span><span class="gw-gx__kpi-value">' + cop(ev.total) + '</span><span class="gw-gx__kpi-hint">' + esc(ev.status || '') + '</span></div>' +
        '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Parte fija</span><span class="gw-gx__kpi-value">' + cop(ev.fixed) + '</span><span class="gw-gx__kpi-hint">' + ev.days + ' día(s) activo(s)</span></div>' +
        '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Parte variable</span><span class="gw-gx__kpi-value">' + cop(ev.variable) + '</span><span class="gw-gx__kpi-hint">' + nf.format(ev.activity) + ' registro(s)</span></div>' +
        '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Registros</span><span class="gw-gx__kpi-value">' + nf.format(ev.door) + ' + ' + nf.format(ev.forms) + '</span><span class="gw-gx__kpi-hint">Puerta + formularios web</span></div></div>' +
        (rows.length ? '<div class="gw-table-wrap gw-scroll-x"><table class="gw-table"><caption>Costo de este evento por mes (COP)</caption><thead><tr><th scope="col">Mes</th><th scope="col" class="gw-gx__num">Costo</th></tr></thead><tbody>' +
          rows.map(function (r) { return '<tr><th scope="row">' + esc(mlabel(r[0])) + '</th><td class="gw-gx__num">' + cop(r[1]) + '</td></tr>'; }).join('') + '</tbody></table></div>'
          : '<p class="gw-hint">Este evento no recibió costo en el periodo: no tuvo registros por la puerta ni por formulario, y no hay costos fijos que repartir por días.</p>');
    }
    return '<section class="gw-gx__panel"><h3 class="gw-gx__panel-title">Costo de un evento</h3>' +
      '<label class="gw-label" for="gxEvSel">Evento</label><select id="gxEvSel" class="gw-select">' + opts + '</select>' + detail + '</section>';
  }

  function kpis() {
    var un = data.unassigned > 0 ? 'Sin repartir: ' + cop(data.unassigned) + ' (' + data.unassigned_months.map(mlabel).join(', ') + ')' : 'Todo el costo quedó repartido';
    return '<div class="gw-gx__kpis">' +
      '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Total del periodo</span><span class="gw-gx__kpi-value">' + cop(data.grand_total) + '</span><span class="gw-gx__kpi-hint">' + data.months.length + ' mes(es) consultado(s)</span></div>' +
      '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Promedio por mes</span><span class="gw-gx__kpi-value">' + cop(data.monthly_avg) + '</span><span class="gw-gx__kpi-hint">Solo meses con gasto registrado</span></div>' +
      '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Promedio por evento</span><span class="gw-gx__kpi-value">' + cop(data.avg_per_event) + '</span><span class="gw-gx__kpi-hint">' + esc(un) + '</span></div>' +
      '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Eventos con costo</span><span class="gw-gx__kpi-value">' + data.events.filter(function (r) { return r.total > 0; }).length + '</span><span class="gw-gx__kpi-hint">De ' + data.events.length + ' evento(s) del periodo, sin la persona de prueba</span></div>' +
      (data.neon_configured ? '<div class="gw-gx__kpi"><span class="gw-gx__kpi-label">Neon (uso del mes)</span><span class="gw-gx__kpi-value" id="gxNeonKpi">…</span><span class="gw-gx__kpi-hint" id="gxNeonHint">Consultando…</span></div>' : '') + '</div>';
  }

  function settingsPanel() {
    var opts = Object.keys(data.basis_labels).map(function (k) { return '<option value="' + k + '"' + (k === data.basis ? ' selected' : '') + '>' + esc(data.basis_labels[k]) + '</option>'; }).join('');
    var imp = data.gcp_export_configured
      ? '<button type="button" class="gw-btn gw-btn--secondary" data-act="import-google">Importar Google ahora</button><span class="gw-hint">La importación de Google corre sola cada domingo a las 12 m. en el Job de operaciones.</span>'
      : '<span class="gw-hint">Google no está conectado (mira «Conexiones» arriba). Mientras tanto, registra el gasto de Google a mano o sube un archivo.</span>';
    return '<section class="gw-gx__panel"><h3 class="gw-gx__panel-title">Cómo se reparte entre eventos</h3><p class="gw-gx__formula"><strong>Fórmula:</strong> ' + esc(data.formula) + '</p>' +
      '<form class="gw-gx__settings" id="gxSettings"><div class="gw-field"><label class="gw-label" for="gxBasis">Criterio de reparto</label><select class="gw-select" id="gxBasis" name="basis">' + opts + '</select></div>' +
      '<div class="gw-field"><label class="gw-label" for="gxTrm">TRM por defecto (COP por USD)</label><input class="gw-input gw-input--short" id="gxTrm" name="trm_default" inputmode="decimal" value="' + (data.trm_default || '') + '" placeholder="Ej. 4100"></div>' +
      '<button type="submit" class="gw-btn gw-btn--primary">Guardar</button></form>' +
      '<div class="gw-row">' + imp + '</div><div id="gxNeon" class="gw-hint">' + (data.neon_configured ? 'Uso de Neon: consultando…' : 'Neon solo informa el uso, no el dinero: su costo se registra a mano (mira «Conexiones» para conectar el uso).') + '</div></section>';
  }

  function costsTable() {
    if (!costs.length) return '<div class="gw-empty"><p>No hay gastos registrados en este periodo. Usa «Registrar gasto» para agregar el primero.</p></div>';
    var rows = costs.slice().reverse().map(function (c) {
      var amt = c.currency === 'USD' ? 'US$ ' + nf.format(c.amount) + ' × ' + nf.format(c.trm) : '';
      return '<tr data-id="' + c.id + '"><td>' + esc(mlabel(c.month)) + '</td><td>' + esc(c.provider_label) + '</td><td>' + esc(c.concept) + (c.note ? '<br><span class="gw-muted">' + esc(c.note) + '</span>' : '') + '</td>' +
        '<td>' + (c.kind === 'fixed' ? 'Fijo' : 'Variable') + '</td><td class="gw-gx__num">' + cop(c.amount_cop) + (amt ? '<br><span class="gw-muted">' + esc(amt) + '</span>' : '') + '</td>' +
        '<td>' + (c.source === 'gcp_export' ? '<span class="gw-badge gw-badge--info">Google</span>' : c.source === 'archivo' ? '<span class="gw-badge">Archivo</span>' : 'Manual') + '</td>' +
        '<td><div class="gw-gx__actions">' + (c.has_attachment ? '<a class="gw-btn gw-btn--ghost gw-btn--sm" href="/api/gastos/infra/costs/' + c.id + '/attachment" target="_blank" rel="noopener">Soporte</a>' : '') +
        '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-act="edit" data-id="' + c.id + '">Editar</button>' +
        '<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-act="delete" data-id="' + c.id + '">Borrar</button></div></td></tr>';
    }).join('');
    return '<div class="gw-table-wrap gw-scroll-x"><table class="gw-table"><caption>Gastos registrados</caption><thead><tr><th scope="col">Mes</th><th scope="col">Proveedor</th><th scope="col">Concepto</th><th scope="col">Tipo</th><th scope="col" class="gw-gx__num">Monto (COP)</th><th scope="col">Origen</th><th scope="col"><span class="gw-sr-only">Acciones</span></th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  function render() {
    var body = document.getElementById('gxBody');
    var empty = !costs.length;
    body.innerHTML = (empty ? '<div class="gw-alert gw-alert--warn"><div class="gw-alert__body"><p class="gw-alert__title">Aún no hay gastos en este periodo</p><p>Registra los gastos de cada proveedor, sube un archivo o conecta Google, y aquí aparecerán los gráficos.</p></div></div>' : '') +
      kpis() +
      panel('month', 'Gasto por mes y proveedor', legend(GROUPS.map(function (g) { return [g, data.group_labels[g]]; }).concat([['total', 'Total del mes']])), null, monthTable()) +
      panel('trend', 'Tendencia del gasto total', '', null, trendTable()) +
      panel('events', 'Costo por evento', legend([['fixed', 'Parte fija (días activos)'], ['variable', 'Parte variable (ingresos)']]), null, eventsTable(),
        data.events.some(function (r) { return r.total > 0; }) ? '' : '<p class="gw-hint">Aún no hay eventos con costo asignado en este periodo.</p>') +
      eventDetailPanel() +
      settingsPanel() +
      '<section class="gw-gx__panel"><h3 class="gw-gx__panel-title">Gastos registrados</h3>' + costsTable() + '</section>';
    mount('month', stackedChart); mount('trend', trendChart);
    if (data.events.some(function (r) { return r.total > 0; })) mount('events', eventsChart);
    if (data.neon_configured) loadNeon();
  }
  function mount(id, fn) {
    var slot = root.querySelector('[data-slot="' + id + '"]');
    if (!slot || tableViews[id]) return;
    if (!data.grand_total && id !== 'events') { slot.innerHTML = '<p class="gw-hint">Sin datos para graficar.</p>'; return; }
    slot.appendChild(fn());
  }
  function loadNeon() {
    api('/api/gastos/infra/neon-usage?month=' + encodeURIComponent(data.to)).then(function (r) {
      var el = document.getElementById('gxNeon'); if (!el) return;
      var kv = document.getElementById('gxNeonKpi'), kh = document.getElementById('gxNeonHint');
      if (kv && kh) { kv.textContent = r.available ? nf.format(r.compute_hours) + ' h' : '—'; kh.textContent = r.available ? 'Cómputo (CU) de ' + mlabel(r.month) + ' en ' + r.projects + ' proyecto(s). Solo uso: el dinero va a mano.' : r.reason; }
      el.textContent = r.available ? 'Uso de Neon en ' + mlabel(r.month) + ': ' + nf.format(r.compute_hours) + ' horas de cómputo (CU) en ' + r.projects + ' proyecto(s). Es solo uso: el costo se registra a mano.' : 'Neon: ' + r.reason;
    }).catch(function () { /* informativo */ });
  }

  // ---------------------------------------------------------------- tooltip (un solo elemento; funciona con ratón, toque y teclado)
  var tip = null;
  function showTip(el) {
    var chart = el.closest('.gw-gx__chart'); if (!chart || !el.getAttribute('data-tip')) return;
    if (!tip) { tip = document.createElement('div'); tip.className = 'gw-gx__tip'; tip.setAttribute('role', 'tooltip'); }
    var parts = el.getAttribute('data-tip').split('|');
    tip.innerHTML = '<strong>' + esc(parts[0]) + '</strong>' + parts.slice(1).map(esc).join('<br>');
    chart.appendChild(tip);
    var cb = chart.getBoundingClientRect(), eb = el.getBoundingClientRect();
    var left = eb.left - cb.left + eb.width / 2 - tip.offsetWidth / 2;
    tip.style.left = Math.max(0, Math.min(left, cb.width - tip.offsetWidth)) + 'px';
    tip.style.top = Math.max(0, eb.top - cb.top - tip.offsetHeight - 8) + 'px';
  }
  function hideTip() { if (tip && tip.parentNode) tip.parentNode.removeChild(tip); }
  root.addEventListener('change', function (e) { if (e.target.id === 'gxEvSel') { evFilter = e.target.value; render(); var el = root.querySelector('#gxEvSel'); if (el) el.focus(); } });
  root.addEventListener('pointerover', function (e) { var t = e.target.closest('[data-tip]'); if (t) showTip(t); });
  root.addEventListener('pointerout', function (e) { if (e.target.closest('[data-tip]')) hideTip(); });
  root.addEventListener('focusin', function (e) { var t = e.target.closest('[data-tip]'); if (t) showTip(t); });
  root.addEventListener('focusout', hideTip);

  // ---------------------------------------------------------------- formulario de gasto
  var dialog = null, lastFocus = null;
  function closeDialog() { if (dialog) { dialog.remove(); dialog = null; document.removeEventListener('keydown', onKey); if (lastFocus && lastFocus.focus) lastFocus.focus(); } }
  function onKey(e) { if (e.key === 'Escape') closeDialog(); }
  function opt(list, sel) { return list.map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === sel ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join(''); }

  function openForm(c) {
    lastFocus = document.activeElement;
    var editing = !!c; c = c || { month: data ? data.to : curMonth(), provider: 'google', kind: 'variable', currency: 'COP' };
    var providers = Object.keys(data.providers).map(function (k) { return [k, data.providers[k]]; });
    dialog = document.createElement('div'); dialog.className = 'gw-gx__dialog';
    dialog.innerHTML = '<form class="gw-gx__dialog-box" role="dialog" aria-modal="true" aria-labelledby="gxDlgT" autocomplete="off" novalidate data-id="' + (editing ? c.id : '') + '">' +
      '<h3 id="gxDlgT" class="gw-gx__panel-title">' + (editing ? 'Editar gasto' : 'Registrar gasto') + '</h3><p class="gw-gx__err" id="gxErr" role="alert" hidden></p>' +
      '<div class="gw-gx__grid2"><div class="gw-field"><label class="gw-label" for="fMonth">Mes</label><input class="gw-input" type="month" id="fMonth" name="month" value="' + esc(c.month) + '" required></div>' +
      '<div class="gw-field"><label class="gw-label" for="fProv">Proveedor</label><select class="gw-select" id="fProv" name="provider">' + opt(providers, c.provider) + '</select></div></div>' +
      '<div class="gw-field"><label class="gw-label" for="fConcept">Concepto</label><input class="gw-input" id="fConcept" name="concept" maxlength="160" value="' + esc(c.concept || '') + '" placeholder="Ej. Cloud Run, Dominio golden-eventos.com" required></div>' +
      '<div class="gw-gx__grid2"><div class="gw-field"><label class="gw-label" for="fKind">Tipo</label><select class="gw-select" id="fKind" name="kind">' + opt([['variable', 'Variable (depende del uso)'], ['fixed', 'Fijo (cuota mensual)']], c.kind) + '</select></div>' +
      '<div class="gw-field"><label class="gw-label" for="fCur">Moneda</label><select class="gw-select" id="fCur" name="currency">' + opt([['COP', 'Pesos (COP)'], ['USD', 'Dólares (USD)']], c.currency) + '</select></div></div>' +
      '<div class="gw-gx__grid2"><div class="gw-field"><label class="gw-label" for="fAmt">Monto</label><input class="gw-input" id="fAmt" name="amount" inputmode="decimal" value="' + (editing ? c.amount : '') + '" required></div>' +
      '<div class="gw-field" id="fTrmBox"' + (c.currency === 'USD' ? '' : ' hidden') + '><label class="gw-label" for="fTrm">TRM del día (COP por USD)</label><input class="gw-input" id="fTrm" name="trm" inputmode="decimal" value="' + (c.trm || (data && data.trm_default) || '') + '"></div></div>' +
      '<div class="gw-field"><label class="gw-label" for="fNote">Nota (opcional)</label><input class="gw-input" id="fNote" name="note" maxlength="300" value="' + esc(c.note || '') + '"></div>' +
      '<div class="gw-field"><label class="gw-label" for="fFile">Soporte (opcional: PDF, PNG o JPG, máximo 5 MB)</label><input class="gw-input" type="file" id="fFile" name="file" accept="application/pdf,image/png,image/jpeg">' +
      (editing && c.has_attachment ? '<span class="gw-hint">Ya tiene un soporte; si eliges otro, lo reemplaza. <button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-act="drop-attachment">Quitar soporte</button></span>' : '') + '</div>' +
      '<div class="gw-actions"><button type="button" class="gw-btn gw-btn--secondary" data-act="cancel">Cancelar</button><button type="submit" class="gw-btn gw-btn--primary">Guardar</button></div></form>';
    document.body.appendChild(dialog);
    document.addEventListener('keydown', onKey);
    dialog.querySelector('#fConcept').focus();
  }

  function formBody(f) {
    return { month: f.month.value, provider: f.provider.value, concept: f.concept.value, kind: f.kind.value, currency: f.currency.value, amount: f.amount.value, trm: f.currency.value === 'USD' ? f.trm.value : null, note: f.note.value };
  }
  function submitForm(f) {
    var id = f.getAttribute('data-id'), err = f.querySelector('#gxErr'), btn = f.querySelector('[type="submit"]');
    err.hidden = true; btn.disabled = true;
    var file = f.file.files[0];
    api(id ? '/api/gastos/infra/costs/' + id : '/api/gastos/infra/costs', { method: id ? 'PUT' : 'POST', body: formBody(f) }).then(function (saved) {
      if (!file) return saved;
      var fd = new FormData(); fd.append('file', file);
      return api('/api/gastos/infra/costs/' + saved.id + '/attachment', { method: 'POST', body: fd }).catch(function (e) { toast('El gasto se guardó, pero el soporte no: ' + e.message, 'error'); return saved; });
    }).then(function () { closeDialog(); toast('Gasto guardado'); return load(); }).catch(function (e) { err.textContent = e.message; err.hidden = false; btn.disabled = false; });
  }

  // ---------------------------------------------------------------- eventos de la pantalla
  root.addEventListener('submit', function (e) {
    if (e.target.id === 'gxRange') { e.preventDefault(); load(); }
    if (e.target.id === 'gxSettings') {
      e.preventDefault();
      var f = e.target;
      api('/api/gastos/infra/settings', { method: 'PUT', body: { basis: f.basis.value, trm_default: f.trm_default.value } }).then(function () { toast('Parámetros guardados'); return load(); }).catch(function (er) { toast(er.message, 'error'); });
    }
  });
  document.addEventListener('submit', function (e) { if (dialog && dialog.contains(e.target)) { e.preventDefault(); submitForm(e.target); } });
  document.addEventListener('change', function (e) { if (dialog && e.target.id === 'fCur') dialog.querySelector('#fTrmBox').hidden = e.target.value !== 'USD'; });
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]'); if (!b) return;
    var act = b.getAttribute('data-act');
    if (dialog && dialog.contains(b)) {
      if (act === 'cancel') closeDialog();
      if (act === 'drop-attachment') {
        var id = dialog.querySelector('form').getAttribute('data-id');
        window.showConfirm('¿Quitar el soporte de este gasto?').then(function (ok) { if (!ok) return; api('/api/gastos/infra/costs/' + id + '/attachment', { method: 'DELETE' }).then(function () { toast('Soporte quitado'); closeDialog(); load(); }).catch(function (er) { toast(er.message, 'error'); }); });
      }
      return;
    }
    if (!root.contains(b)) return;
    var cid = parseInt(b.getAttribute('data-id'), 10);
    if (act === 'new') openForm();
    else if (act === 'edit') openForm(costs.filter(function (c) { return c.id === cid; })[0]);
    else if (act === 'delete') {
      window.showConfirm('¿Borrar este gasto? No se puede deshacer.').then(function (ok) {
        if (ok) api('/api/gastos/infra/costs/' + cid, { method: 'DELETE' }).then(function () { toast('Gasto borrado'); return load(); }).catch(function (er) { toast(er.message, 'error'); });
      });
    } else if (act === 'toggle-table') { var k = b.getAttribute('data-chart'); tableViews[k] = !tableViews[k]; render(); }
    else if (act === 'upload') { var inp = document.getElementById('gxFile'); if (!inp) { inp = document.createElement('input'); inp.type = 'file'; inp.id = 'gxFile'; inp.accept = '.csv,text/csv,text/plain'; inp.hidden = true; root.appendChild(inp); } inp.value = ''; inp.click(); }
    else if (act === 'export') { var r = range(); window.location.href = '/api/gastos/infra/export.xlsx' + qs(r); }
    else if (act === 'import-google') {
      b.disabled = true;
      api('/api/gastos/infra/import/google', { method: 'POST', body: {} }).then(function (r) {
        toast('Google: ' + r.imported + ' nuevo(s), ' + r.updated + ' actualizado(s)' + (r.warnings && r.warnings.length ? '. ' + r.warnings[0] : ''), r.warnings && r.warnings.length ? 'error' : 'ok'); return load();
      }).catch(function (er) { toast(er.message, 'error'); b.disabled = false; });
    }
  });

  document.addEventListener('change', function (e) {
    if (e.target.id !== 'gxFile' || !e.target.files[0]) return;
    var fd = new FormData(); fd.append('file', e.target.files[0]);
    api('/api/gastos/infra/import/csv', { method: 'POST', body: fd }).then(function (r) {
      var warn = r.warnings && r.warnings.length;
      toast('Archivo cargado: ' + r.imported + ' nuevo(s), ' + r.updated + ' actualizado(s)' + (r.skipped ? ', ' + r.skipped + ' omitido(s)' : '') + (warn ? '. ' + r.warnings[0] : ''), warn ? 'error' : 'ok');
      return load();
    }).catch(function (er) { toast(er.message, 'error'); });
  });

  // ---------------------------------------------------------------- arranque
  var to = curMonth();
  document.getElementById('gxTo').value = to; document.getElementById('gxFrom').value = addMonths(to, -11);
  load();
})();
