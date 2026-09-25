/* Dibujo y animación de la ruleta (Sprint 5) — compartido por la pantalla del proyector (/r/<token>), la vista previa de la
   configuración visual y la de comportamiento. Solo sabe DIBUJAR y ANIMAR: el ganador ya viene decidido por el servidor.

   RouletteRender.wheel(canvas, style)            -> { draw(names, angle), spinTo(names, winnerIndex, seconds) : Promise }
   RouletteRender.buildSegments(pool, winner, n)  -> { names, winnerIndex }   (un segmento POR PERSONA, hasta n; siempre incluye al ganador)
   RouletteRender.stage(host, style)              -> { idle(names), spin(pool, winner, seconds) : Promise, kind }
                                                     dibuja la ruleta CIRCULAR o la columna vertical estilo casino («jackpot») según style.wheel_style
   RouletteRender.buildReelList(pool, winner)     -> { rows, winnerRow }   (lista que recorre la columna del estilo casino)
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

  // Un segmento POR PERSONA (hasta `max`, 24 por defecto: más ya no se lee en un círculo), con el ganador en una posición al azar. Con 2 personas
  // hay 2 segmentos que se reparten el círculo; nunca se rellena con segmentos vacíos.
  function buildSegments(pool, winner, max) {
    const others = Array.from(new Set((pool || []).filter((x) => x && x !== winner)));
    for (let i = others.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [others[i], others[j]] = [others[j], others[i]]; }
    const total = Math.max(1, Math.min(max || 24, others.length + 1));
    const names = others.slice(0, total - 1);
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

  // ---- Estilo «casino» (jackpot): una columna vertical de nombres que pasa de arriba hacia abajo y frena con el ganador en la fila del centro.
  // Sirve para muchos nombres (200, 1000…) donde una ruleta circular ya no se puede leer.
  function buildReelList(pool, winner) {
    let others = Array.from(new Set((pool || []).filter((x) => x && x !== winner)));
    for (let i = others.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [others[i], others[j]] = [others[j], others[i]]; }
    others = others.slice(0, 150);                                            // el recorrido no necesita más filas: con miles de personas la página sigue liviana
    const shuffle = () => { const a = others.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
    const rows = [];
    if (!others.length) { for (let i = 0; i < 40; i++) rows.push(winner); }     // una sola persona: la columna gira igual
    else while (rows.length < 70) rows.push(...shuffle());                    // se repite mezclado hasta tener recorrido suficiente
    const tail = shuffle().slice(0, 3);
    while (tail.length < 3) tail.push(others[0] || winner);
    const winnerRow = rows.length;
    rows.push(winner, ...tail);                                              // tras el ganador quedan filas visibles debajo
    return { rows, winnerRow };
  }

  function reel(host, style) {
    const VISIBLE = 5, H = 96, HEIGHT = VISIBLE * H;
    const accent = style.pointer_color || '#FF4D6D';
    const colors = style.colors && style.colors.length ? style.colors : ['#D4AF37', '#0A0E2E'];
    const box = document.createElement('div');
    box.style.cssText = `position:relative; width:min(760px, 94vw); height:${HEIGHT}px; overflow:hidden; border-radius:26px; border:7px solid ${accent}; background:rgba(0,0,0,.38); box-shadow:inset 0 0 70px rgba(0,0,0,.65), 0 10px 40px rgba(0,0,0,.4); margin:0 auto;`;
    const strip = document.createElement('div');
    strip.style.cssText = 'position:absolute; left:0; right:0; top:0; will-change:transform;';
    const line = document.createElement('div');
    line.style.cssText = `position:absolute; left:0; right:0; top:${(HEIGHT - H) / 2}px; height:${H}px; border-top:4px solid ${accent}; border-bottom:4px solid ${accent}; background:rgba(255,255,255,.10); pointer-events:none; box-sizing:border-box;`;
    const fade = (pos) => `position:absolute; left:0; right:0; ${pos}:0; height:${H * 1.5}px; pointer-events:none; background:linear-gradient(${pos === 'top' ? 'to bottom' : 'to top'}, rgba(0,0,0,.75), rgba(0,0,0,0));`;
    const top = document.createElement('div'); top.style.cssText = fade('top');
    const bottom = document.createElement('div'); bottom.style.cssText = fade('bottom');
    box.append(strip, line, top, bottom);
    host.appendChild(box);

    const rowEl = (name, i) => {
      const d = document.createElement('div');
      const bg = colors[i % colors.length];
      d.style.cssText = `height:${H}px; box-sizing:border-box; display:flex; align-items:center; justify-content:center; padding:0 28px; font-weight:800; font-size:${H * 0.42}px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; background:${bg}; color:${luminance(bg) > 0.55 ? '#111' : '#fff'}; border-bottom:1px solid rgba(255,255,255,.18); font-family:'${style.font_family || 'Montserrat'}', sans-serif;`;
      d.textContent = name;
      return d;
    };
    let y = 0;
    const setY = (v, blur) => { y = v; strip.style.transform = `translateY(${v}px)`; strip.style.filter = blur > 0.4 ? `blur(${blur.toFixed(1)}px)` : 'none'; };
    const centerOffset = (row) => -(row * H) + (HEIGHT - H) / 2;

    function idle(names) {
      strip.innerHTML = '';
      const list = (names && names.length ? names : ['?']).slice(0, 40);
      list.forEach((n, i) => strip.appendChild(rowEl(n, i)));
      setY(centerOffset(Math.min(2, list.length - 1)), 0);
    }
    function spin(pool, winner, seconds) {
      const { rows, winnerRow } = buildReelList(pool, winner);
      strip.innerHTML = '';
      rows.forEach((n, i) => strip.appendChild(rowEl(n, i)));
      const from = centerOffset(1), to = centerOffset(winnerRow);
      const duration = Math.max(2, seconds || 6) * 1000;
      const t0 = performance.now();
      let prevY = from, prevT = t0;
      return new Promise((resolve) => {
        function frame(now) {
          const p = Math.min(1, (now - t0) / duration);
          const eased = 1 - Math.pow(1 - p, 3.4);                                  // arranca rápido y frena con suspenso al final
          const cur = from + (to - from) * eased;
          const v = Math.abs(cur - prevY) / Math.max(1, now - prevT) * 1000;        // px/s → desenfoque de movimiento mientras va rápido
          prevY = cur; prevT = now;
          setY(cur, Math.min(5, v / 900));
          if (p < 1) requestAnimationFrame(frame);
          else { setY(to, 0); strip.children[winnerRow].style.boxShadow = `inset 0 0 0 5px ${accent}`; resolve(); }
        }
        requestAnimationFrame(frame);
      });
    }
    return { idle, spin };
  }

  // Un solo punto de entrada para las tres pantallas: dibuja el tipo de ruleta elegido en el estilo.
  function stage(host, style) {
    host.innerHTML = '';
    if (style.wheel_style === 'jackpot') {
      const r = reel(host, style);
      return { kind: 'jackpot', idle: r.idle, spin: async (pool, winner, seconds) => { await r.spin(pool, winner, seconds); } };
    }
    const canvas = document.createElement('canvas');
    canvas.width = 900; canvas.height = 900; canvas.style.cssText = 'width:100%; height:auto; max-width:100%;';
    host.appendChild(canvas);
    const w = wheel(canvas, style);
    return {
      kind: 'circular',
      idle: (names) => w.draw(names && names.length ? names.slice(0, 24) : ['?', '?', '?', '?'], 0),
      spin: async (pool, winner, seconds) => { const seg = buildSegments(pool, winner, 24); w.draw(seg.names, 0); await w.spinTo(seg.names, seg.winnerIndex, seconds); },
    };
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

  if (typeof window !== 'undefined') window.RouletteRender = { wheel, buildSegments, buildReelList, stage, fontsUrl, applyBackground, reveal };
  if (typeof module !== 'undefined') module.exports = { buildSegments, buildReelList };
})();
