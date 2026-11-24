/* Cédula por FOTO con guía (24-nov-2026, pedido de Juan David): la cámara muestra el MISMO recuadro guía de siempre, pero ya no intenta leer cuadro a cuadro.
   El operador encuadra y pulsa «Tomar foto»: se toma UNA foto en la mayor resolución posible y esa foto se decodifica con los mismos lectores de static/js/cedula-readers.js.
     - Foto: ImageCapture.takePhoto() a la resolución máxima del sensor (Chrome/Edge en Android y en computador); si el navegador no lo ofrece (iOS Safari, Firefox) o falla,
       el cuadro actual del video a resolución completa (el video se pide a 4K / 1440p / lo que dé la cámara).
     - Cédula vieja (PDF417): primero el recorte del recuadro guía, luego la foto completa. El lector ya prueba en cada una contraste, binarizado, desenfoque inverso,
       enderezado, giros de ±4–16°, 180° y varias escalas (CedulaScanner.scanImage, plan «deep»).
     - Cédula nueva (3 líneas): recorte ajustado al recuadro, recorte holgado y por último la foto completa (busca las 3 líneas en cualquier parte y orientación). Cada recorte se lee
       con 3 tamaños de letra y, si no aparece la estructura, al revés (180°). La cédula SIEMPRE sale validada por los dígitos de control (el general cubre la cédula); los nombres
       (que no tienen control) se aceptan solo si DOS lecturas coinciden o una tiene confianza alta; si no, se entrega la cédula sin nombres.
     - Respaldo en el servidor (solo cédula nueva, con red y evento): si el navegador no logra leerla, la foto (reducida) va a POST /api/events/<id>/cedula-mrz-scan, que la lee con
       Tesseract y responde solo si los dígitos de control cuadran. Ni el navegador ni el servidor guardan la foto ni la escriben en registros: se descarta en memoria.
   El QR NO pasa por aquí (sigue en vivo en qr.js). Uso (desde qr.js):
     const h = CedulaFoto.attach({ kind: 'old'|'new', video, overlay, button, readers, eventId, onStatus(msg, tipo), onResult(datos) });   …   h.stop();
   datos = { cedula, nombre1, nombre2, apellido1, apellido2, nacimiento, … } (el mismo formato de los lectores). Las funciones puras se exportan para tests/js/cedula_foto_check.js. */
(function () {
  'use strict';
  const GUIDE = { old: { ar: 4.8, fill: 0.92 }, new: { ar: 4.6, fill: 0.94 } };          // las mismas proporciones del recuadro de los lectores en vivo
  const MSG = {
    aimOld: 'Encaje el código de barras del reverso dentro del recuadro y pulse «Tomar foto».',
    aimNew: 'Encaje las 3 líneas de letras y números del reverso dentro del recuadro y pulse «Tomar foto».',
    loading: 'Cargando el lector…',
    processing: 'Procesando la foto…',
    server: 'Procesando la foto… (revisión en el servidor)',
    fail: 'No se pudo leer la cédula: acérquela, evite reflejos y tome otra foto.',
    unknown: 'Se leyó un código, pero no tiene el formato de la cédula. Tome otra foto del reverso.',
    noReader: 'No se pudo cargar el lector de cédulas (sin conexión). Escriba la cédula o use el lector de mano.',
    camPerm: 'No se pudo acceder a la cámara — revisa los permisos del navegador (la cámara solo funciona en una página segura, https).',
    camNone: 'No se encontró ninguna cámara.',
  };
  const SIZES = [{ width: { ideal: 3840 }, height: { ideal: 2160 } }, { width: { ideal: 2560 }, height: { ideal: 1440 } }, { width: { ideal: 1920 }, height: { ideal: 1080 } }, {}];
  const STILL_MAX = 4600;                    // lado mayor máximo pedido a takePhoto (más no aporta y pesa en memoria)
  const MRZ_CROP_W = 1800;                   // ancho de trabajo del recorte de las 3 líneas (≈60 px por carácter)
  const SERVER_MAX = 2400;                   // lado mayor de la copia que va al servidor (respaldo)
  const SERVER_TIMEOUT_MS = 25000;

  /* ---------------------------------------------------------------- funciones puras (también en Node) */
  /** Recuadro guía en px del video, sobre la parte VISIBLE del elemento (bw×bh en pantalla; con object-fit: cover se recorta). Igual que _guideRect de los lectores. */
  function guideRect(vw, vh, bw, bh, ar, fill) {
    let visW = vw, visH = vh;
    if (bw && bh) { const k = Math.max(bw / vw, bh / vh); visW = bw / k; visH = bh / k; }
    const x0 = (vw - visW) / 2, y0 = (vh - visH) / 2, w = Math.min(visW * fill, visH * fill * ar), h = w / ar;
    return { x: x0 + (visW - w) / 2, y: y0 + (visH - h) / 2, w, h };
  }
  /** Rectángulo r agrandado (fracciones de su ancho/alto a cada lado) y recortado a W×H. */
  function expandRect(r, fx, fy, W, H) {
    const x0 = Math.max(0, r.x - r.w * fx), y0 = Math.max(0, r.y - r.h * fy), x1 = Math.min(W, r.x + r.w * (1 + fx)), y1 = Math.min(H, r.y + r.h * (1 + fy));
    return { x: Math.round(x0), y: Math.round(y0), w: Math.max(1, Math.round(x1 - x0)), h: Math.max(1, Math.round(y1 - y0)) };
  }
  /** Lleva un rectángulo del video (vw×vh) a la foto (pw×ph). La foto fija suele cubrir MÁS campo que el video (sensor 4:3 y video 16:9 recortado al centro): escala = la menor
      de las dos y el video queda centrado en la foto. Si la orientación no coincide (video vertical y foto horizontal) devuelve null: entonces se usa la foto completa. */
  function photoRect(r, vw, vh, pw, ph) {
    if (!vw || !vh || !pw || !ph || (vw >= vh) !== (pw >= ph)) return null;
    const k = Math.min(pw / vw, ph / vh), ox = (pw - vw * k) / 2, oy = (ph - vh * k) / 2;
    return { x: ox + r.x * k, y: oy + r.y * k, w: r.w * k, h: r.h * k };
  }
  /** Opciones de takePhoto para la resolución máxima (con el paso que pida el sensor), a partir de getPhotoCapabilities(). {} si no hay datos. */
  function stillOptions(cap) {
    const W = cap && cap.imageWidth, H = cap && cap.imageHeight;
    if (!W || !H || !W.max || !H.max) return {};
    const k = Math.min(1, STILL_MAX / Math.max(W.max, H.max));
    const fit = (rg, v) => Math.min(rg.max, Math.max(rg.min || 1, Math.round(v / (rg.step || 1)) * (rg.step || 1)));
    return { imageWidth: fit(W, W.max * k), imageHeight: fit(H, H.max * k) };
  }
  const mrzKey = (p) => [p.cedula, p.nombre1, p.nombre2, p.apellido1, p.apellido2, p.nacimiento].join('|');
  /** Decide con varias lecturas de la MISMA foto. reads: [{ parsed, conf:[n,n,n] }]. strong = CedulaReaders.mrzStrong.
      → { datos, nombres: true } con nombres confirmados (2 lecturas iguales o confianza ≥ 80 en las 3 líneas);
      → con final = true y solo lecturas «fuertes» sin confirmar: la cédula (validada por los dígitos de control) SIN nombres, si todas dicen la misma cédula;
      → null si aún no hay nada seguro. */
  function pickMrz(reads, strong, final) {
    const ok = reads.filter((r) => r && r.parsed && strong(r.parsed));
    if (!ok.length) return null;
    const votes = new Map();
    for (const r of ok) { const k = mrzKey(r.parsed); votes.set(k, (votes.get(k) || 0) + 1); }
    for (const r of ok) if (votes.get(mrzKey(r.parsed)) >= 2) return { datos: { ...r.parsed, verificada: true }, nombres: true };
    for (const r of ok) if (Array.isArray(r.conf) && r.conf.length === 3 && Math.min(...r.conf) >= 80) return { datos: { ...r.parsed, verificada: true }, nombres: true };
    if (!final) return null;
    const ced = new Set(ok.map((r) => r.parsed.cedula));
    if (ced.size !== 1) return null;
    const p = ok[0].parsed;
    return { datos: { cedula: p.cedula, nombre1: '', nombre2: '', apellido1: '', apellido2: '', nacimiento: p.nacimiento || '', verificada: true, nombresSinConfirmar: true }, nombres: false };
  }
  /** Lee las 3 líneas de un recorte: tamaños de letra 0,1,2 y, si no aparece la estructura, al revés. read(flip, attempt) → { texts:[{text,conf}] } | { } (sin 3 líneas).
      Se detiene en cuanto pickMrz confirma. Devuelve las lecturas que acumuló (para sumarlas a las de otros recortes). */
  async function readMrzCrop(read, parse, strong, reads, alive) {
    for (const flip of [false, true]) {
      let parsedAny = false;
      for (const attempt of [0, 1, 2]) {
        if (alive && !alive()) return reads;
        const r = await read(flip, attempt);
        if (!r || !r.texts) return reads;                         // no se ven 3 líneas en este recorte: girarlo no cambia eso
        const parsed = parse(r.texts.map((t) => t.text));
        reads.push({ parsed, conf: r.texts.map((t) => t.conf) });
        if (parsed) parsedAny = true;
        if (pickMrz(reads, strong, false)) return reads;
      }
      if (parsedAny) return reads;                                // la orientación era la correcta: girar 180° no ayuda
    }
    return reads;
  }
  /** Respuesta de /cedula-mrz-scan → el formato de los lectores. */
  function fromServer(j) {
    const id = j && String(j.id == null ? '' : j.id).replace(/\D/g, '');
    if (!id) return null;
    return { cedula: id, nombre1: String(j.first_name || '').trim(), nombre2: '', apellido1: String(j.last_name || '').trim(), apellido2: '', nacimiento: '', verificada: true, origen: 'servidor' };
  }

  /* ---------------------------------------------------------------- navegador */
  const decoders = {};                        // un lector por tipo y por página: el OCR (3 trabajadores) y zxing se cargan UNA vez y se reutilizan
  async function decoder(R, kind) {
    if (!decoders[kind]) {
      const d = kind === 'old' ? new R.CedulaScanner({}) : new R.MrzScanner({});
      decoders[kind] = d.init().then(() => d).catch((e) => { decoders[kind] = null; throw e; });
    }
    return decoders[kind];
  }
  function canvasOf(w, h) { const c = document.createElement('canvas'); c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h)); return c; }
  function cropCanvas(src, r, maxW) {
    const k = Math.min(1, (maxW || Infinity) / r.w), c = canvasOf(r.w * k, r.h * k), x = c.getContext('2d', { willReadFrequently: true });
    x.imageSmoothingQuality = 'high'; x.drawImage(src, r.x, r.y, r.w, r.h, 0, 0, c.width, c.height);
    return c;
  }
  function grayOf(c) {
    const d = c.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, c.width, c.height).data, g = new Uint8Array(c.width * c.height);
    for (let i = 0, j = 0; j < g.length; i += 4, j++) g[j] = (d[i] * 77 + d[i + 1] * 150 + d[i + 2] * 29) >> 8;
    return g;
  }
  function tok(el, name, fallback) { try { const v = getComputedStyle(el).getPropertyValue(name).trim(); return v || fallback; } catch (e) { return fallback; } }

  /** Toma la foto: ImageCapture.takePhoto() a resolución máxima; si no se puede, el cuadro actual del video a resolución completa. → { img, w, h, source } */
  async function takeStill(track, video) {
    if (track && typeof ImageCapture !== 'undefined' && track.readyState === 'live') {
      try {
        const ic = new ImageCapture(track);
        let opts = {}; try { opts = stillOptions(await ic.getPhotoCapabilities()); } catch (e) { /* sin capacidades: la foto por defecto */ }
        let blob; try { blob = await ic.takePhoto(opts); } catch (e) { blob = await ic.takePhoto(); }
        const bmp = await createImageBitmap(blob, { imageOrientation: 'from-image' });
        if (bmp.width && bmp.height) return { img: bmp, w: bmp.width, h: bmp.height, source: 'still' };
      } catch (e) { /* algunos celulares no la dan (o la cámara está ocupada): se usa el cuadro del video */ }
    }
    const c = canvasOf(video.videoWidth, video.videoHeight);
    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
    return { img: c, w: c.width, h: c.height, source: 'frame' };
  }

  async function decodeOld(R, shot, guidePhoto, alive) {
    const sc = await decoder(R, 'old');
    let unknown = false;
    sc.onResult = () => {}; sc.onStatus = () => {}; sc.onUnknown = () => { unknown = true; };
    const sources = [];
    if (guidePhoto) sources.push([cropCanvas(shot.img, expandRect(guidePhoto, 0.06, 0.9, shot.w, shot.h)), 7000]);     // el recuadro con margen (la cédula rara vez queda exacta)
    sources.push([shot.img, 9000]);                                                                                   // la foto completa: el localizador busca el código en cualquier parte y ángulo
    for (const [src, budgetMs] of sources) {
      if (!alive()) return { datos: null };
      const datos = await sc.scanImage(src, { budgetMs });
      if (datos) return { datos };
    }
    return { datos: null, unknown };
  }

  async function decodeNew(R, shot, guidePhoto, alive) {
    const mz = await decoder(R, 'new');
    mz.onStatus = () => {};
    const reads = [];
    const crops = guidePhoto ? [expandRect(guidePhoto, 0.03, 0.08, shot.w, shot.h), expandRect(guidePhoto, 0.08, 0.45, shot.w, shot.h)] : [];
    for (const r of crops) {
      if (!alive()) return null;
      const c = cropCanvas(shot.img, r, MRZ_CROP_W), g = grayOf(c);
      await readMrzCrop((flip, attempt) => mz._read(g, c.width, c.height, { flip, attempt }), R.parseMrz, R.mrzStrong, reads, alive);
      const got = pickMrz(reads, R.mrzStrong, false); if (got) return got.datos;
    }
    if (!alive()) return null;
    let full = null; mz.onResult = (d) => { full = d; };                                                          // la foto completa: las 3 líneas en cualquier parte y orientación
    await mz.scanImage(shot.img);                                                                                 // lienzo o ImageBitmap: el lector hace su propia copia
    mz.onResult = () => {};
    if (full) reads.push({ parsed: full, conf: null });
    const got = pickMrz(reads, R.mrzStrong, true);
    return got ? got.datos : null;
  }

  /** Respaldo: el servidor lee las 3 líneas (Tesseract). Solo con red, con evento y fuera del modo sin conexión. La copia se envía y se descarta; el servidor tampoco la guarda. */
  async function serverMrz(shot, eventId, alive) {
    const offline = (typeof navigator !== 'undefined' && navigator.onLine === false) || (window.GoldenContingency && window.GoldenContingency.instance && window.GoldenContingency.instance.active && window.GoldenContingency.instance.active());
    if (!eventId || offline || !alive()) return null;
    const k = Math.min(1, SERVER_MAX / Math.max(shot.w, shot.h)), c = cropCanvas(shot.img, { x: 0, y: 0, w: shot.w, h: shot.h }, shot.w * k);
    let blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.92));
    if (!blob || !alive()) return null;
    const fd = new FormData(); fd.append('file', blob, 'reverso.jpg'); blob = null;
    const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null, t = ctl ? setTimeout(() => ctl.abort(), SERVER_TIMEOUT_MS) : 0;
    try {
      const res = await fetch(`/api/events/${encodeURIComponent(eventId)}/cedula-mrz-scan`, { method: 'POST', body: fd, credentials: 'same-origin', signal: ctl ? ctl.signal : undefined });
      if (!res.ok) return null;
      return fromServer(await res.json().catch(() => null));
    } catch (e) { return null; } finally { if (t) clearTimeout(t); }
  }

  function attach(o) {
    const kind = o.kind === 'new' ? 'new' : 'old', G = GUIDE[kind], video = o.video, overlay = o.overlay, btn = o.button;
    const say = (m, k) => { if (!dead && o.onStatus) o.onStatus(m, k || ''); };
    let dead = false, stream = null, track = null, busy = false, raf = 0, R = null, frozen = false;
    const alive = () => !dead;
    const label = btn ? btn.textContent : '';

    function draw() {
      raf = 0;
      if (dead || !overlay || !video.videoWidth) return;
      const vw = video.videoWidth, vh = video.videoHeight, r = video.getBoundingClientRect(), g = guideRect(vw, vh, r.width, r.height, G.ar, G.fill), x = overlay.getContext('2d');
      if (overlay.width !== vw || overlay.height !== vh) { overlay.width = vw; overlay.height = vh; }
      const line = busy ? tok(overlay, '--gw-gold-2', '#e8c25a') : tok(overlay, '--gw-ok-line', '#1f8a4c');
      x.clearRect(0, 0, vw, vh);
      x.fillStyle = tok(overlay, '--gw-overlay', 'rgba(0,0,0,.45)');                   // oscurece lo que queda fuera del recuadro
      x.beginPath(); x.rect(0, 0, vw, vh); x.rect(g.x, g.y, g.w, g.h); x.fill('evenodd');
      const lw = Math.max(4, vw / 260), c = Math.min(g.h * 0.35, g.w * 0.06);
      x.lineWidth = lw; x.strokeStyle = line; x.lineCap = 'round'; x.strokeRect(g.x, g.y, g.w, g.h); x.lineWidth = lw * 1.8;
      [[g.x, g.y, 1, 1], [g.x + g.w, g.y, -1, 1], [g.x, g.y + g.h, 1, -1], [g.x + g.w, g.y + g.h, -1, -1]].forEach(([px, py, sx, sy]) => { x.beginPath(); x.moveTo(px, py + sy * c); x.lineTo(px, py); x.lineTo(px + sx * c, py); x.stroke(); });
      if (kind === 'new') {                                                             // 3 renglones de ayuda: dónde caen las 3 líneas
        x.lineWidth = lw * 0.5; x.setLineDash([lw * 3, lw * 3]);
        [1 / 6, 0.5, 5 / 6].forEach((f) => { x.beginPath(); x.moveTo(g.x + g.w * 0.03, g.y + g.h * f); x.lineTo(g.x + g.w * 0.97, g.y + g.h * f); x.stroke(); });
        x.setLineDash([]);
      }
    }
    const redraw = () => { if (!raf && !dead) raf = requestAnimationFrame(draw); };
    window.addEventListener('resize', redraw);

    function setBusy(on) {
      busy = on;
      if (btn) { btn.disabled = on || !stream; btn.textContent = on ? 'Procesando…' : label; btn.setAttribute('aria-busy', String(on)); }
      redraw();
    }
    function resumePreview() { if (frozen && !dead && stream) { frozen = false; video.play().catch(() => {}); } }

    async function openCamera() {
      let last = null, s = null;
      for (const size of SIZES) {
        try { s = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: 'environment' }, ...size } }); break; }
        catch (e) { last = e; if (e.name === 'NotAllowedError' || e.name === 'SecurityError' || e.name === 'NotFoundError') break; }
      }
      if (dead) { if (s) s.getTracks().forEach((t) => t.stop()); return; }
      if (!s) { say(last && last.name === 'NotFoundError' ? MSG.camNone : MSG.camPerm, 'err'); return; }
      stream = s; track = s.getVideoTracks()[0];
      try { await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) { /* sin control de enfoque */ }
      video.srcObject = s; video.setAttribute('playsinline', ''); video.muted = true;
      video.addEventListener('loadedmetadata', redraw);
      try { await video.play(); } catch (e) { /* iOS: arranca con el primer toque */ }
      if (dead) return;
      if (btn) btn.disabled = busy;
      redraw(); setTimeout(redraw, 300);
      if (!busy) say(kind === 'old' ? MSG.aimOld : MSG.aimNew);
    }

    async function shoot() {
      if (busy || dead || !stream || !video.videoWidth) return;
      setBusy(true); say(MSG.processing, 'warn');
      let shot = null;
      try {
        const vw = video.videoWidth, vh = video.videoHeight, r = video.getBoundingClientRect(), g = guideRect(vw, vh, r.width, r.height, G.ar, G.fill);
        shot = await takeStill(track, video);
        if (dead) return;
        video.pause(); frozen = true;                                                   // lo que se ve es lo que se está procesando
        await new Promise((ok) => setTimeout(ok, 30));                                  // deja pintar «Procesando la foto…» antes del cálculo pesado
        const guidePhoto = photoRect(g, vw, vh, shot.w, shot.h);
        let datos = null, unknown = false, readerErr = null;
        if (!R) { try { R = await o.readers(); } catch (e) { readerErr = e; } }
        if (R && !dead) {
          try {
            if (kind === 'old') { const out = await decodeOld(R, shot, guidePhoto, alive); datos = out.datos; unknown = !!out.unknown; }
            else datos = await decodeNew(R, shot, guidePhoto, alive);
          } catch (e) { readerErr = e; }
        }
        if (!datos && kind === 'new' && !dead) { say(MSG.server, 'warn'); datos = await serverMrz(shot, o.eventId, alive); }
        if (dead) return;
        if (datos) { say('Cédula leída.', 'ok'); setBusy(false); o.onResult(datos, kind); resumePreview(); return; }
        say(readerErr && !R ? MSG.noReader : unknown ? MSG.unknown : MSG.fail, 'err');
      } catch (e) {
        say(MSG.fail, 'err');
      } finally {
        if (shot && shot.img && shot.img.close) shot.img.close();                       // la foto se descarta en memoria: no se guarda en ningún lado
        shot = null;
        if (!dead) { setBusy(false); resumePreview(); }
      }
    }
    if (btn) { btn.disabled = true; btn.addEventListener('click', shoot); }

    say(MSG.loading);
    openCamera();
    // Los lectores se van cargando mientras el operador encuadra (la primera vez la cédula nueva baja el OCR: unos segundos).
    Promise.resolve().then(() => o.readers()).then((r) => { R = r; return decoder(r, kind); }).catch(() => { /* se reintenta al tomar la foto */ });

    return {
      shoot,
      stop() {
        dead = true;
        if (raf) cancelAnimationFrame(raf);
        window.removeEventListener('resize', redraw);
        if (btn) { btn.removeEventListener('click', shoot); btn.disabled = false; btn.textContent = label; btn.removeAttribute('aria-busy'); }
        if (stream) stream.getTracks().forEach((t) => t.stop());                        // libera la cámara (se apaga la luz del celular/computador)
        stream = track = null;
        try { video.pause(); video.srcObject = null; } catch (e) { /* ya liberado */ }
        if (overlay) overlay.getContext('2d').clearRect(0, 0, overlay.width, overlay.height);
      },
    };
  }

  const api = { attach, guideRect, expandRect, photoRect, stillOptions, pickMrz, readMrzCrop, fromServer, MSG, GUIDE };
  if (typeof window !== 'undefined') window.CedulaFoto = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
