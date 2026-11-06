/* Componente de analítica compartido (Sprint 5): dibuja un "tablero" (KPIs + gráficos) que entrega el servidor con el
   formato de app/analytics.py. Sirve igual para el Registro del evento y para los Formularios Web.

     AnalyticsDashboard.mount(contenedor, url, { refreshSeconds: 30 })

   Requiere Chart.js (CDN) cargado antes. Cada gráfico se destruye y se vuelve a crear en cada refresco. */
(function () {
  /* Colores de los gráficos: paleta de datos accesible (tokens --gw-viz-1..8 de static/css/gw-estadisticas.css, con su versión para tema oscuro). Si la pantalla
     no los define (p. ej. el editor de formularios, que aún no se rediseña) se usa la misma paleta clara escrita aquí como respaldo. */
  const VIZ_FALLBACK = ['#1e2a6e', '#b8862b', '#0f766e', '#b3365a', '#6a3fa0', '#c25e00', '#2c7bb6', '#6b7a2c'];
  const TOKEN_FALLBACK = { '--gw-text': '#12183f', '--gw-text-muted': '#4a5273', '--gw-border': '#d3d7e8', '--gw-surface': '#ffffff' };
  const token = (name) => { try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || TOKEN_FALLBACK[name] || ''; } catch (e) { return TOKEN_FALLBACK[name] || ''; } };
  const palette = () => VIZ_FALLBACK.map((c, i) => token('--gw-viz-' + (i + 1)) || c);
  /* Se ofrece a los demás scripts de Estadísticas: GWViz.palette(), GWViz.token(nombre), GWViz.onTheme(fn) (vuelve a dibujar al cambiar de tema claro/oscuro). */
  window.GWViz = window.GWViz || {
    palette, token,
    onTheme(fn) { try { new MutationObserver(fn).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] }); } catch (e) { /* sin observador: se queda con el tema con el que cargó */ } },
  };
  const GWViz = window.GWViz;
  /* Gráficos de barras legibles en celular (Fase 1.7, M5). Hasta 720 px (celular) cada categoría es una FILA: el nombre completo (hasta 3 líneas, sin rotar) arriba,
     la barra a casi todo el ancho y la cantidad (y el porcentaje) siempre visibles al final; el alto crece con el número de categorías. El tooltip queda como extra. */
  const NARROW_MQ = '(max-width: 720px)';
  const mq = () => { try { return window.matchMedia(NARROW_MQ); } catch (e) { return null; } };
  GWViz.narrow = GWViz.narrow || (() => { const m = mq(); return !!(m && m.matches); });
  GWViz.onNarrow = GWViz.onNarrow || ((fn) => { const m = mq(); if (!m) return; if (m.addEventListener) m.addEventListener('change', fn); else if (m.addListener) m.addListener(fn); });
  /* Parte un texto en renglones de a lo sumo `max` caracteres (por palabras) y recorta con «…» pasado `maxLines`. */
  GWViz.wrap = GWViz.wrap || ((text, max, maxLines) => {
    const words = String(text == null ? '' : text).split(/\s+/).filter(Boolean); const lines = []; let cur = '';
    words.forEach((w) => { if (cur && (cur + ' ' + w).length > max) { lines.push(cur); cur = w; } else cur = cur ? cur + ' ' + w : w; });
    if (cur) lines.push(cur);
    if (maxLines && lines.length > maxLines) { const keep = lines.slice(0, maxLines); keep[maxLines - 1] = keep[maxLines - 1].replace(/.{1}$/, '') + '…'; return keep; }
    return lines.length ? lines : [''];
  });
  const ROW_BAR = 24, ROW_LINE = 18;
  /* Plan de filas: alto del lienzo y relleno para `labels` en un ancho disponible `width` (px). */
  GWViz.rowPlan = GWViz.rowPlan || ((labels, texts, width) => {
    const perLine = Math.max(12, Math.floor((width - 8) / 7.8));
    const lines = Math.max(1, Math.min(3, Math.max.apply(null, labels.map((l) => Math.ceil(String(l).length / perLine) || 1))));
    const rowH = ROW_BAR + ROW_LINE * lines + 12;
    const padTop = Math.max(0, ROW_LINE * lines + 4 - Math.round((rowH - ROW_BAR) / 2));
    const padRight = Math.max.apply(null, texts.map((t) => String(t).length)) * 9 + 14;
    return { lines, rowH, padTop, padRight, height: Math.min(1600, labels.length * rowH + padTop + 10) };
  });
  /* Dibuja, por barra, el nombre (arriba) y el valor (al final). Opciones en plugins.gwRows = { labels, texts, lines }. */
  GWViz.rowsPlugin = GWViz.rowsPlugin || {
    id: 'gwRows',
    afterDatasetsDraw(chart, _a, o) {
      if (!o || !o.labels) return;
      const ctx = chart.ctx, meta = chart.getDatasetMeta(0), left = 2, maxW = chart.width - 6;
      const fit = (t) => { const words = String(t).split(/\s+/); const out = []; let cur = '';
        words.forEach((w) => { const probe = cur ? cur + ' ' + w : w; if (cur && ctx.measureText(probe).width > maxW) { out.push(cur); cur = w; } else cur = probe; });
        out.push(cur); if (out.length > o.lines) { out.length = o.lines; let last = out[o.lines - 1]; while (last.length > 1 && ctx.measureText(last + '…').width > maxW) last = last.slice(0, -1); out[o.lines - 1] = last + '…'; }
        return out; };
      ctx.save(); ctx.fillStyle = token('--gw-text'); ctx.textBaseline = 'alphabetic';
      meta.data.forEach((bar, i) => {
        const top = bar.y - bar.height / 2;
        ctx.font = '600 14px system-ui, sans-serif'; ctx.textAlign = 'left';
        const lines = fit(o.labels[i]);
        lines.forEach((ln, k) => ctx.fillText(ln, left, top - 6 - (lines.length - 1 - k) * ROW_LINE));
        ctx.font = '700 15px system-ui, sans-serif'; ctx.textBaseline = 'middle';
        ctx.fillText(o.texts[i], Math.max(bar.x, chart.chartArea.left) + 8, bar.y); ctx.textBaseline = 'alphabetic';
      });
      ctx.restore();
    },
  };
  /* Barras en filas para UNA serie. Devuelve { config, height } listo para `new Chart(canvas, config)`. */
  GWViz.rowBars = GWViz.rowBars || ((labels, values, o) => {
    o = o || {};
    const total = values.reduce((a, b) => a + (Number(b) || 0), 0);
    const texts = values.map((v) => String(v) + (o.showPct && total ? ' · ' + Math.round(100 * v / total) + '%' : ''));
    const plan = GWViz.rowPlan(labels, texts, o.width || 330);
    return { height: plan.height, config: {
      type: 'bar',
      data: { labels, datasets: [{ label: o.seriesLabel || 'Cantidad', data: values, backgroundColor: o.color || palette()[0], borderRadius: 4, barThickness: ROW_BAR }] },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, layout: { padding: { top: plan.padTop, right: plan.padRight, bottom: 4, left: 0 } },
        plugins: { legend: { display: false }, gwRows: { labels, texts, lines: plan.lines }, tooltip: { titleFont: { size: 14 }, bodyFont: { size: 14 } } },
        scales: { x: { display: false, beginAtZero: true, grid: { display: false } }, y: { display: false, grid: { display: false } } } },
      plugins: [GWViz.rowsPlugin],
    } };
  });
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const TONE_CLASS = { good: ' ad-kpi--good', warn: ' ad-kpi--warn', bad: ' ad-kpi--bad' };

  /* Estilos propios del panel (solo tokens --gw-*; se inyectan una vez, así el panel se ve igual donde se monte). */
  function injectStyles() {
    if (document.getElementById('adStyles')) return;
    const st = document.createElement('style'); st.id = 'adStyles';
    st.textContent = `
      .ad-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: var(--gw-sp-3); margin-bottom: var(--gw-sp-3); }
      .ad-title { margin: 0; font-size: var(--gw-fs-xl); font-weight: var(--gw-fw-bold); color: var(--gw-text); }
      .ad-tools { display: flex; align-items: center; flex-wrap: wrap; gap: var(--gw-sp-3); }
      .ad-updated { font-size: var(--gw-fs-sm); color: var(--gw-text-muted); }
      .ad-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr)); gap: var(--gw-sp-3); margin-bottom: var(--gw-sp-4); }
      .ad-kpi { display: flex; flex-direction: column; gap: var(--gw-sp-1); padding: var(--gw-sp-3) var(--gw-sp-4); background: var(--gw-surface); border: 1px solid var(--gw-border); border-radius: var(--gw-radius-md); box-shadow: var(--gw-shadow-sm); }
      .ad-kpi__label { font-size: var(--gw-fs-sm); font-weight: var(--gw-fw-bold); color: var(--gw-text-muted); letter-spacing: .04em; text-transform: uppercase; }
      .ad-kpi__value { font-size: var(--gw-fs-2xl); font-weight: var(--gw-fw-bold); line-height: var(--gw-lh-tight); color: var(--gw-text); overflow-wrap: anywhere; }
      .ad-kpi__hint { font-size: var(--gw-fs-sm); color: var(--gw-text-muted); }
      .ad-kpi--good .ad-kpi__value { color: var(--gw-ok-text); }
      .ad-kpi--warn .ad-kpi__value { color: var(--gw-warn-text); }
      .ad-kpi--bad .ad-kpi__value { color: var(--gw-err-text); }
      .ad-charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr)); gap: var(--gw-sp-4); }
      .ad-charts--large { grid-template-columns: repeat(auto-fit, minmax(min(100%, 28rem), 1fr)); }
      .ad-card { min-width: 0; padding: var(--gw-sp-4); background: var(--gw-surface); border: 1px solid var(--gw-border); border-radius: var(--gw-radius-md); box-shadow: var(--gw-shadow-sm); }
      .ad-ct { margin-bottom: var(--gw-sp-2); font-size: var(--gw-fs-lg); font-weight: var(--gw-fw-bold); color: var(--gw-text); overflow-wrap: anywhere; }
      .ad-box { position: relative; height: 260px; }
      .ad-note { margin-top: var(--gw-sp-2); font-size: var(--gw-fs-sm); color: var(--gw-text-muted); }
      .ad-empty { padding: var(--gw-sp-5); text-align: center; color: var(--gw-text-muted); }
      .ad-empty[hidden] { display: none; }
      .ad-refresh { display: inline-flex; align-items: center; justify-content: center; min-height: var(--gw-tap); padding: var(--gw-sp-2) var(--gw-sp-4); font: inherit; font-size: var(--gw-fs-sm); font-weight: var(--gw-fw-bold); color: var(--gw-secondary-text); background: var(--gw-secondary-bg); border: 2px solid var(--gw-border-strong); border-radius: var(--gw-radius-md); cursor: pointer; }
      .ad-refresh:hover { border-color: var(--gw-text); }
      .ad-refresh[aria-busy="true"] { cursor: progress; opacity: .7; }
      @media (max-width: 768px) { .ad-box { height: 240px; } }`;
    document.head.appendChild(st);
  }

  /* Cantidad visible en cada barra / porción (solo con { large: true }): se dibuja al final de la barra, en tamaño legible. */
  const valueLabels = {
    id: 'adValueLabels',
    afterDatasetsDraw(chart, _args, o) {
      if (!o || !o.enabled) return;
      const ctx = chart.ctx; const horizontal = chart.options.indexAxis === 'y';
      ctx.save(); ctx.font = '700 14px system-ui, sans-serif'; ctx.textBaseline = 'middle'; ctx.fillStyle = token('--gw-text');
      chart.data.datasets.forEach((ds, di) => {
        if (chart.config.type !== 'bar' || chart.isDatasetVisible(di) === false) return;
        chart.getDatasetMeta(di).data.forEach((bar, i) => {
          const v = ds.data[i]; if (v == null || (v === 0 && chart.data.datasets.length > 1)) return;
          if (horizontal) { ctx.textAlign = 'left'; ctx.fillText(String(v), bar.x + 6, bar.y); }
          else { ctx.textAlign = 'center'; ctx.textBaseline = 'bottom'; ctx.fillText(String(v), bar.x, bar.y - 4); ctx.textBaseline = 'middle'; }
        });
      });
      ctx.restore();
    },
  };

  function mount(container, url, opts) {
    opts = opts || {};
    injectStyles();
    container.innerHTML = `
      <div class="ad-head">
        <h3 class="ad-title">Panel de analítica</h3>
        <div class="ad-tools"><span class="ad-updated" role="status" aria-live="polite"></span>
          <button type="button" class="ad-refresh">Actualizar</button></div>
      </div>
      ${opts.stats ? '<p class="ad-state" role="status">Cargando las cifras…</p>' : ''}
      <div class="ad-kpis"></div>
      <div class="ad-charts${opts.large ? ' ad-charts--large' : ''}${opts.stats ? ' ad-charts--wide' : ''}"></div>
      <p class="ad-empty" hidden>Todavía no hay datos para mostrar. Aparecen aquí apenas llegue el primer registro.</p>`;
    const q = (c) => container.querySelector(c);
    const charts = {};
    let timer = null;
    let lastData = null;

    /* Presentación en celular: filas (una serie, categorías), barras con nombres envueltos (varias series) o alto según la leyenda (circular). Devuelve el alto del lienzo o null. */
    function narrowPlan(spec, card) {
      if (!GWViz.narrow()) return null;
      const n = spec.labels.length, w = Math.max(240, (card.clientWidth || window.innerWidth) - 34);
      const longest = Math.max.apply(null, spec.labels.map((l) => String(l).length).concat([0]));
      if (spec.type === 'bar' && spec.datasets.length === 1 && (spec.horizontal || n > 6 || longest > 10)) {
        const dated = spec.labels.every((l) => /^[\d\s\-/:.hH]+$/.test(String(l)));        // fechas y horas conservan su orden
        let idx = spec.labels.map((_, k) => k);
        if (n > 5 && !dated) idx.sort((a, b) => (Number(spec.datasets[0].data[b]) || 0) - (Number(spec.datasets[0].data[a]) || 0));        // muchas opciones: de mayor a menor
        return { kind: 'rows', idx, width: w };
      }
      if (spec.type === 'bar' && spec.horizontal) return { kind: 'hwrap', height: Math.min(1600, n * 58 + 120) };
      if (spec.type === 'pie') return { kind: 'pie', height: Math.min(1000, 250 + n * 34) };
      if (spec.type === 'line') return { kind: 'line', height: 280 };
      return null;
    }

    function paintChart(spec, card, np) {
      const canvas = card.querySelector('canvas');
      if (charts[spec.id]) charts[spec.id].destroy();
      if (np && np.kind === 'rows') {
        const labels = np.idx.map((k) => spec.labels[k]), values = np.idx.map((k) => spec.datasets[0].data[k]);
        const built = GWViz.rowBars(labels, values, { width: np.width, seriesLabel: spec.datasets[0].label });
        card.querySelector('.ad-box').style.height = built.height + 'px';        // alto según el número de categorías
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', spec.title + '. ' + labels.slice(0, 12).map((l, k) => l + ': ' + values[k]).join('; '));
        charts[spec.id] = new Chart(canvas, built.config);
        return;
      }
      const single = spec.type === 'pie';
      const colors = palette();
      const text = token('--gw-text'), muted = token('--gw-text-muted'), grid = token('--gw-border'), surface = token('--gw-surface');
      const total = single ? spec.datasets[0].data.reduce((a, b) => a + (Number(b) || 0), 0) : 0;
      /* Porciones: el nombre, la cantidad y el porcentaje van en la leyenda (el color solo ayuda a ubicar). */
      const labels = single ? spec.labels.map((l, k) => `${l} · ${spec.datasets[0].data[k]}${total ? ' (' + Math.round(100 * spec.datasets[0].data[k] / total) + '%)' : ''}`) : spec.labels;
      const datasets = spec.datasets.map((d, i) => {
        const color = colors[i % colors.length];
        if (single) return { label: d.label, data: d.data, backgroundColor: spec.labels.map((_, k) => colors[k % colors.length]), borderColor: surface, borderWidth: 2 };
        if (spec.type === 'line') return { label: d.label, data: d.data, borderColor: color, backgroundColor: color + '33', tension: 0.3, fill: i === 0, borderWidth: 3, pointRadius: spec.labels.length > 40 ? 0 : 3 };
        return { label: d.label, data: d.data, backgroundColor: spec.stacked ? (i === 0 ? colors[2] : colors[1]) : color, borderRadius: 4 };
      });
      const fs = opts.large ? 14 : 13;
      canvas.setAttribute('role', 'img');
      canvas.setAttribute('aria-label', spec.title + '. ' + spec.labels.slice(0, 12).map((l, k) => l + ': ' + (spec.datasets[0].data[k] != null ? spec.datasets[0].data[k] : '')).join('; '));
      charts[spec.id] = new Chart(canvas, {
        type: spec.type === 'pie' ? 'doughnut' : spec.type,
        data: { labels, datasets },
        options: {
          indexAxis: spec.horizontal ? 'y' : 'x', responsive: true, maintainAspectRatio: false,
          layout: opts.large || (np && np.kind === 'hwrap') ? { padding: { right: spec.horizontal ? 36 : 4, top: spec.horizontal ? 4 : 22 } } : {},
          plugins: { adValueLabels: { enabled: (!!opts.large || !!(np && np.kind === 'hwrap')) && !single }, legend: { display: single || spec.datasets.length > 1, position: 'bottom', labels: { color: text, font: { size: fs } } }, tooltip: { titleFont: { size: 14 }, bodyFont: { size: 14 } } },
          scales: single ? {} : { x: { stacked: !!spec.stacked, grid: { color: grid }, ticks: { color: muted, maxRotation: np && np.kind === 'line' ? 0 : 60, maxTicksLimit: np ? 6 : undefined, autoSkip: !opts.large || !spec.horizontal, font: { size: fs } } }, y: { stacked: !!spec.stacked, beginAtZero: true, grid: { color: grid }, ticks: Object.assign({ color: muted, precision: 0, autoSkip: !(opts.large && spec.horizontal), font: { size: fs } }, np && np.kind === 'hwrap' ? { autoSkip: false, callback(v) { return GWViz.wrap(this.getLabelForValue(v), 16, 3); } } : {}) } },
        },
        plugins: [valueLabels],
      });
    }

    /* Modo { stats: true } (Estadísticas del evento): las 3 primeras cifras van grandes (.gw-stat dentro de .gw-stats-row) y las demás quedan como cifras pequeñas debajo. */
    function paintStats(kpis) {
      const icon = (n) => `<svg class="gw-icon gw-stat__icon" aria-hidden="true"><use href="${esc(opts.icons || '')}#i-${n}"/></svg>`;
      const ICONS = ['users', 'check', 'clock'];
      const big = kpis.slice(0, 3), rest = kpis.slice(3);
      const cls = { good: ' gw-stat--ok', warn: ' gw-stat--warn', bad: ' gw-stat--err' };
      q('.ad-kpis').className = 'ad-kpis ad-kpis--stats';
      q('.ad-kpis').innerHTML = `<div class="gw-stats-row${big.length === 2 ? ' gw-stats-row--2' : ''}">` + big.map((k, i) => `<div class="gw-stat${cls[k.tone] || ''}">${icon(ICONS[i])}
        <div class="gw-stat__value">${esc(k.value)}</div><div class="gw-stat__label">${esc(k.label)}</div><div class="gw-stat__hint">${esc(k.hint)}</div></div>`).join('') + '</div>'
        + (rest.length ? '<div class="ad-kpis">' + rest.map((k) => `<div class="ad-kpi${TONE_CLASS[k.tone] || ''}"><div class="ad-kpi__label">${esc(k.label)}</div><div class="ad-kpi__value">${esc(k.value)}</div><div class="ad-kpi__hint">${esc(k.hint)}</div></div>`).join('') + '</div>' : '');
    }

    function paint(data) {
      lastData = data;
      const st = q('.ad-state'); if (st) st.hidden = true;
      q('.ad-title').textContent = data.title || 'Panel de analítica';
      q('.ad-updated').textContent = 'Actualizado ' + new Date(data.generated_at).toLocaleTimeString();
      if (opts.stats) paintStats(data.kpis);
      else q('.ad-kpis').innerHTML = data.kpis.map((k) => `<div class="ad-kpi${TONE_CLASS[k.tone] || ''}">
        <div class="ad-kpi__label">${esc(k.label)}</div>
        <div class="ad-kpi__value">${esc(k.value)}</div>
        <div class="ad-kpi__hint">${esc(k.hint)}</div></div>`).join('');
      const host = q('.ad-charts');
      const wanted = new Set(data.charts.map((c) => c.id));
      Object.keys(charts).forEach((id) => { if (!wanted.has(id)) { charts[id].destroy(); delete charts[id]; } });
      host.querySelectorAll('[data-chart]').forEach((el) => { if (!wanted.has(el.dataset.chart)) el.remove(); });
      data.charts.forEach((spec) => {
        let card = host.querySelector(`[data-chart="${spec.id}"]`);
        if (!card) {
          card = document.createElement('div'); card.dataset.chart = spec.id; card.className = 'ad-card';
          card.innerHTML = '<h4 class="ad-ct"></h4><div class="ad-box"><canvas></canvas></div><div class="ad-note"></div>';
          host.appendChild(card);
        }
        const np = narrowPlan(spec, card);
        const box = card.querySelector('.ad-box');
        box.style.height = '';
        if (np && np.height) box.style.height = np.height + 'px';
        else if (opts.large) {          // gráficas grandes: las barras horizontales crecen con la cantidad de opciones para que cada nombre se lea completo
          const h = spec.horizontal || spec.type === 'bar' && spec.labels.length > 8 && spec.labels.some((l) => String(l).length > 10) ? Math.max(320, spec.labels.length * 40 + 90) : 360;
          box.style.height = Math.min(h, 900) + 'px';        // alto calculado con los datos: es lo único que se fija por código
        }
        card.querySelector('.ad-ct').textContent = spec.title;
        card.querySelector('.ad-note').textContent = spec.note || '';
        paintChart(spec, card, np);
      });
      q('.ad-empty').hidden = !!(data.charts.length || data.kpis.some((k) => Number(k.value) > 0));
    }

    async function load() {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'No se pudo cargar la analítica');
        paint(await res.json());
      } catch (e) {
        q('.ad-updated').textContent = e.message;
        const st = q('.ad-state'); if (st && !lastData) { st.hidden = false; st.className = 'ad-state ad-state--err'; st.textContent = e.message + '. Usa «Actualizar» para intentar de nuevo.'; }
      }
    }
    const refresh = q('.ad-refresh');
    refresh.addEventListener('click', () => { if (window.GW && window.GW.busy) window.GW.busy(refresh, load).catch(() => {}); else load(); });
    window.GWViz.onNarrow(() => { if (lastData && document.body.contains(container)) paint(lastData); });          // cruza el límite de celular (girar el aparato): se redibuja
    window.GWViz.onTheme(() => { if (lastData && document.body.contains(container)) paint(lastData); });          // otro tema: se vuelve a dibujar con sus colores
    load();
    if (opts.refreshSeconds) {
      const again = () => { if (document.body.contains(container)) load(); else clearInterval(timer); };
      timer = window.GW && window.GW.poll ? window.GW.poll(again, opts.refreshSeconds * 1000) : setInterval(again, opts.refreshSeconds * 1000);      // pausado mientras la pestaña no se usa (GW.idle)
    }
    return { reload: load };
  }

  window.AnalyticsDashboard = { mount };
})();
