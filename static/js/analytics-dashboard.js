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

    function paintChart(spec, card) {
      const canvas = card.querySelector('canvas');
      if (charts[spec.id]) charts[spec.id].destroy();
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
          layout: opts.large ? { padding: { right: spec.horizontal ? 36 : 4, top: spec.horizontal ? 4 : 22 } } : {},
          plugins: { adValueLabels: { enabled: !!opts.large && !single }, legend: { display: single || spec.datasets.length > 1, position: 'bottom', labels: { color: text, font: { size: fs } } }, tooltip: { titleFont: { size: 14 }, bodyFont: { size: 14 } } },
          scales: single ? {} : { x: { stacked: !!spec.stacked, grid: { color: grid }, ticks: { color: muted, maxRotation: 60, autoSkip: !opts.large || !spec.horizontal, font: { size: fs } } }, y: { stacked: !!spec.stacked, beginAtZero: true, grid: { color: grid }, ticks: { color: muted, precision: 0, autoSkip: !(opts.large && spec.horizontal), font: { size: fs } } } },
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
        if (opts.large) {          // gráficas grandes: las barras horizontales crecen con la cantidad de opciones para que cada nombre se lea completo
          const h = spec.horizontal || spec.type === 'bar' && spec.labels.length > 8 && spec.labels.some((l) => String(l).length > 10) ? Math.max(320, spec.labels.length * 40 + 90) : 360;
          card.querySelector('.ad-box').style.height = Math.min(h, 900) + 'px';        // alto calculado con los datos: es lo único que se fija por código
        }
        card.querySelector('.ad-ct').textContent = spec.title;
        card.querySelector('.ad-note').textContent = spec.note || '';
        paintChart(spec, card);
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
