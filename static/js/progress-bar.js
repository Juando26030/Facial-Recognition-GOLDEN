/* Barra de progreso con tiempo estimado (Sprint 5), reutilizable en cualquier carga o proceso largo.

   const bar = ProgressBar.create(contenedor, { title: 'Cargando base de datos' });
   bar.update(0.42, 'Procesando fotos (17 de 40)');   // fracción 0..1 + etapa actual
   bar.finish('Listo: 200 personas');  |  bar.fail('No se pudo cargar');  |  bar.remove();

   El tiempo restante se calcula con el ritmo real observado (transcurrido / avance), suavizado para que no salte, y
   solo se muestra cuando ya hay datos suficientes (unos segundos y >3 % de avance): antes dice "calculando…". */
(function () {
  const fmtClock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  function fmtEta(seconds) {
    if (!isFinite(seconds) || seconds < 0) return 'calculando…';
    if (seconds < 45) return 'menos de 1 min';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `~${minutes} min`;
    const h = Math.floor(minutes / 60), m = minutes % 60;
    return m ? `~${h} h ${m} min` : `~${h} h`;
  }

  function create(container, opts) {
    opts = opts || {};
    const box = document.createElement('div');
    box.style.cssText = 'background:#e7f1ff; border:1px solid #b6d4fe; color:#084298; padding:1rem 1.2rem; border-radius:12px; font-size:0.85rem; margin-bottom:0.8rem;';
    box.innerHTML = `
      <div style="display:flex; justify-content:space-between; gap:10px; font-weight:700;"><span class="pb-title"></span><span class="pb-pct">0%</span></div>
      <div style="height:12px; background:#cfe2ff; border-radius:8px; overflow:hidden; margin:8px 0;"><div class="pb-fill" style="height:100%; width:0%; background:#0d6efd; border-radius:8px; transition:width .4s;"></div></div>
      <div class="pb-stage" style="font-size:0.82rem;"></div>
      <div class="pb-time" style="font-size:0.78rem; color:#3b6ab8; margin-top:2px;"></div>`;
    container.appendChild(box);
    const q = (c) => box.querySelector(c);
    q('.pb-title').textContent = opts.title || 'Procesando';

    const started = Date.now();
    let smoothedRate = null, lastFraction = 0, lastAt = started;   // rate = fracción por segundo

    function update(fraction, stage) {
      fraction = Math.max(0, Math.min(1, fraction || 0));
      const now = Date.now();
      const elapsed = (now - started) / 1000;
      if (fraction > lastFraction && now > lastAt) {
        const instant = (fraction - lastFraction) / ((now - lastAt) / 1000);
        smoothedRate = smoothedRate == null ? instant : smoothedRate * 0.7 + instant * 0.3;
        lastFraction = fraction; lastAt = now;
      }
      q('.pb-fill').style.width = `${(fraction * 100).toFixed(1)}%`;
      q('.pb-pct').textContent = `${Math.floor(fraction * 100)}%`;
      if (stage) q('.pb-stage').textContent = stage;
      // Ritmo promedio global (más estable al principio) mezclado con el reciente.
      const avgRate = elapsed > 0 ? fraction / elapsed : 0;
      const rate = smoothedRate ? (avgRate * 0.5 + smoothedRate * 0.5) : avgRate;
      const eta = fraction >= 0.03 && elapsed >= 3 && rate > 0 ? (1 - fraction) / rate : NaN;
      q('.pb-time').textContent = `Transcurrido ${fmtClock(elapsed)} · Tiempo restante estimado: ${fmtEta(eta)}`;
    }
    function finish(message) {
      box.style.background = '#d1e7dd'; box.style.borderColor = '#a3cfbb'; box.style.color = '#0a3622';
      q('.pb-fill').style.background = '#198754'; q('.pb-fill').style.width = '100%'; q('.pb-pct').textContent = '100%';
      q('.pb-stage').textContent = message || 'Listo';
      q('.pb-time').textContent = `Terminó en ${fmtClock((Date.now() - started) / 1000)}`;
    }
    function fail(message) {
      box.style.background = '#f8d7da'; box.style.borderColor = '#f1aeb5'; box.style.color = '#842029';
      q('.pb-fill').style.background = '#dc3545';
      q('.pb-stage').textContent = message || 'No se pudo completar';
      q('.pb-time').textContent = '';
    }
    function remove() { box.remove(); }
    update(0, opts.stage || 'Iniciando…');
    return { update, finish, fail, remove, element: box };
  }

  if (typeof window !== 'undefined') window.ProgressBar = { create, fmtEta };
  if (typeof module !== 'undefined') module.exports = { fmtEta };
})();
