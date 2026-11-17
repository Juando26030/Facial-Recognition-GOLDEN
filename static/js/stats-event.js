/* Estadísticas del evento (templates/kiosk_estadisticas.html): gráficos por variable, exportar la base, borrar fotos e informe de tiempos.
   Antes vivía en la plantilla; la lógica y las rutas son las mismas. Lee window.EVENT_ID y window.STATS_BASE (los pone la plantilla). Todo lo escrito por personas se inserta como
   texto (nunca como HTML); eventos por delegación. Colores de los gráficos: paleta de datos --gw-viz-* (GWViz, de analytics-dashboard.js). */
(function () {
  'use strict';
  var EVENT_ID = window.EVENT_ID, BASE = window.STATS_BASE;
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function toast(msg, kind) { if (window.showToast) window.showToast(msg, kind || 'info'); }
  function busy(btn, work) { return window.GW && window.GW.busy ? window.GW.busy(btn, work) : Promise.resolve(work()); }
  var viz = window.GWViz;          // lo define analytics-dashboard.js, que la plantilla carga antes

  /* ---------- Fotos y rostros del evento (solo admin) ---------- */
  var purgeBtn = $('purgePhotosBtn');
  if (purgeBtn) purgeBtn.addEventListener('click', function () {
    busy(purgeBtn, async function () {
      var say = $('purgeStatus'), res = await window.purgeEventBiometrics(EVENT_ID);
      if (!res) return;
      say.className = 'gw-msg ' + (res.ok ? 'gw-msg--ok' : 'gw-msg--err');
      say.textContent = res.ok ? window.purgeEventMessage(res.data) : (res.data.detail || 'No se pudo borrar');
    }).catch(function () { toast('No se pudo borrar. Intenta de nuevo.', 'error'); });
  });

  /* ---------- Informe de tiempo por registro (solo admin; solo agregados) ---------- */
  var timingBody = $('timingBody');
  if (timingBody) {
    var sec = function (ms) { return ms == null ? '—' : (ms / 1000).toFixed(1) + ' s'; };
    var table = function (title, head, rows) {
      var box = el('div'); box.appendChild(el('h4', null, title));
      var t = el('table', 'gw-table gw-table-cards'); var thead = el('thead'), tr0 = el('tr');
      head.forEach(function (x) { var th = el('th', null, x); th.scope = 'col'; tr0.appendChild(th); });
      thead.appendChild(tr0); t.appendChild(thead);
      var tb = el('tbody');
      rows.forEach(function (r) { var tr = el('tr'); r.forEach(function (x, i) { var td = el('td', null, String(x)); if (head[i]) td.dataset.label = head[i]; tr.appendChild(td); }); tb.appendChild(tr); });
      t.appendChild(tb); box.appendChild(t); return box;
    };
    var line = function (s) { return [s.n, sec(s.p50_ms), sec(s.p90_ms), s.small_sample ? 'muestra pequeña' : '']; };
    fetch('/api/events/' + EVENT_ID + '/timing-report', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : Promise.reject(new Error('No se pudo cargar')); }).then(function (d) {
      timingBody.textContent = '';
      if (!d.measured) { timingBody.textContent = d.registrations ? 'Aún no hay registros medidos en este evento (los hechos antes de esta medición no cuentan).' : 'Aún no hay registros en este evento.'; return; }
      timingBody.appendChild(el('p', null, 'Medidos: ' + d.measured + ' de ' + d.registrations + ' registros (' + d.coverage_pct + '%). Mediana ' + sec(d.overall.p50_ms) + ', p90 ' + sec(d.overall.p90_ms) + '.'));
      timingBody.appendChild(table('Por pantalla', ['Pantalla', 'Registros', 'p50', 'p90', 'Nota'], d.by_flow.map(function (f) { return [f.ui_flow].concat(line(f)); })));
      timingBody.appendChild(table('Por digitador', ['Digitador', 'Registros', 'p50', 'p90', 'Nota'], d.by_staff.map(function (s) { return [s.name].concat(line(s)); })));
    }).catch(function () { timingBody.textContent = 'No se pudo cargar el informe de tiempos.'; });
  }

  /* ---------- Exportar la base: el Excel se arma en segundo plano y se descarga YA armado (nunca una petición larga que Firebase corte a los 60 s) ---------- */
  var exportBtn = $('exportBtn');
  if (exportBtn) exportBtn.addEventListener('click', function () {
    var box = $('exportProgress'), msg = box.querySelector('[data-msg]'), bar = box.querySelector('[data-bar]'), prog = box.querySelector('[role="progressbar"]');
    var show = function (text, pct, bad) {
      box.hidden = false; msg.textContent = text; bar.style.width = pct + '%'; prog.setAttribute('aria-valuenow', String(Math.round(pct)));
      box.classList.toggle('gw-pbar--err', !!bad);
    };
    busy(exportBtn, async function () {
      try {
        show('Preparando el reporte…', 3);
        var st = await (await fetch('/api/report/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_id: EVENT_ID }) })).json().then(function (d) { return d; }, function () { return {}; });
        for (var i = 0; i < 300 && st.job_id && (st.status === 'queued' || st.status === 'running'); i++) {      // hasta 5 min mirando el avance cada segundo
          show((st.stage || 'Preparando el reporte') + '… ' + (st.percent || 0) + '%', st.percent || 3);
          await new Promise(function (r) { setTimeout(r, 1000); });
          var r = await fetch('/api/report/status/' + st.job_id, { cache: 'no-store' });
          st = r.ok ? await r.json() : { status: 'error', error: 'No se pudo consultar el avance del reporte.' };
        }
        if (st.ready) {
          show('Listo. Descargando el Excel…', 100);
          window.location.href = '/api/report/download/' + st.job_id;
          setTimeout(function () { box.hidden = true; }, 6000);
        } else {
          show(st.error || st.detail || 'No se pudo generar el reporte. Intenta de nuevo en un momento.', 0, true);
          toast(st.error || st.detail || 'No se pudo generar el reporte. Intenta de nuevo.', 'error');
        }
      } catch (e) {
        show('No se pudo generar el reporte (sin conexión). Intenta de nuevo.', 0, true);
      }
    });
  });

  /* ---------- Gráficos por variable ---------- */
  var variableSelect = $('statsVariableSelect'), addBtn = $('addStatsVarBtn'), container = $('statsChartsContainer'), emptyMsg = $('statsEmptyMsg');
  if (!variableSelect || !container) return;
  /* El backend (/stats/data) ya devuelve el `type` detectado (numeric/categorical) según los valores reales: aquí solo se ofrecen los tipos de gráfico válidos para ESE tipo. */
  var CHART_TYPES = {
    categorical: [{ value: 'bar', label: 'Barras' }, { value: 'pie', label: 'Circular (pie)' }],
    numeric: [{ value: 'bar', label: 'Histograma (barras)' }, { value: 'line', label: 'Líneas' }],
  };
  var chartInstances = {};   // clave de variable -> instancia de Chart.js, para destruirla si se quita la tarjeta
  var cache = {};            // clave -> { result, select, canvas }, para volver a dibujar al cambiar de tema

  function updateEmptyMsg() { emptyMsg.hidden = container.children.length > 0; }
  /* «histogram» (Parámetros del evento) no es un tipo aparte: para datos numéricos las barras YA son el histograma. Si el tipo configurado no aplica al dato real, cae al primero válido. */
  function resolveChartType(requested, dataType) {
    var valid = (CHART_TYPES[dataType] || CHART_TYPES.categorical).map(function (o) { return o.value; });
    var normalized = requested === 'histogram' ? 'bar' : requested;
    return valid.indexOf(normalized) >= 0 ? normalized : valid[0];
  }

  /* Alto del lienzo y presentación según el aparato (Fase 1.7, M5): en celular, o con muchas opciones / nombres largos, las barras van en FILAS (nombre completo arriba, barra ancha,
     cantidad y porcentaje siempre visibles), de mayor a menor si es una variable de categorías; la circular crece con su leyenda. Devuelve { config, height }. */
  function planChart(chartType, buckets, dataType, box) {
    var narrow = viz.narrow && viz.narrow(), n = buckets.length;
    var longest = buckets.reduce(function (m, b) { return Math.max(m, String(b.label).length); }, 0);
    if (chartType === 'bar' && viz.rowBars && (narrow || n > 8 || longest > 18)) {
      var list = buckets.slice();
      if (dataType !== 'numeric' && n > 5) list.sort(function (a, b) { return b.count - a.count; });
      var built = viz.rowBars(list.map(function (b) { return b.label; }), list.map(function (b) { return b.count; }), { width: Math.max(240, (box.parentNode && box.parentNode.clientWidth || window.innerWidth) - 34), showPct: dataType !== 'numeric', seriesLabel: 'Personas' });
      return built;
    }
    var cfg = buildChartConfig(chartType, buckets);
    var height = null;
    if (narrow && chartType === 'pie') height = Math.min(1000, 250 + n * 34);
    else if (narrow) height = 280;
    if (narrow && chartType === 'line') cfg.options.scales.x.ticks = Object.assign(cfg.options.scales.x.ticks, { maxRotation: 0, maxTicksLimit: 6 });
    return { config: cfg, height: height };
  }

  function buildChartConfig(chartType, buckets) {
    var colors = viz.palette(), labels = buckets.map(function (b) { return b.label; }), data = buckets.map(function (b) { return b.count; });
    var total = data.reduce(function (a, b) { return a + b; }, 0);
    var text = viz.token('--gw-text'), muted = viz.token('--gw-text-muted'), grid = viz.token('--gw-border'), surface = viz.token('--gw-surface');
    var pie = chartType === 'pie', line = chartType === 'line';
    /* Circular: nombre, cantidad y porcentaje en la leyenda (el color solo ayuda a ubicar). */
    var shown = pie ? labels.map(function (l, i) { return l + ' · ' + data[i] + (total ? ' (' + Math.round(100 * data[i] / total) + '%)' : ''); }) : labels;
    return {
      type: chartType,
      data: { labels: shown, datasets: [{
        label: 'Personas', data: data,
        backgroundColor: line ? colors[1] : labels.map(function (_, i) { return colors[i % colors.length]; }),
        borderColor: line ? colors[1] : surface, borderWidth: line ? 3 : 2, borderRadius: chartType === 'bar' ? 4 : undefined,
        fill: false, tension: line ? 0.3 : undefined, pointRadius: line ? 4 : undefined,
      }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: pie, position: 'bottom', labels: { color: text, font: { size: 14 } } }, tooltip: { titleFont: { size: 14 }, bodyFont: { size: 14 } } },
        scales: pie ? {} : { x: { grid: { color: grid }, ticks: { color: muted, font: { size: 13 } } }, y: { beginAtZero: true, grid: { color: grid }, ticks: { color: muted, precision: 0, font: { size: 13 } } } },
      },
    };
  }

  function render(key, label) {
    var c = cache[key]; if (!c) return;
    if (chartInstances[key]) chartInstances[key].destroy();
    c.canvas.setAttribute('role', 'img');
    c.canvas.setAttribute('aria-label', label + ': ' + c.result.buckets.slice(0, 12).map(function (b) { return b.label + ' ' + b.count; }).join('; '));
    var box = c.canvas.parentNode, plan = planChart(c.select.value, c.result.buckets, c.result.type, box);
    box.style.height = plan.height ? plan.height + 'px' : '';          // alto según el número de opciones (lo único que se fija por código)
    chartInstances[key] = new window.Chart(c.canvas, plan.config);
  }

  function loadVariables() {
    return fetch(BASE + '/stats/variables').then(function (res) { return res.json(); }).then(function (list) {
      variableSelect.textContent = '';
      list.forEach(function (v) { var o = el('option', null, v.label); o.value = v.key; variableSelect.appendChild(o); });
      // Las variables marcadas «Generar estadística» en Parámetros aparecen solas; el selector sigue sirviendo para agregar cualquier otra.
      list.filter(function (v) { return v.default_stat_enabled; }).forEach(function (v) { addVariableChart(v.key, v.label, v.default_chart_type); });
    }).catch(function () { toast('No se pudieron cargar las variables', 'error'); });
  }

  function addVariableChart(key, label, preferred) {
    if ($('stats-card-' + key)) { toast('Esa variable ya está agregada', 'error'); return Promise.resolve(); }
    var card = el('div', 'gw-chart-card'); card.id = 'stats-card-' + key;
    var head = el('div', 'gw-chart-card__head'); head.appendChild(el('h3', 'gw-chart-card__title', label));
    var tools = el('div', 'gw-chart-card__tools');
    var select = el('select', 'gw-select chart-type-select'); select.setAttribute('aria-label', 'Tipo de gráfico de ' + label);
    var rm = el('button', 'gw-btn gw-btn--secondary gw-btn--sm remove-chart-btn'); rm.type = 'button'; rm.setAttribute('aria-label', 'Quitar el gráfico de ' + label); rm.title = 'Quitar';
    rm.innerHTML = '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="' + (container.dataset.icons || '') + '#i-close"/></svg>';
    tools.append(select, rm); head.appendChild(tools);
    var msg = el('div', 'gw-chart-card__msg chart-loading'); msg.setAttribute('role', 'status');
    if (window.GW && window.GW.skeleton) msg.innerHTML = window.GW.skeleton.html({ kind: 'block', label: 'Cargando ' + label + '…' }); else msg.textContent = 'Cargando…';
    var box = el('div', 'gw-chart-card__box'); box.hidden = true; var canvas = document.createElement('canvas'); box.appendChild(canvas);
    card.append(head, msg, box);
    container.appendChild(card); updateEmptyMsg();
    rm.addEventListener('click', function () {
      if (chartInstances[key]) { chartInstances[key].destroy(); delete chartInstances[key]; }
      delete cache[key]; card.remove(); updateEmptyMsg();
    });
    return fetch(BASE + '/stats/data?variable=' + encodeURIComponent(key)).then(function (res) {
      return res.json().then(function (result) { if (!res.ok) throw new Error(result.detail || 'Error'); return result; });
    }).then(function (result) {
      var options = CHART_TYPES[result.type] || CHART_TYPES.categorical;
      options.forEach(function (o) { var op = el('option', null, o.label); op.value = o.value; select.appendChild(op); });
      if (!result.buckets.length) { msg.textContent = 'Sin datos suficientes para graficar esta variable todavía.'; select.hidden = true; return; }
      if (preferred) select.value = resolveChartType(preferred, result.type);
      msg.hidden = true; box.hidden = false;
      cache[key] = { result: result, select: select, canvas: canvas };
      render(key, label);
      select.addEventListener('change', function () { render(key, label); });
    }).catch(function () { msg.textContent = 'No se pudo cargar esta variable. Quítala y vuelve a agregarla.'; select.hidden = true; });
  }

  addBtn.addEventListener('click', function () {
    var key = variableSelect.value;
    var label = variableSelect.options[variableSelect.selectedIndex] ? variableSelect.options[variableSelect.selectedIndex].text : key;
    if (!key) return;
    busy(addBtn, function () { return addVariableChart(key, label); });
  });
  function redrawAll() { Object.keys(cache).forEach(function (k) { var t = $('stats-card-' + k); render(k, t ? t.querySelector('.gw-chart-card__title').textContent : k); }); }
  if (viz.onNarrow) viz.onNarrow(redrawAll);          // al girar el aparato o cruzar el límite de celular se vuelve a dibujar
  viz.onTheme(function () { Object.keys(cache).forEach(function (k) { var t = $('stats-card-' + k); render(k, t ? t.querySelector('.gw-chart-card__title').textContent : k); }); });
  loadVariables();
  updateEmptyMsg();
})();
