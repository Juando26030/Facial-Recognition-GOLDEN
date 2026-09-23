/* Dibujo y animación de la ruleta (Sprint 5) — compartido por la pantalla del proyector (/r/<token>), la vista previa de la
   configuración visual y la de comportamiento. Solo sabe DIBUJAR y ANIMAR: el ganador ya viene decidido por el servidor.

   RouletteRender.wheel(canvas, style)            -> { draw(names, angle), spinTo(names, winnerIndex, seconds) : Promise }
   RouletteRender.buildSegments(pool, winner, n)  -> { names, winnerIndex }   (n segmentos que SIEMPRE incluyen al ganador)
   RouletteRender.fontsUrl(families)              -> URL de Google Fonts
   RouletteRender.applyBackground(el, style, assetUrl)
   RouletteRender.reveal(container, winner, style)  -> pinta la tarjeta del ganador                                          */
(function () {
  const TAU = Math.PI * 2;

  function fontsUrl(families) {
    const list = Array.from(new Set(families.filter(Boolean))).map((f) => 'family=' + encodeURIComponent(f).replace(/%20/g, '+') + ':wght@400;700');
    return 'https://fonts.googleapis.com/css2?' + list.join('&') + '&display=swap';
  }

  function applyBackground(el, style, assetUrl) {
    el.style.backgroundColor = style.background_color || '#0A0E2E';
    if (style.background_image) {
      el.style.backgroundImage = `url(${assetUrl(style.background_image)})`;
      el.style.backgroundSize = 'cover'; el.style.backgroundPosition = 'center';
    } else {
      el.style.backgroundImage = 'none';
    }
    el.style.color = style.text_color || '#FFFFFF';
    el.style.fontFamily = `'${style.font_family || 'Montserrat'}', sans-serif`;
  }

  // n segmentos (mín. 4, máx. 24) tomados del pool, con el ganador en una posición al azar.
  function buildSegments(pool, winner, n) {
    const others = Array.from(new Set((pool || []).filter((x) => x && x !== winner)));
    for (let i = others.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [others[i], others[j]] = [others[j], others[i]]; }
    const total = Math.max(4, Math.min(24, n || others.length + 1));
    const names = others.slice(0, total - 1);
    while (names.length < total - 1) names.push('·');            // pocas personas: se rellena para que la ruleta no quede vacía
    const winnerIndex = Math.floor(Math.random() * total);
    names.splice(winnerIndex, 0, winner);
    return { names, winnerIndex };
  }

  function wheel(canvas, style) {
    const ctx = canvas.getContext('2d');
    const colors = style.colors && style.colors.length ? style.colors : ['#D4AF37', '#0A0E2E'];
    let current = 0;

    function draw(names, angle) {
      current = angle;
      const w = canvas.width, h = canvas.height, cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - 18;
      ctx.clearRect(0, 0, w, h);
      const n = names.length, step = TAU / n;
      for (let i = 0; i < n; i++) {
        // segmento 0 empieza arriba (-90°) y `angle` rota toda la rueda
        const a0 = angle - Math.PI / 2 + i * step, a1 = a0 + step;
        let color = colors[i % colors.length];
        if (n % colors.length === 1 && i === n - 1) color = colors[(i + 1) % colors.length];   // que el último no choque con el primero
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, r, a0, a1); ctx.closePath();
        ctx.fillStyle = color; ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 2; ctx.stroke();
        ctx.save();
        ctx.translate(cx, cy); ctx.rotate((a0 + a1) / 2);
        ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
        ctx.fillStyle = luminance(color) > 0.55 ? '#111' : '#fff';
        const label = names[i].length > 22 ? names[i].slice(0, 21) + '…' : names[i];
        const size = Math.max(11, Math.min(26, (r * step) / 1.9, 520 / (label.length + 6)));
        ctx.font = `700 ${size}px '${style.font_family || 'Montserrat'}', sans-serif`;
        ctx.fillText(label, r - 16, 0);
        ctx.restore();
      }
      // borde y centro
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, TAU); ctx.lineWidth = 8; ctx.strokeStyle = style.pointer_color || '#FF4D6D'; ctx.stroke();
      ctx.beginPath(); ctx.arc(cx, cy, 26, 0, TAU); ctx.fillStyle = '#fff'; ctx.fill(); ctx.lineWidth = 4; ctx.strokeStyle = style.pointer_color || '#FF4D6D'; ctx.stroke();
      // puntero fijo arriba
      ctx.beginPath(); ctx.moveTo(cx - 20, 4); ctx.lineTo(cx + 20, 4); ctx.lineTo(cx, 46); ctx.closePath();
      ctx.fillStyle = style.pointer_color || '#FF4D6D'; ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 3; ctx.stroke();
    }

    // Gira varias vueltas y frena con el segmento `winnerIndex` bajo el puntero (arriba).
    function spinTo(names, winnerIndex, seconds) {
      const n = names.length, step = TAU / n;
      const target = -(winnerIndex + 0.5) * step + (Math.random() - 0.5) * step * 0.6;   // centro del segmento ± un poco
      const start = ((current % TAU) + TAU) % TAU;
      const end = target + TAU * (5 + Math.floor(Math.random() * 3));
      const duration = Math.max(2, seconds || 6) * 1000;
      const t0 = performance.now();
      return new Promise((resolve) => {
        function frame(now) {
          const p = Math.min(1, (now - t0) / duration);
          const eased = 1 - Math.pow(1 - p, 4);                     // frena suave al final
          draw(names, start + (end - start) * eased);
          if (p < 1) requestAnimationFrame(frame); else resolve();
        }
        requestAnimationFrame(frame);
      });
    }
    return { draw, spinTo };
  }

  function luminance(hex) {
    const v = hex.replace('#', '');
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(v.substr(i, 2), 16) / 255);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function esc(t) { return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

  function reveal(container, winner, style) {
    container.innerHTML = `<div style="background:${style.winner_bg}; color:${style.winner_color}; border-radius:22px; padding:22px 34px; text-align:center; box-shadow:0 12px 40px rgba(0,0,0,.45); animation:rr-pop .5s ease-out;">
      <div style="font-size:0.9rem; letter-spacing:3px; text-transform:uppercase; opacity:.8;">${winner.position ? 'Ganador ' + winner.position : 'Ganador'}</div>
      <div style="font-size:clamp(1.8rem,5vw,3.6rem); font-weight:800; line-height:1.1; margin-top:4px; font-family:'${style.title_font}', sans-serif;">${esc(winner.name)}</div>
      ${winner.entity ? `<div style="font-size:1.1rem; margin-top:6px; opacity:.85;">${esc(winner.entity)}</div>` : ''}
    </div>`;
  }

  if (typeof window !== 'undefined') window.RouletteRender = { wheel, buildSegments, fontsUrl, applyBackground, reveal };
  if (typeof module !== 'undefined') module.exports = { buildSegments };
})();
