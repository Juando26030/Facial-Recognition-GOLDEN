/* Componente compartido «tomar o adjuntar foto» (A1, 2026-10): lo usan la página de aceptación (/aceptar) y, más adelante, el campo «Adjuntar foto» de los formularios.
   - Cámara EN VIVO (frontal) con óvalo guía e indicación corta; «Tomar foto» → vista previa → «Repetir» / «Usar esta foto».
   - Subir un archivo queda como alternativa si no hay cámara o la persona niega el permiso.
   - Revisión SIMPLE en el dispositivo (no detecta caras: eso va con B2d en el servidor): tamaño mínimo, brillo y nitidez aproximada. Si falla: «intenta de nuevo» con el motivo;
     tras 2 intentos fallidos se deja continuar (para no excluir celulares de gama baja).
   - La foto sale como JPEG (máx. 1280 px de lado mayor; evita el HEIC del iPhone). Nada se guarda en el navegador: los intentos descartados se sueltan de la memoria.
   Uso: PhotoCapture.mount(contenedor, { onChange: (blob|null) => {...}, hint: 'texto corto' })  →  { blob(), reset() } */
(function () {
  const MIN_SHORT_SIDE = 480;                // px del lado corto
  const MIN_LUMA = 55, MAX_LUMA = 215;       // brillo medio (0-255)
  const MIN_SHARPNESS = 40;                  // varianza del laplaciano sobre una copia de 240 px (aproximado: calibrable)
  const MAX_SIDE = 1280;
  const ALLOW_AFTER_FAILS = 2;
  const PRIVACY_NOTE = 'Solo guardamos la foto final que decidas enviar. No grabamos video ni almacenamos tus intentos.';   // texto literal de la auditora

  function el(tag, attrs, text) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => { if (k === 'style') e.style.cssText = v; else e.setAttribute(k, v); });
    if (text) e.textContent = text;
    return e;
  }

  function toCanvas(source, w, h) {
    const scale = Math.min(1, MAX_SIDE / Math.max(w, h));
    const c = document.createElement('canvas');
    c.width = Math.round(w * scale); c.height = Math.round(h * scale);
    c.getContext('2d').drawImage(source, 0, 0, c.width, c.height);
    return { canvas: c, w, h };
  }

  // Revisión simple: devuelve '' si está bien o el motivo en palabras sencillas.
  function check(canvas, origW, origH) {
    if (Math.min(origW, origH) < MIN_SHORT_SIDE) return 'La foto es muy pequeña. Acércate un poco o usa otra foto.';
    const s = Math.min(1, 240 / Math.max(canvas.width, canvas.height));
    const w = Math.max(1, Math.round(canvas.width * s)), h = Math.max(1, Math.round(canvas.height * s));
    const small = document.createElement('canvas'); small.width = w; small.height = h;
    const ctx = small.getContext('2d'); ctx.drawImage(canvas, 0, 0, w, h);
    const d = ctx.getImageData(0, 0, w, h).data;
    const g = new Float32Array(w * h); let sum = 0;
    for (let i = 0; i < w * h; i++) { const y = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2]; g[i] = y; sum += y; }
    const mean = sum / (w * h);
    if (mean < MIN_LUMA) return 'La foto está muy oscura. Busca más luz, de frente.';
    if (mean > MAX_LUMA) return 'La foto tiene demasiada luz. Evita la luz directa detrás o sobre la cara.';
    let n = 0, m = 0, m2 = 0;
    for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
      const i = y * w + x, lap = g[i - 1] + g[i + 1] + g[i - w] + g[i + w] - 4 * g[i];
      n++; const delta = lap - m; m += delta / n; m2 += delta * (lap - m);
    }
    if (n && m2 / n < MIN_SHARPNESS) return 'La foto se ve borrosa. Quédate quieto y vuelve a tomarla.';
    return '';
  }

  function mount(host, opts) {
    opts = opts || {};
    let stream = null, current = null, fails = 0;
    host.replaceChildren();
    const hint = el('p', { class: 'pc-hint' }, opts.hint || 'Con buena luz, sin gafas oscuras ni gorra, mirando de frente.');
    const stage = el('div', { class: 'pc-stage', style: 'position:relative; width:100%; max-width:420px; aspect-ratio:3/4; margin:8px auto; border-radius:14px; overflow:hidden; background:#000; display:none;' });
    const video = el('video', { autoplay: '', playsinline: '', muted: '', style: 'width:100%; height:100%; object-fit:cover; transform:scaleX(-1);' });
    const oval = el('div', { 'aria-hidden': 'true', style: 'position:absolute; left:50%; top:46%; width:62%; height:70%; transform:translate(-50%,-50%); border:3px dashed rgba(255,255,255,.9); border-radius:50%; box-shadow:0 0 0 999px rgba(0,0,0,.35); pointer-events:none;' });
    const preview = el('img', { alt: 'Vista previa de tu foto', style: 'display:none; width:100%; max-width:420px; margin:8px auto; border-radius:14px;' });
    stage.append(video, oval);
    const note = el('p', { class: 'pc-note', style: 'font-size:.78rem; opacity:.8; margin:4px 0 8px;' }, 'ⓘ ' + PRIVACY_NOTE);
    const msg = el('p', { class: 'pc-msg', role: 'status', 'aria-live': 'polite', style: 'min-height:1.2em; color:#c0392b; font-size:.9rem;' });
    const row = el('div', { class: 'pc-row', style: 'display:flex; gap:8px; flex-wrap:wrap; justify-content:center;' });
    const bOpen = el('button', { type: 'button', class: 'secondary pc-open' }, 'Abrir la cámara');
    const bShot = el('button', { type: 'button', class: 'primary pc-shot', style: 'display:none;' }, 'Tomar foto');
    const bRetry = el('button', { type: 'button', class: 'secondary pc-retry', style: 'display:none;' }, 'Repetir');
    const bUse = el('button', { type: 'button', class: 'primary pc-use', style: 'display:none;' }, 'Usar esta foto');
    const fileLabel = el('label', { class: 'pc-file', style: 'display:block; margin-top:10px; font-size:.9rem;' }, 'O sube una foto desde tu dispositivo: ');
    const file = el('input', { type: 'file', accept: 'image/*' });
    fileLabel.appendChild(file);
    row.append(bOpen, bShot, bRetry, bUse);
    host.append(hint, stage, preview, note, msg, row, fileLabel);
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) bOpen.style.display = 'none';

    const show = (b, on) => { b.style.display = on ? '' : 'none'; };
    const stop = () => { if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; } video.srcObject = null; stage.style.display = 'none'; };
    const drop = () => { if (preview.src) URL.revokeObjectURL(preview.src); preview.removeAttribute('src'); preview.style.display = 'none'; current = null; };
    const chosen = (blob) => { if (opts.onChange) opts.onChange(blob); };

    async function evaluate(canvas, w, h) {
      const problem = check(canvas, w, h);
      const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.9));
      drop(); current = blob;
      preview.src = URL.createObjectURL(blob); preview.style.display = 'block';
      show(bShot, false); show(bRetry, true); show(bOpen, false);
      if (problem) {
        fails++;
        msg.textContent = problem + (fails >= ALLOW_AFTER_FAILS ? ' Si no logras una mejor, puedes usar esta.' : ' Intenta de nuevo.');
        show(bUse, fails >= ALLOW_AFTER_FAILS);
      } else { msg.textContent = ''; show(bUse, true); }
      chosen(null);
    }

    bOpen.addEventListener('click', async () => {
      msg.textContent = ''; drop(); chosen(null);
      try { stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 1280 } }, audio: false }); }
      catch (e) { msg.textContent = 'No se pudo abrir la cámara (o no diste el permiso). Puedes subir una foto desde tu dispositivo.'; show(bOpen, false); return; }
      video.srcObject = stream; stage.style.display = 'block';
      show(bOpen, false); show(bShot, true); show(bRetry, false); show(bUse, false);
    });
    bShot.addEventListener('click', async () => {
      if (!video.videoWidth) return;
      const { canvas, w, h } = toCanvas(video, video.videoWidth, video.videoHeight);
      stop();
      await evaluate(canvas, w, h);
    });
    bRetry.addEventListener('click', () => { drop(); chosen(null); msg.textContent = ''; show(bRetry, false); show(bUse, false); if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) bOpen.click(); });
    bUse.addEventListener('click', () => { if (!current) return; show(bUse, false); show(bRetry, true); msg.style.color = '#1e7a3a'; msg.textContent = 'Foto lista.'; chosen(current); setTimeout(() => { msg.style.color = '#c0392b'; }, 0); });
    file.addEventListener('change', async () => {
      const f = file.files && file.files[0]; file.value = '';
      if (!f) return;
      stop();
      const url = URL.createObjectURL(f);
      const img = new Image();
      img.onload = async () => { const { canvas, w, h } = toCanvas(img, img.naturalWidth, img.naturalHeight); URL.revokeObjectURL(url); await evaluate(canvas, w, h); };
      img.onerror = () => { URL.revokeObjectURL(url); msg.textContent = 'No pudimos leer esa imagen. Prueba con otra o usa la cámara.'; };
      img.src = url;
    });
    return { blob: () => current, reset: () => { stop(); drop(); fails = 0; msg.textContent = ''; show(bOpen, !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)); show(bShot, false); show(bRetry, false); show(bUse, false); chosen(null); } };
  }

  window.PhotoCapture = { mount, check, PRIVACY_NOTE };
})();
