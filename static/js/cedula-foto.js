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
    glare: 'Hay un brillo sobre la cédula: inclínela un poco o aléjela de la luz directa.',
    glareTorch: 'Hay un brillo sobre la cédula: apague la linterna o incline un poco la cédula.',
    failGlare: 'No se pudo leer por un brillo sobre la cédula: inclínela un poco (o apague la linterna) y tome otra foto.',
    partial: 'No se leyó completa. ¿Es alguna de estas personas? Confírmelo con el documento.',
    torchOn: 'Linterna', torchOff: 'Apagar linterna',
  };
  const SIZES = [{ width: { ideal: 3840 }, height: { ideal: 2160 } }, { width: { ideal: 2560 }, height: { ideal: 1440 } }, { width: { ideal: 1920 }, height: { ideal: 1080 } }, {}];
  const STILL_MAX = 4600;                    // lado mayor máximo pedido a takePhoto (más no aporta y pesa en memoria)
  const LOCATE_W = 2400;                     // recorte holgado alrededor del recuadro para ubicar las 3 líneas donde estén (el lector lo lleva a ≤ 2400 px)
  const MRZ_CROP_W = 1800;                   // ancho de trabajo del recorte de las 3 líneas (≈60 px por carácter)
  const SERVER_MAX = 2400;                   // lado mayor de la copia que va al servidor (respaldo)
  const SERVER_TIMEOUT_MS = 25000;
  const HD_SHORT_SIDE = 1080;                 // video con lado corto ≥ 1080 px: su cuadro ya es alta definición (no hace falta takePhoto)
  const OLD_BUDGET_MS = [2000, 1000, 1000, 2000];   // cédula vieja: recuadro de la foto 1, de la 2 y de la 3 (ráfaga), y foto 1 completa: ≈6 s en el peor caso
  const BURST = 3, BURST_GAP_MS = 110;       // ráfaga: 3 cuadros seguidos (≈0,25 s). Lo que un brillo o el pulso arruinan en uno suele verse en otro
  const GLARE_LEVEL = 245, GLARE_RATIO = 0.012;   // brillo: más del 1,2 % del recuadro casi blanco en los tres colores (el fondo de la cédula no llega a eso)        // cédula vieja: recuadro guía, luego foto completa (antes 7 s + 9 s: lo que no sale en ~5 s no sale con más tiempo; mejor otra foto)
  const SERVER_HEAD_START_MS = 1200;         // cédula nueva: si el navegador no la leyó en este tiempo, el servidor arranca EN PARALELO (gana el primero que la valide)

  /* ---------------------------------------------------------------- funciones puras (también en Node) */
  /** Fracción de píxeles casi blancos (R, G y B ≥ GLARE_LEVEL) en una imagen RGBA: el reflejo «quema» el color; la cédula impresa no. */
  function glareRatio(data) {
    let hot = 0; const n = Math.floor(data.length / 4) || 1;
    for (let i = 0; i < data.length; i += 4) if (data[i] >= GLARE_LEVEL && data[i + 1] >= GLARE_LEVEL && data[i + 2] >= GLARE_LEVEL) hot++;
    return hot / n;
  }
  /** Lo que SÍ se alcanzó a leer de la cédula nueva cuando ninguna lectura quedó validada → {cedula, first_name, last_name} para buscar parecidas, o null.
   *  Se queda con la lectura que más controles pasa (y, a igualdad, la que trae más dígitos). Nunca se usa para acreditar: solo para proponer. */
  function partialFrom(reads) {
    let best = null, bestScore = -1;
    for (const r of reads || []) {
      const p = r && r.parsed; if (!p) continue;
      const digits = String(p.cedula || '').replace(/\D/g, '');
      if (digits.length < 5 && !p.apellido1) continue;
      const c = p.checks || {};
      const score = (c.birth ? 4 : 0) + (c.expiry ? 4 : 0) + (c.composite === true ? 4 : 0) + digits.length / 100 + (p.apellido1 ? 0.5 : 0);
      if (score > bestScore) { bestScore = score; best = p; }
    }
    if (!best) return null;
    return { cedula: String(best.cedula || '').replace(/\D/g, ''), first_name: [best.nombre1, best.nombre2].filter(Boolean).join(' '), last_name: [best.apellido1, best.apellido2].filter(Boolean).join(' ') };
  }
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
    // 24-nov-2026 (rapidez): si el video ya es HD (lado corto ≥ 1080 px) se usa su cuadro: es inmediato y basta para el recuadro guía. takePhoto() solo
    // cuando la cámara no da video HD (en Android reenfoca y decodifica un JPEG de 12 MP: 1-3 s de espera).
    if (Math.min(video.videoWidth || 0, video.videoHeight || 0) >= HD_SHORT_SIDE) return frameOf(video);
    if (track && typeof ImageCapture !== 'undefined' && track.readyState === 'live') {
      try {
        const ic = new ImageCapture(track);
        let opts = {}; try { opts = stillOptions(await ic.getPhotoCapabilities()); } catch (e) { /* sin capacidades: la foto por defecto */ }
        let blob; try { blob = await ic.takePhoto(opts); } catch (e) { blob = await ic.takePhoto(); }
        const bmp = await createImageBitmap(blob, { imageOrientation: 'from-image' });
        if (bmp.width && bmp.height) return { img: bmp, w: bmp.width, h: bmp.height, source: 'still' };
      } catch (e) { /* algunos celulares no la dan (o la cámara está ocupada): se usa el cuadro del video */ }
    }
    return frameOf(video);
  }
  function frameOf(video) {
    const c = canvasOf(video.videoWidth, video.videoHeight);
    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
    return { img: c, w: c.width, h: c.height, source: 'frame' };
  }

  /** Cédula vieja sobre la RÁFAGA: el recuadro de cada cuadro (lo que un brillo o el pulso arruinan en uno suele verse en otro) y al final la foto completa. */
  async function decodeOld(R, shots, guidePhoto, alive) {
    const sc = await decoder(R, 'old');
    let unknown = false;
    sc.onResult = () => {}; sc.onStatus = () => {}; sc.onUnknown = () => { unknown = true; };
    const sources = [];
    shots.forEach((shot, k) => { if (guidePhoto && k < 3) sources.push([() => cropCanvas(shot.img, expandRect(guidePhoto, 0.06, 0.9, shot.w, shot.h)), OLD_BUDGET_MS[k]]); });   // el recuadro con margen
    sources.push([() => shots[0].img, OLD_BUDGET_MS[3]]);                                                              // la foto completa: el localizador busca el código en cualquier parte y ángulo
    for (const [src, budgetMs] of sources) {
      if (!alive()) return { datos: null };
      const datos = await sc.scanImage(src(), { budgetMs });
      if (datos) return { datos };
    }
    return { datos: null, unknown };
  }

  /** Cédula nueva sobre la ráfaga. `reads` se comparte con quien llama: si nada queda validado, de ahí sale lo que SÍ se leyó (partialFrom). La votación
   *  (pickMrz) junta las lecturas de los tres cuadros: dos lecturas iguales de cuadros distintos valen como confirmación de los nombres. */
  async function decodeNew(R, shots, guidePhoto, alive, withFull = true, reads = []) {
    const mz = await decoder(R, 'new');
    mz.onStatus = () => {};
    const plan = [];
    shots.forEach((shot, k) => {
      if (!guidePhoto) return;
      plan.push([shot, expandRect(guidePhoto, 0.03, 0.08, shot.w, shot.h)]);                   // ajustado al recuadro
      if (k === 0) plan.push([shot, expandRect(guidePhoto, 0.08, 0.45, shot.w, shot.h)]);      // holgado (las líneas quedaron un poco fuera), solo en el primero
    });
    const locate = async (shot) => {                                                          // las 3 líneas DONDE ESTÉN cerca del recuadro: más pequeñas, corridas o un poco fuera
      if (!guidePhoto || !alive()) return;
      const c = cropCanvas(shot.img, expandRect(guidePhoto, 0.22, 1.6, shot.w, shot.h), LOCATE_W);
      let found = null; mz.onResult = (d) => { found = d; };
      try { await mz.scanImage(c); } finally { mz.onResult = () => {}; }
      if (found) reads.push({ parsed: found, conf: null });
    };
    for (const [idx, [shot, r]] of plan.entries()) {
      if (!alive()) return null;
      const c = cropCanvas(shot.img, r, MRZ_CROP_W), g = grayOf(c);
      await readMrzCrop((flip, attempt) => mz._read(g, c.width, c.height, { flip, attempt }), R.parseMrz, R.mrzStrong, reads, alive);
      let got = pickMrz(reads, R.mrzStrong, false); if (got) return got.datos;
      if (idx === 0) {                                                                         // 24-nov: la cédula no llenó el recuadro (o se salió un poco)
        const before = reads.length;
        await locate(shot);
        if (reads.length > before && R.mrzStrong(reads[reads.length - 1].parsed)) {           // número validado: se confirma con el 2.º cuadro (los nombres no tienen dígito de control)
          if (shots[1]) await locate(shots[1]);
          got = pickMrz(reads, R.mrzStrong, false) || pickMrz(reads, R.mrzStrong, true);      // sin segunda coincidencia: entra con la cédula validada y sin nombres (como siempre)
          if (got) return got.datos;
        }
      }
    }
    if (!alive()) return null;
    if (!withFull) { const g2 = pickMrz(reads, R.mrzStrong, true); return g2 ? g2.datos : null; }   // con servidor disponible, él lee la foto completa (más rápido que el OCR del celular)
    let full = null; mz.onResult = (d) => { full = d; };                                                          // la foto completa: las 3 líneas en cualquier parte y orientación
    await mz.scanImage(shots[0].img);                                                                             // lienzo o ImageBitmap: el lector hace su propia copia
    mz.onResult = () => {};
    if (full) reads.push({ parsed: full, conf: null });
    const got = pickMrz(reads, R.mrzStrong, true);
    return got ? got.datos : null;
  }

  /** Respaldo: el servidor lee las 3 líneas (Tesseract). Solo con red, con evento y fuera del modo sin conexión. La copia se envía y se descarta; el servidor tampoco la guarda. */
  function serverUsable(eventId) {
    const offline = (typeof navigator !== 'undefined' && navigator.onLine === false) || (typeof window !== 'undefined' && window.GoldenContingency && window.GoldenContingency.instance && window.GoldenContingency.instance.active && window.GoldenContingency.instance.active());
    return !!eventId && !offline;
  }
  /** El primero de las promesas que entregue algo (no null); null si ninguna. Las demás se ignoran. */
  function firstFound(promises) {
    return new Promise((done) => {
      let left = promises.length; if (!left) { done(null); return; }
      promises.forEach((p) => Promise.resolve(p).catch(() => null).then((v) => { if (v) { done(v); done = () => {}; } else if (--left === 0) done(null); }));
    });
  }
  /** Cédula nueva: navegador y servidor en carrera. El servidor arranca a los SERVER_HEAD_START_MS (o antes, si el navegador ya se rindió); gana el primero
   *  que entregue una lectura validada y el otro se corta (alive). Sin red / sin evento / modo sin conexión: solo el navegador, con su lectura de la foto completa. */
  async function decodeNewRace(R, shots, guidePhoto, alive, eventId, reads) {
    const shot = shots[0];
    const useServer = serverUsable(eventId);
    if (!useServer) return R ? decodeNew(R, shots, guidePhoto, alive, true, reads) : null;
    let won = false, kick = null;
    const still = () => alive() && !won;
    const startServer = new Promise((ok) => { kick = ok; setTimeout(ok, SERVER_HEAD_START_MS); });
    const local = R ? decodeNew(R, shots, guidePhoto, still, false, reads).catch(() => null).then((d) => { if (!d) kick(); return d; }) : (kick(), null);
    const server = startServer.then(() => (still() ? serverMrz(shot, eventId, still) : null));
    const d = await firstFound([local, server]);
    won = true;
    return d;
  }
  async function serverMrz(shot, eventId, alive) {
    if (!serverUsable(eventId) || !alive()) return null;
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
    let dead = false, stream = null, track = null, busy = false, raf = 0, R = null, frozen = false, glare = false, torchOn = false, glareTimer = 0, torchBtn = null, choices = null;
    const alive = () => !dead;
    const label = btn ? btn.textContent : '';

    function draw() {
      raf = 0;
      if (dead || !overlay || !video.videoWidth) return;
      const vw = video.videoWidth, vh = video.videoHeight, r = video.getBoundingClientRect(), g = guideRect(vw, vh, r.width, r.height, G.ar, G.fill), x = overlay.getContext('2d');
      if (overlay.width !== vw || overlay.height !== vh) { overlay.width = vw; overlay.height = vh; }
      const line = busy ? tok(overlay, '--gw-gold-2', '#e8c25a') : glare ? tok(overlay, '--gw-warn-line', '#c98a00') : tok(overlay, '--gw-ok-line', '#1f8a4c');
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
    const aimMsg = () => (kind === 'old' ? MSG.aimOld : MSG.aimNew);

    /* Brillo EN VIVO: cada 0,5 s se mira el recuadro (en pequeño) y, si hay reflejo, se avisa ANTES de tomar la foto y el recuadro se pone ámbar. */
    const probe = canvasOf(240, 60);
    function checkGlare() {
      if (dead || busy || frozen || !video.videoWidth) return;
      const vw = video.videoWidth, vh = video.videoHeight, r = video.getBoundingClientRect(), g = guideRect(vw, vh, r.width, r.height, G.ar, G.fill);
      probe.height = Math.max(8, Math.round(probe.width / G.ar));
      const x = probe.getContext('2d', { willReadFrequently: true });
      try { x.drawImage(video, g.x, g.y, g.w, g.h, 0, 0, probe.width, probe.height); } catch (e) { return; }
      const now = glareRatio(x.getImageData(0, 0, probe.width, probe.height).data) > GLARE_RATIO;
      if (now !== glare) { glare = now; redraw(); if (!busy) say(glare ? (torchOn ? MSG.glareTorch : MSG.glare) : aimMsg(), glare ? 'warn' : ''); }
    }

    /* Linterna: solo si el celular la ofrece (Android Chrome). En cédulas plastificadas a veces CAUSA el brillo: por eso el aviso pide apagarla. */
    function setupTorch() {
      let caps = {}; try { caps = track && track.getCapabilities ? track.getCapabilities() : {}; } catch (e) { caps = {}; }
      if (!caps.torch || !video.parentElement) return;
      torchBtn = document.createElement('button');
      torchBtn.type = 'button'; torchBtn.className = 'gw-btn gw-btn--secondary gw-btn--sm gw-cam__torch'; torchBtn.textContent = MSG.torchOn; torchBtn.setAttribute('aria-pressed', 'false');
      torchBtn.addEventListener('click', async () => {
        const want = !torchOn;
        try { await track.applyConstraints({ advanced: [{ torch: want }] }); torchOn = want; } catch (e) { return; }
        torchBtn.textContent = torchOn ? MSG.torchOff : MSG.torchOn; torchBtn.setAttribute('aria-pressed', String(torchOn));
      });
      video.parentElement.appendChild(torchBtn);
    }

    /* Lectura a medias (cédula nueva) → personas PARECIDAS de la base. NUNCA acredita sola: el operador elige y la elegida sigue el camino EXACTO de siempre. */
    function clearChoices() { if (choices) { choices.remove(); choices = null; } }
    async function offerNear(partial) {
      if (!partial || !o.eventId || !serverUsable(o.eventId) || dead) return false;
      let j = null;
      try {
        const res = await fetch(`/api/events/${encodeURIComponent(o.eventId)}/cedula-near`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(partial) });
        if (res.ok) j = await res.json();
      } catch (e) { j = null; }
      const list = j ? [...(j.by_number || []), ...(j.by_name || [])] : [];
      if (!list.length || dead) return false;
      clearChoices();
      choices = document.createElement('div');
      choices.className = 'gw-cam__choices gw-alert gw-alert--warn'; choices.setAttribute('role', 'group');
      const head = document.createElement('p'); head.className = 'gw-cam__choices-head'; head.textContent = MSG.partial; choices.appendChild(head);
      list.forEach((c) => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'gw-btn gw-btn--secondary gw-btn--block gw-cam__choice';
        b.textContent = `${[c.first_name, c.last_name].filter(Boolean).join(' ') || 'Sin nombre'} · ${c.id}${c.in_event ? ' · en este evento' : ''}${c.entity ? ' · ' + c.entity : ''}`;
        b.addEventListener('click', () => {
          const d = { cedula: String(c.id), nombre1: c.first_name || '', nombre2: '', apellido1: c.last_name || '', apellido2: '', nacimiento: '', verificada: false, origen: 'operador' };
          clearChoices(); say('Cédula elegida por el operador.', 'ok'); o.onResult(d, kind);
        });
        choices.appendChild(b);
      });
      const none = document.createElement('button');
      none.type = 'button'; none.className = 'gw-btn gw-btn--ghost gw-btn--block'; none.textContent = 'Ninguna: tomar otra foto';
      none.addEventListener('click', () => { clearChoices(); say(aimMsg()); });
      choices.appendChild(none);
      const host = (o.status && o.status.parentElement) || (video.parentElement && video.parentElement.parentElement);
      if (host) host.appendChild(choices);
      return true;
    }

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
      setupTorch();
      glareTimer = setInterval(checkGlare, 500);
      if (!busy) say(aimMsg());
    }

    async function shoot() {
      if (busy || dead || !stream || !video.videoWidth) return;
      clearChoices();
      setBusy(true); say(MSG.processing, 'warn');
      let shots = [];
      const reads = [];
      const hadGlare = glare;
      try {
        const vw = video.videoWidth, vh = video.videoHeight, r = video.getBoundingClientRect(), g = guideRect(vw, vh, r.width, r.height, G.ar, G.fill);
        shots.push(await takeStill(track, video));
        if (shots[0].source === 'frame') for (let k = 1; k < BURST && !dead; k++) { await new Promise((ok) => setTimeout(ok, BURST_GAP_MS)); shots.push(frameOf(video)); }   // ráfaga del video (mismo encuadre que el primer cuadro)
        if (dead) return;
        video.pause(); frozen = true;                                                   // lo que se ve es lo que se está procesando
        await new Promise((ok) => setTimeout(ok, 30));                                  // deja pintar «Procesando la foto…» antes del cálculo pesado
        const shot = shots[0];
        const guidePhoto = photoRect(g, vw, vh, shot.w, shot.h);
        let datos = null, unknown = false, readerErr = null;
        if (!R) { try { R = await o.readers(); } catch (e) { readerErr = e; } }
        if (R && !dead) {
          try {
            if (kind === 'old') { const out = await decodeOld(R, shots, guidePhoto, alive); datos = out.datos; unknown = !!out.unknown; }
            else datos = await decodeNewRace(R, shots, guidePhoto, alive, o.eventId, reads);
          } catch (e) { readerErr = e; }
        }
        if (!datos && kind === 'new' && !R && !dead) datos = await decodeNewRace(null, shots, guidePhoto, alive, o.eventId, reads);   // el lector del navegador no cargó: solo el servidor
        if (dead) return;
        if (datos) { say('Cédula leída.', 'ok'); setBusy(false); o.onResult(datos, kind); resumePreview(); return; }
        if (kind === 'new' && await offerNear(partialFrom(reads))) { say(MSG.partial, 'warn'); return; }
        say(readerErr && !R ? MSG.noReader : unknown ? MSG.unknown : (hadGlare || glare) ? MSG.failGlare : MSG.fail, 'err');
      } catch (e) {
        say(MSG.fail, 'err');
      } finally {
        shots.forEach((x) => { if (x && x.img && x.img.close) x.img.close(); });       // las fotos se descartan en memoria: no se guardan en ningún lado
        shots = [];
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
        if (glareTimer) clearInterval(glareTimer);
        if (torchBtn) torchBtn.remove();
        clearChoices();
        window.removeEventListener('resize', redraw);
        if (btn) { btn.removeEventListener('click', shoot); btn.disabled = false; btn.textContent = label; btn.removeAttribute('aria-busy'); }
        if (stream) stream.getTracks().forEach((t) => t.stop());                        // libera la cámara (se apaga la luz del celular/computador)
        stream = track = null;
        try { video.pause(); video.srcObject = null; } catch (e) { /* ya liberado */ }
        if (overlay) overlay.getContext('2d').clearRect(0, 0, overlay.width, overlay.height);
      },
    };
  }

  const api = { attach, firstFound, glareRatio, partialFrom, guideRect, expandRect, photoRect, stillOptions, pickMrz, readMrzCrop, fromServer, MSG, GUIDE };
  if (typeof window !== 'undefined') window.CedulaFoto = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
