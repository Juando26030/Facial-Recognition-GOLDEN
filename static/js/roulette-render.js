/* Dibujo y animación de la ruleta (Sprint 5) — compartido por la pantalla del proyector (/r/<token>), la vista previa de la
   configuración visual y la de comportamiento. Solo sabe DIBUJAR y ANIMAR: el ganador ya viene decidido por el servidor.

   RouletteRender.wheel(canvas, style)            -> { draw(names, angle), spinTo(names, winnerIndex, seconds) : Promise }
   RouletteRender.buildSegments(pool, winner, n)  -> { names, winnerIndex }   (un segmento POR PERSONA, hasta n; siempre incluye al ganador)
   RouletteRender.stage(host, style, opts?)       -> { idle(names), spin(pool, winner, seconds, ctl?) : Promise, kind }
                                                     dibuja la ruleta CIRCULAR o la columna vertical estilo casino («jackpot») según style.wheel_style.
                                                     ctl = { stop: Promise } (Fase 10, C): GIRO LIBRE — gira sin parar hasta que `ctl.stop` se cumple (un clic en «Detener») y entonces frena sobre el
                                                     ganador; sin `ctl` dura `seconds`. Sin clic en 2 minutos se detiene sola (MAX_FREE_MS).
   RouletteRender.topImages(host, style, assetUrl) -> dibuja los logos/banners de arriba (style.top_images)
   RouletteRender.fieldRows(winner)               -> [{label, value, entity}] lo que se muestra bajo el nombre (winner.fields; sin él, la entidad de siempre)
   RouletteRender.buildReelList(pool, winner)     -> { rows, winnerRow }   (lista que recorre la columna del estilo casino)
   RouletteRender.applyBackground(el, style, assetUrl)
   RouletteRender.reveal(container, winner, style)  -> pinta la tarjeta del ganador                                          */
(function () {
  const TAU = Math.PI * 2;
  const MAX_FREE_MS = 120000;          // giro libre: si nadie hace clic en «Detener», se frena sola a los 2 minutos

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

  // Marca Golden usada por el dibujo (la configuración visual manda en colores de segmentos, textos y fondo; esto es solo el «marco»).
  const BRAND = { gold1: '#B8862B', gold2: '#E8C25A', goldMid: '#D4A63F', navy: '#1E2A6E', navyDeep: '#141C4D', ivory: '#FFF6D8', legacyPointer: '#FF4D6D' };
  const reduceMotion = () => !!(typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function wheel(canvas, style, opts) {
    const ctx = canvas.getContext('2d');
    const colors = style.colors && style.colors.length ? style.colors : ['#D4AF37', '#0A0E2E'];
    const family = `'${style.font_family || 'Montserrat'}', sans-serif`;
    // El rosa por defecto de versiones anteriores no es de la marca: si nadie lo cambió, el puntero va dorado con joya azul noche.
    const custom = style.pointer_color && style.pointer_color.toUpperCase() !== BRAND.legacyPointer;
    const jewel = custom ? style.pointer_color : BRAND.navy;
    let current = 0, lastNames = ['?'], lastHl = null, spinning = false;
    let logo = null;
    if (opts && opts.logoUrl) { logo = new Image(); logo.onload = () => draw(lastNames, current, lastHl); logo.src = opts.logoUrl; }
    if (typeof document !== 'undefined' && document.fonts && document.fonts.load) {      // que el primer dibujo no salga con la letra de reemplazo
      document.fonts.load(`700 24px ${family}`).then(() => draw(lastNames, current, lastHl)).catch(() => {});
    }

    function goldGrad(x0, y0, x1, y1) {
      const g = ctx.createLinearGradient(x0, y0, x1, y1);
      g.addColorStop(0, BRAND.gold2); g.addColorStop(0.5, BRAND.goldMid); g.addColorStop(1, BRAND.gold1);
      return g;
    }

    // Nombre radial, SIEMPRE legible: en la mitad izquierda de la rueda se gira media vuelta para que nunca quede de cabeza.
    function drawLabel(name, mid, R1, hubR, color, step) {
      const left = Math.cos(mid) < 0;
      ctx.save();
      ctx.rotate(mid);
      if (left) ctx.rotate(Math.PI);
      ctx.textBaseline = 'middle';
      ctx.textAlign = left ? 'left' : 'right';
      const x = left ? -(R1 - 40) : (R1 - 40);
      const maxW = R1 - 40 - hubR - 26;
      let size = Math.max(24, Math.min(64, step * R1 * 0.40));
      ctx.font = `700 ${size}px ${family}`;
      let label = name;
      while (ctx.measureText(label).width > maxW && size > 26) { size -= 2; ctx.font = `700 ${size}px ${family}`; }
      while (ctx.measureText(label).width > maxW && label.length > 2) label = label.slice(0, -2).trimEnd() + '…';
      ctx.fillStyle = color;
      ctx.fillText(label, x, 0);
      ctx.restore();
    }

    function drawPointer(cx, tilt) {
      const px = cx, py = 34;
      ctx.save();
      ctx.translate(px, py); ctx.rotate(tilt); ctx.translate(-px, -py);
      ctx.shadowColor = 'rgba(0,0,0,.55)'; ctx.shadowBlur = 18; ctx.shadowOffsetY = 6;
      ctx.beginPath();                                                   // gota: cabeza redonda y punta hacia la rueda
      ctx.moveTo(px, 132);
      ctx.bezierCurveTo(px - 14, 104, px - 44, 86, px - 44, 56);
      ctx.arc(px, 56, 44, Math.PI, 0);
      ctx.bezierCurveTo(px + 44, 86, px + 14, 104, px, 132);
      ctx.closePath();
      ctx.fillStyle = goldGrad(px - 44, 10, px + 44, 130); ctx.fill();
      ctx.shadowColor = 'transparent';
      ctx.lineWidth = 5; ctx.strokeStyle = BRAND.navyDeep; ctx.stroke();
      ctx.beginPath(); ctx.arc(px, 56, 17, 0, TAU);
      ctx.fillStyle = jewel; ctx.fill(); ctx.lineWidth = 4; ctx.strokeStyle = BRAND.ivory; ctx.stroke();
      ctx.restore();
    }

    function drawHub(cx, cy, hubR) {
      ctx.save();
      ctx.shadowColor = 'rgba(0,0,0,.5)'; ctx.shadowBlur = 24;
      ctx.beginPath(); ctx.arc(cx, cy, hubR + 12, 0, TAU); ctx.fillStyle = goldGrad(cx - hubR, cy - hubR, cx + hubR, cy + hubR); ctx.fill();
      ctx.restore();
      const g = ctx.createRadialGradient(cx - 18, cy - 18, 8, cx, cy, hubR);
      g.addColorStop(0, BRAND.navy); g.addColorStop(1, BRAND.navyDeep);
      ctx.beginPath(); ctx.arc(cx, cy, hubR, 0, TAU); ctx.fillStyle = g; ctx.fill();
      ctx.lineWidth = 3; ctx.strokeStyle = BRAND.gold2; ctx.stroke();
      if (logo && logo.complete && logo.naturalWidth) {                   // logo del evento, contenido en un disco claro
        const d = hubR * 1.55;
        ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, hubR - 8, 0, TAU); ctx.fillStyle = BRAND.ivory; ctx.fill(); ctx.clip();
        const k = Math.min(d / logo.naturalWidth, d / logo.naturalHeight);
        ctx.drawImage(logo, cx - logo.naturalWidth * k / 2, cy - logo.naturalHeight * k / 2, logo.naturalWidth * k, logo.naturalHeight * k);
        ctx.restore();
      } else {                                                            // marca: destello dorado de cuatro puntas
        const R = hubR * 0.62, r = R * 0.28;
        ctx.beginPath();
        for (let i = 0; i < 8; i++) { const rad = i % 2 ? r : R, a = -Math.PI / 2 + i * Math.PI / 4; ctx.lineTo(cx + Math.cos(a) * rad, cy + Math.sin(a) * rad); }
        ctx.closePath(); ctx.fillStyle = goldGrad(cx - R, cy - R, cx + R, cy + R); ctx.fill();
      }
    }

    function draw(names, angle, highlight) {
      current = angle; lastNames = names; lastHl = highlight == null ? null : highlight;
      const w = canvas.width, h = canvas.height, cx = w / 2, cy = h / 2;
      const R0 = Math.min(w, h) / 2 - 22, R1 = R0 - 48, hubR = Math.round(R1 * 0.17);     // R0 borde exterior, R1 borde de los segmentos
      ctx.clearRect(0, 0, w, h);

      // aro dorado con foquitos
      ctx.beginPath(); ctx.arc(cx, cy, R0, 0, TAU); ctx.fillStyle = goldGrad(cx - R0, cy - R0, cx + R0, cy + R0); ctx.fill();
      ctx.beginPath(); ctx.arc(cx, cy, R0 - 3, 0, TAU); ctx.lineWidth = 3; ctx.strokeStyle = BRAND.navyDeep; ctx.stroke();
      ctx.beginPath(); ctx.arc(cx, cy, R1 + 3, 0, TAU); ctx.fillStyle = BRAND.navyDeep; ctx.fill();
      const bulbs = 28, bulbR = R1 + (R0 - R1) / 2 + 1, phase = spinning ? Math.floor(angle * 5) : 0;
      for (let i = 0; i < bulbs; i++) {
        const a = -Math.PI / 2 + (i / bulbs) * TAU, bx = cx + Math.cos(a) * bulbR, by = cy + Math.sin(a) * bulbR;
        const lit = !spinning || ((i + phase) % 2 === 0);
        ctx.beginPath(); ctx.arc(bx, by, 8, 0, TAU);
        ctx.fillStyle = lit ? BRAND.ivory : BRAND.gold1; ctx.fill();
        if (lit) { ctx.beginPath(); ctx.arc(bx, by, 13, 0, TAU); ctx.fillStyle = 'rgba(255,246,216,.28)'; ctx.fill(); }
      }

      // segmentos
      const n = names.length, step = TAU / n;
      ctx.save();
      ctx.beginPath(); ctx.arc(cx, cy, R1, 0, TAU); ctx.clip();
      for (let i = 0; i < n; i++) {
        const a0 = angle - Math.PI / 2 + i * step, a1 = a0 + step;     // el segmento 0 empieza arriba y `angle` rota toda la rueda
        let color = colors[i % colors.length];
        if (n % colors.length === 1 && i === n - 1) color = colors[(i + 1) % colors.length];   // que el último no choque con el primero
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, R1 + 2, a0, a1); ctx.closePath();
        ctx.fillStyle = color; ctx.fill();
      }
      const shade = ctx.createRadialGradient(cx, cy, hubR, cx, cy, R1);     // profundidad: más oscuro hacia el borde, sin cambiar los colores elegidos
      shade.addColorStop(0, 'rgba(255,255,255,.10)'); shade.addColorStop(0.55, 'rgba(0,0,0,0)'); shade.addColorStop(1, 'rgba(0,0,0,.24)');
      ctx.fillStyle = shade; ctx.fillRect(0, 0, w, h);
      ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(232,194,90,.7)';
      for (let i = 0; i < n; i++) { const a = angle - Math.PI / 2 + i * step; ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * hubR, cy + Math.sin(a) * hubR); ctx.lineTo(cx + Math.cos(a) * R1, cy + Math.sin(a) * R1); ctx.stroke(); }
      if (lastHl !== null) {                                                  // al terminar: el ganador resalta y el resto se apaga
        for (let i = 0; i < n; i++) {
          if (i === lastHl) continue;
          const a0 = angle - Math.PI / 2 + i * step;
          ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, R1 + 2, a0, a0 + step); ctx.closePath();
          ctx.fillStyle = 'rgba(10,14,46,.55)'; ctx.fill();
        }
      }
      ctx.translate(cx, cy);
      for (let i = 0; i < n; i++) {
        const mid = angle - Math.PI / 2 + (i + 0.5) * step;
        let color = colors[i % colors.length];
        if (n % colors.length === 1 && i === n - 1) color = colors[(i + 1) % colors.length];
        drawLabel(names[i], mid, R1, hubR, luminance(color) > 0.5 ? '#111111' : '#FFFFFF', step);
      }
      ctx.restore();
      if (lastHl !== null) {                                                  // contorno dorado del segmento ganador
        const a0 = angle - Math.PI / 2 + lastHl * step;
        ctx.save(); ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, R1 - 3, a0, a0 + step); ctx.closePath();
        ctx.lineWidth = 7; ctx.lineJoin = 'round'; ctx.strokeStyle = BRAND.gold2; ctx.stroke(); ctx.restore();
      }

      drawHub(cx, cy, hubR);
      let tilt = 0;
      if (spinning) { const f = (((-angle / step) % 1) + 1) % 1; tilt = -0.34 * Math.max(0, 1 - f / 0.22); }   // la clavija empuja la punta al pasar cada segmento
      drawPointer(cx, tilt);
    }

    // Curva de giro: arranca con aceleración corta y frena largo (como una rueda con rozamiento). Se integra una velocidad y se normaliza.
    function curve() {
      const N = 240, ramp = 0.06, cum = [0];
      for (let i = 1; i <= N; i++) { const p = i / N; cum.push(cum[i - 1] + Math.min(1, p / ramp) * Math.pow(1 - p, 2.6)); }
      return (p) => { const x = p * N, i = Math.min(N - 1, Math.floor(x)); return (cum[i] + (cum[i + 1] - cum[i]) * (x - i)) / cum[N]; };
    }

    // Gira varias vueltas y frena con el segmento `winnerIndex` bajo el puntero (arriba).
    function spinTo(names, winnerIndex, seconds) {
      const n = names.length, step = TAU / n;
      const target = -(winnerIndex + 0.5) * step + (Math.random() - 0.5) * step * 0.6;   // centro del segmento ± un poco
      const start = ((current % TAU) + TAU) % TAU;
      const calm = reduceMotion();                                                 // sin animación larga si la persona lo pidió
      const end = target + TAU * (calm ? 1 : 5 + Math.floor(Math.random() * 3));
      const duration = calm ? 900 : Math.max(2, seconds || 6) * 1000;
      const ease = calm ? (p) => 1 - Math.pow(1 - p, 3) : curve();
      const t0 = performance.now();
      spinning = !calm;
      return new Promise((resolve) => {
        function frame(now) {
          const p = Math.min(1, (now - t0) / duration);
          draw(names, start + (end - start) * ease(p));
          if (p < 1) requestAnimationFrame(frame);
          else { spinning = false; draw(names, end, winnerIndex); resolve(); }
        }
        requestAnimationFrame(frame);
      });
    }
    // Giro LIBRE (Fase 10, C): gira a velocidad constante hasta que `stop` se cumple; entonces frena con el segmento `winnerIndex` bajo el puntero. La duración del frenado se ajusta a la distancia para que
    // la velocidad no pegue un salto al hacer clic (velocidad inicial del frenado cúbico = 3 · distancia / duración).
    function spinFree(names, winnerIndex, stop) {
      const n = names.length, step = TAU / n, calm = reduceMotion();
      const cruise = calm ? 3 : 7;                                                  // rad/s (~1,1 vueltas por segundo)
      let angle = current, v = 0, last = performance.now(), stopped = false;
      const t0 = last;
      Promise.resolve(stop).then(() => { stopped = true; }, () => { stopped = true; });
      spinning = !calm;
      return new Promise((resolve) => {
        function cruiseFrame(now) {
          if (stopped || now - t0 > MAX_FREE_MS) { brake(); return; }
          const dt = Math.min(0.05, (now - last) / 1000); last = now;
          v = Math.min(cruise, v + cruise * dt / 0.8);                              // arranque suave (0,8 s)
          angle += v * dt; draw(names, angle);
          requestAnimationFrame(cruiseFrame);
        }
        function brake() {
          const target = -(winnerIndex + 0.5) * step + (Math.random() - 0.5) * step * 0.6;
          const want = Math.max(v, cruise * 0.5) * 3.5 / 3;                         // distancia aproximada para ~3,5 s de frenado
          const end = target + TAU * Math.ceil((angle + want - target) / TAU);
          const dist = end - angle, duration = Math.max(1200, Math.min(7000, 3 * dist / Math.max(v, cruise * 0.5) * 1000));
          const from = angle, t1 = performance.now();
          (function frame(now) {
            const p = Math.min(1, (now - t1) / duration);
            draw(names, from + dist * (1 - Math.pow(1 - p, 3)));
            if (p < 1) requestAnimationFrame(frame);
            else { spinning = false; draw(names, end, winnerIndex); resolve(); }
          })(t1);
        }
        requestAnimationFrame(cruiseFrame);
      });
    }
    return { draw, spinTo, spinFree };
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
    const big = typeof document !== 'undefined' && document.body.classList.contains('rr-display');     // en el proyector las filas son más altas
    const VISIBLE = 5, H = big ? Math.max(72, Math.min(132, Math.round(window.innerHeight * 0.115))) : 96, HEIGHT = VISIBLE * H;
    const accent = style.pointer_color && style.pointer_color.toUpperCase() !== BRAND.legacyPointer ? style.pointer_color : BRAND.gold2;
    const colors = style.colors && style.colors.length ? style.colors : ['#D4AF37', '#0A0E2E'];
    const family = `'${style.font_family || 'Montserrat'}', sans-serif`;
    const mk = (cls) => { const d = document.createElement('div'); d.className = cls; return d; };
    const box = mk('rr-reel'); box.style.height = `${HEIGHT}px`;
    const strip = mk('rr-reel__strip');
    const line = mk('rr-reel__line'); line.style.top = `${(HEIGHT - H) / 2}px`; line.style.height = `${H}px`; line.style.borderColor = accent;
    const top = mk('rr-reel__fade rr-reel__fade--top'), bottom = mk('rr-reel__fade rr-reel__fade--bottom');
    top.style.height = bottom.style.height = `${H * 1.5}px`;
    const arrowL = mk('rr-reel__arrow rr-reel__arrow--left'), arrowR = mk('rr-reel__arrow rr-reel__arrow--right');
    arrowL.style.top = arrowR.style.top = `${HEIGHT / 2}px`; arrowL.style.borderLeftColor = arrowR.style.borderRightColor = accent;
    box.append(strip, line, top, bottom, arrowL, arrowR);
    host.appendChild(box);

    const rowEl = (name, i) => {
      const d = mk('rr-reel__row');
      const bg = colors[i % colors.length];
      d.style.cssText = `height:${H}px; font-size:${H * 0.42}px; background:${bg}; color:${luminance(bg) > 0.5 ? '#111111' : '#FFFFFF'}; font-family:${family};`;
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
      const calm = reduceMotion();
      const from = calm ? centerOffset(Math.max(0, winnerRow - 2)) : centerOffset(1), to = centerOffset(winnerRow);
      const duration = calm ? 700 : Math.max(2, seconds || 6) * 1000;
      const t0 = performance.now();
      let prevY = from, prevT = t0;
      return new Promise((resolve) => {
        function frame(now) {
          const p = Math.min(1, (now - t0) / duration);
          const eased = 1 - Math.pow(1 - p, 3.4);                                  // arranca rápido y frena con suspenso al final
          const cur = from + (to - from) * eased;
          const v = Math.abs(cur - prevY) / Math.max(1, now - prevT) * 1000;        // px/s → desenfoque de movimiento mientras va rápido
          prevY = cur; prevT = now;
          setY(cur, calm ? 0 : Math.min(5, v / 900));
          if (p < 1) requestAnimationFrame(frame);
          else { setY(to, 0); strip.children[winnerRow].classList.add('rr-reel__row--win'); strip.children[winnerRow].style.boxShadow = `inset 0 0 0 6px ${accent}`; resolve(); }
        }
        requestAnimationFrame(frame);
      });
    }
    // Giro LIBRE (Fase 10, C): la columna corre en bucle (3 copias de una vuelta de filas, de largo múltiplo del número de colores para que no se note el salto) hasta que `stop` se cumple;
    // entonces el ganador se coloca unas filas más adelante y la columna frena sobre él con la velocidad con que venía.
    function spinFree(pool, winner, stop) {
      let others = Array.from(new Set((pool || []).filter((x) => x && x !== winner)));
      for (let i = others.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [others[i], others[j]] = [others[j], others[i]]; }
      others = others.slice(0, 150);
      if (!others.length) others = [winner];
      const L = colors.length * Math.ceil(36 / colors.length);
      const loop = []; while (loop.length < L) loop.push(...others);
      loop.length = L;
      const rows = [].concat(loop, loop, loop);
      strip.innerHTML = '';
      rows.forEach((n, i) => strip.appendChild(rowEl(n, i)));
      const calm = reduceMotion();
      const speed = H * (calm ? 3 : 9);                                            // px/s
      const base = centerOffset(1), loopPx = L * H;
      let pos = 0, last = performance.now(), v = 0, stopped = false;
      const t0 = last;
      Promise.resolve(stop).then(() => { stopped = true; }, () => { stopped = true; });
      return new Promise((resolve) => {
        function cruiseFrame(now) {
          if (stopped || now - t0 > MAX_FREE_MS) { brake(); return; }
          const dt = Math.min(0.05, (now - last) / 1000); last = now;
          v = Math.min(speed, v + speed * dt / 0.6);
          pos = (pos + v * dt) % loopPx;
          setY(base - pos, calm ? 0 : Math.min(5, v / 900));
          requestAnimationFrame(cruiseFrame);
        }
        function brake() {
          const vv = Math.max(v, speed * 0.5);
          const curRow = pos / H + 1;                                              // fila (con decimales) que está en el centro ahora
          const winnerRow = Math.round(curRow + vv * 4 / 3.4 / H);                 // ~4 s de frenado a la velocidad que traía
          strip.replaceChild(rowEl(winner, winnerRow), strip.children[winnerRow]);
          const from = base - pos, to = centerOffset(winnerRow), dist = from - to;
          const duration = Math.max(1200, Math.min(7000, 3.4 * dist / vv * 1000));
          const t1 = performance.now();
          let prevY = from, prevT = t1;
          (function frame(now) {
            const p = Math.min(1, (now - t1) / duration);
            const cur = from + (to - from) * (1 - Math.pow(1 - p, 3.4));
            const sp = Math.abs(cur - prevY) / Math.max(1, now - prevT) * 1000;
            prevY = cur; prevT = now;
            setY(cur, calm ? 0 : Math.min(5, sp / 900));
            if (p < 1) requestAnimationFrame(frame);
            else { setY(to, 0); strip.children[winnerRow].classList.add('rr-reel__row--win'); strip.children[winnerRow].style.boxShadow = `inset 0 0 0 6px ${accent}`; resolve(); }
          })(t1);
        }
        requestAnimationFrame(cruiseFrame);
      });
    }
    return { idle, spin, spinFree };
  }

  // Un solo punto de entrada para las tres pantallas: dibuja el tipo de ruleta elegido en el estilo.
  // opts.logoUrl (opcional): imagen para el centro de la rueda circular.
  function stage(host, style, opts) {
    host.innerHTML = '';
    if (style.wheel_style === 'jackpot') {
      const r = reel(host, style);
      return { kind: 'jackpot', idle: r.idle, spin: async (pool, winner, seconds, ctl) => { if (ctl && ctl.stop) await r.spinFree(pool, winner, ctl.stop); else await r.spin(pool, winner, seconds); } };
    }
    const canvas = document.createElement('canvas');
    canvas.width = 1200; canvas.height = 1200; canvas.className = 'rr-canvas';
    canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', 'Ruleta del sorteo');
    host.appendChild(canvas);
    const w = wheel(canvas, style, opts);
    return {
      kind: 'circular',
      idle: (names) => w.draw(names && names.length ? names.slice(0, 24) : ['?', '?', '?', '?'], 0),
      spin: async (pool, winner, seconds, ctl) => {
        const seg = buildSegments(pool, winner, 24); w.draw(seg.names, 0);
        if (ctl && ctl.stop) await w.spinFree(seg.names, seg.winnerIndex, ctl.stop); else await w.spinTo(seg.names, seg.winnerIndex, seconds);
      },
    };
  }

  function luminance(hex) {
    const v = hex.replace('#', '');
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(v.substr(i, 2), 16) / 255);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

  // Confeti sobrio: pocas piezas pequeñas en los colores del evento; cae una vez y se retira. Sin movimiento si la persona lo pidió.
  function confetti(container, style) {
    if (reduceMotion() || typeof document === 'undefined') return;
    const hostEl = container.closest ? container.closest('.gw-ruleta-preview') : null;
    const layer = document.createElement('div');
    layer.className = 'rr-confetti' + (hostEl ? ' rr-confetti--local' : '');
    layer.setAttribute('aria-hidden', 'true');
    if (hostEl) hostEl.classList.add('rr-confetti-host');
    const palette = [style.winner_bg, BRAND.gold2, BRAND.ivory].concat(style.colors || []).filter(Boolean);
    for (let i = 0; i < 34; i++) {
      const p = document.createElement('i');
      p.style.cssText = `left:${(Math.random() * 100).toFixed(1)}%; background:${palette[i % palette.length]}; width:${6 + Math.floor(Math.random() * 6)}px; height:${10 + Math.floor(Math.random() * 8)}px;` +
        `--rr-dx:${Math.round(Math.random() * 160 - 80)}px; --rr-rot:${Math.round(Math.random() * 720 - 360)}deg; animation-duration:${(2.6 + Math.random() * 1.8).toFixed(2)}s; animation-delay:${(Math.random() * 0.7).toFixed(2)}s;`;
      layer.appendChild(p);
    }
    (hostEl || document.body).appendChild(layer);
    setTimeout(() => layer.remove(), 6000);
  }

  // Lo que va bajo el nombre del ganador: con `winner.fields` (Fase 10, C) lo que el coordinador eligió; sin él (sorteos viejos), la entidad de siempre.
  function fieldRows(winner) {
    if (Array.isArray(winner.fields)) return winner.fields.filter((f) => f && f.value).map((f) => ({ label: f.label || '', value: f.value, entity: !!f.entity }));
    return winner.entity ? [{ label: '', value: winner.entity, entity: true }] : [];
  }

  function reveal(container, winner, style) {
    const rows = fieldRows(winner).map((f) => `<div class="rr-winner__entity">${f.entity || !f.label ? '' : `<span class="rr-winner__fieldlabel">${esc(f.label)}</span> `}${esc(f.value)}</div>`).join('');
    container.innerHTML = `<div class="rr-winner" style="--rr-win-bg:${esc(style.winner_bg)}; --rr-win-fg:${esc(style.winner_color)};">
      <svg class="rr-winner__star" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1l2.6 7.4L22 11l-7.4 2.6L12 21l-2.6-7.4L2 11l7.4-2.6z"/></svg>
      <div class="rr-winner__eyebrow">${winner.position ? 'Ganador ' + esc(winner.position) : 'Ganador'}</div>
      <div class="rr-winner__name" style="font-family:'${esc(style.title_font)}', sans-serif;">${esc(winner.name)}</div>
      ${rows}
    </div>`;
    confetti(container, style);
  }

  // Logos/banners de arriba de la pantalla (hasta 4). `host` se vacía y se oculta si no hay ninguno.
  function topImages(host, style, assetUrl) {
    host.innerHTML = '';
    const list = Array.isArray(style.top_images) ? style.top_images.filter(Boolean) : [];
    host.hidden = !list.length;
    host.classList.toggle('rr-top--single', list.length === 1);
    list.forEach((p) => { const img = document.createElement('img'); img.src = assetUrl(p); img.alt = ''; host.appendChild(img); });
  }

  if (typeof window !== 'undefined') window.RouletteRender = { wheel, buildSegments, buildReelList, stage, applyBackground, reveal, topImages, fieldRows };
  if (typeof module !== 'undefined') module.exports = { buildSegments, buildReelList, fieldRows };
})();
