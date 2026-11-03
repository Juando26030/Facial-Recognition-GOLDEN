/* Componente de analítica compartido (Sprint 5): dibuja un "tablero" (KPIs + gráficos) que entrega el servidor con el
   formato de app/analytics.py. Sirve igual para el Registro del evento y para los Formularios Web.

     AnalyticsDashboard.mount(contenedor, url, { refreshSeconds: 30 })

   Requiere Chart.js (CDN) cargado antes. Cada gráfico se destruye y se vuelve a crear en cada refresco. */
(function () {
  const PALETTE = ['#D4AF37', '#0A0E2E', '#3F7CAC', '#2E9E6B', '#C0392B', '#8E5BB5', '#E08E45', '#5DADE2', '#7F8C8D', '#B8941F'];
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const TONES = { good: '#198754', warn: '#b26a00', bad: '#c0392b', '': '#0A0E2E' };

  /* Cantidad visible en cada barra / porción (solo con { large: true }): se dibuja al final de la barra, en tamaño legible. */
  const valueLabels = {
    id: 'adValueLabels',
    afterDatasetsDraw(chart, _args, o) {
      if (!o || !o.enabled) return;
      const ctx = chart.ctx; const horizontal = chart.options.indexAxis === 'y';
      ctx.save(); ctx.font = '700 14px system-ui, sans-serif'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#12183f';
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
    container.innerHTML = `
      <div class="ad-head" style="display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:0.8rem;">
        <h4 class="ad-title" style="margin:0; color:var(--golden-dark);">Panel de analítica</h4>
        <div style="display:flex; gap:10px; align-items:center;"><span class="ad-updated" style="font-size:0.75rem; color:#888;"></span>
          <button type="button" class="ad-refresh" style="border:1px solid #ccc; background:white; border-radius:18px; padding:5px 14px; font-size:0.78rem; cursor:pointer;">↻ Actualizar</button></div>
      </div>
      <div class="ad-kpis" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 150px), 1fr)); gap:0.8rem; margin-bottom:1.2rem;"></div>
      <div class="ad-charts" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, ${opts.large ? 460 : 380}px), 1fr)); gap:1.2rem;"></div>
      <p class="ad-empty" style="display:none; color:#888; text-align:center; padding:1.5rem;">Todavía no hay datos para mostrar.</p>`;
    const q = (c) => container.querySelector(c);
    const charts = {};
    let timer = null;

    function paintChart(spec, card) {
      const canvas = card.querySelector('canvas');
      if (charts[spec.id]) charts[spec.id].destroy();
      const single = spec.type === 'pie';
      const datasets = spec.datasets.map((d, i) => {
        const color = PALETTE[i % PALETTE.length];
        if (single) return { label: d.label, data: d.data, backgroundColor: spec.labels.map((_, k) => PALETTE[k % PALETTE.length]), borderColor: '#fff', borderWidth: 2 };
        if (spec.type === 'line') return { label: d.label, data: d.data, borderColor: color, backgroundColor: color + '33', tension: 0.3, fill: i === 0, pointRadius: spec.labels.length > 40 ? 0 : 3 };
        return { label: d.label, data: d.data, backgroundColor: spec.stacked ? (i === 0 ? '#2E9E6B' : '#E5C77A') : color, borderRadius: 4 };
      });
      charts[spec.id] = new Chart(canvas, {
        type: spec.type === 'pie' ? 'doughnut' : spec.type,
        data: { labels: spec.labels, datasets },
        options: {
          indexAxis: spec.horizontal ? 'y' : 'x', responsive: true, maintainAspectRatio: false,
          layout: opts.large ? { padding: { right: spec.horizontal ? 36 : 4, top: spec.horizontal ? 4 : 22 } } : {},
          plugins: { adValueLabels: { enabled: !!opts.large && !single }, legend: { display: single || spec.datasets.length > 1, position: 'bottom', labels: { font: { size: opts.large ? 14 : 12 } } }, tooltip: opts.large ? { titleFont: { size: 14 }, bodyFont: { size: 14 } } : {} },
          scales: single ? {} : { x: { stacked: !!spec.stacked, ticks: { maxRotation: 60, autoSkip: !opts.large || !spec.horizontal, font: { size: opts.large ? 14 : 12 } } }, y: { stacked: !!spec.stacked, beginAtZero: true, ticks: { precision: 0, autoSkip: !(opts.large && spec.horizontal), font: { size: opts.large ? 14 : 12 } } } },
        },
        plugins: [valueLabels],
      });
    }

    function paint(data) {
      q('.ad-title').textContent = data.title || 'Panel de analítica';
      q('.ad-updated').textContent = 'Actualizado ' + new Date(data.generated_at).toLocaleTimeString();
      q('.ad-kpis').innerHTML = data.kpis.map((k) => `<div style="background:white; border-radius:14px; padding:0.8rem 1rem; box-shadow:0 4px 16px rgba(0,0,0,0.06);">
        <div style="font-size:0.72rem; color:#888; text-transform:uppercase; letter-spacing:.5px;">${esc(k.label)}</div>
        <div style="font-size:1.55rem; font-weight:800; color:${TONES[k.tone] || TONES['']}; line-height:1.2;">${esc(k.value)}</div>
        <div style="font-size:0.72rem; color:#999;">${esc(k.hint)}</div></div>`).join('');
      const host = q('.ad-charts');
      const wanted = new Set(data.charts.map((c) => c.id));
      Object.keys(charts).forEach((id) => { if (!wanted.has(id)) { charts[id].destroy(); delete charts[id]; } });
      host.querySelectorAll('[data-chart]').forEach((el) => { if (!wanted.has(el.dataset.chart)) el.remove(); });
      data.charts.forEach((spec) => {
        let card = host.querySelector(`[data-chart="${spec.id}"]`);
        if (!card) {
          card = document.createElement('div'); card.dataset.chart = spec.id;
          card.style.cssText = 'background:white; border-radius:16px; padding:1rem 1.2rem; box-shadow:0 4px 16px rgba(0,0,0,0.06);';
          card.innerHTML = `<div class="ad-ct" style="font-weight:700; font-size:0.88rem; color:var(--golden-dark); margin-bottom:6px;"></div><div class="ad-box" style="height:250px;"><canvas></canvas></div><div class="ad-note" style="font-size:0.72rem; color:#999;"></div>`;
          host.appendChild(card);
        }
        if (opts.large) {          // gráficas grandes: las barras horizontales crecen con la cantidad de opciones para que cada nombre se lea completo
          const h = spec.horizontal || spec.type === 'bar' && spec.labels.length > 8 && spec.labels.some((l) => String(l).length > 10) ? Math.max(320, spec.labels.length * 40 + 90) : 360;
          card.querySelector('.ad-box').style.height = Math.min(h, 900) + 'px';
          card.querySelector('.ad-ct').style.fontSize = '1.05rem';
        }
        card.querySelector('.ad-ct').textContent = spec.title;
        card.querySelector('.ad-note').textContent = spec.note || '';
        paintChart(spec, card);
      });
      q('.ad-empty').style.display = data.charts.length || data.kpis.some((k) => Number(k.value) > 0) ? 'none' : 'block';
    }

    async function load() {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'No se pudo cargar la analítica');
        paint(await res.json());
      } catch (e) { q('.ad-updated').textContent = e.message; }
    }
    q('.ad-refresh').addEventListener('click', load);
    load();
    if (opts.refreshSeconds) {
      const again = () => { if (document.body.contains(container)) load(); else clearInterval(timer); };
      timer = window.GW && window.GW.poll ? window.GW.poll(again, opts.refreshSeconds * 1000) : setInterval(again, opts.refreshSeconds * 1000);      // pausado mientras la pestaña no se usa (GW.idle)
    }
    return { reload: load };
  }

  window.AnalyticsDashboard = { mount };
})();
