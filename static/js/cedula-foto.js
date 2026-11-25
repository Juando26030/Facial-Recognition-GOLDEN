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
     - RECORTE AUTOMÁTICO (24-nov-2026, «como CamScanner»): el recuadro es una AYUDA, no un requisito. Cédula nueva: CedulaReaders.mrzFind ubica las 3 líneas en cualquier
       parte de la foto (pequeña, corrida, girada o de lado), las endereza y entrega solo esa zona; eso mismo es lo que va al servidor. Cédula vieja: después del recuadro se
       pasa la foto COMPLETA de cada cuadro (el lector ubica, endereza y recorta el código). Si la cédula se vio pero sin detalle, se toma una foto fija a resolución máxima
       y se repite. Probado con Chrome real y cámara simulada (docs/PRUEBA_LECTOR_CEDULA.md § Recorte automático).
   El QR NO pasa por aquí (sigue en vivo en qr.js). Uso (desde qr.js):
     const h = CedulaFoto.attach({ kind: 'old'|'new', video, overlay, button, readers, eventId, onStatus(msg, tipo), onResult(datos) });   …   h.stop();
   datos = { cedula, nombre1, nombre2, apellido1, apellido2, nacimiento, … } (el mismo formato de los lectores). Las funciones puras se exportan para tests/js/cedula_foto_check.js. */
(function () {
  'use strict';
  const GUIDE = { old: { ar: 4.8, fill: 0.92 }, new: { ar: 4.6, fill: 0.94 } };          // las mismas proporciones del recuadro de los lectores en vivo
  const MSG = {
    aimOld: 'Apunte al código de barras del reverso (lo ideal: dentro del recuadro) y pulse «Tomar foto».',
    aimNew: 'Apunte a las 3 líneas de letras y números del reverso (lo ideal: dentro del recuadro) y pulse «Tomar foto».',
    loading: 'Cargando el lector…',
    processing: 'Procesando la foto…',
    server: 'Procesando la foto… (revisión en el servidor)',
    fail: 'No se pudo leer la cédula: acérquela, evite reflejos y tome otra foto.',
    detail: 'Procesando… tomando una foto con más detalle.',
    noLines: 'No se ven las 3 líneas de la cédula: que queden completas dentro de la foto, sin brillo, y tome otra foto.',
    noCode: 'No se ve el código de barras: que quede completo dentro de la foto, sin brillo, y tome otra foto.',
    covered: 'Parte de la cédula no se ve (un brillo, una sombra o un dedo la tapa): déjela completa a la vista y tome otra foto.',
    small: 'La cédula quedó muy lejos: acérquela y tome otra foto.',
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
  // FLUIDEZ (24-nov-2026, tableta que no es de última generación: la vista previa iba trabada y con retraso). Mostrar video 4K en vivo es lo que más pesa:
  //  · equipo modesto (≤ 4 núcleos o ≤ 3 GB): se pide 1080p de entrada; · en los demás se MIDE la vista previa y, si va a menos de FPS_MIN, se baja a 1080p (y a 720p si
  //    ni así). La lectura no cambia: con 1080p se sigue usando el cuadro del video; con menos, la foto fija del sensor (takePhoto), igual que antes en cámaras sin HD.
  const FPS_MIN = 18, FPS_MIN_720 = 12, FPS_WARMUP_MS = 500, FPS_WINDOW_MS = 1200, OVERLAY_DPR_MAX = 2;
  /** ¿Equipo modesto? (puro: recibe navigator) */
  function lowEnd(nav) { return !!nav && ((nav.hardwareConcurrency > 0 && nav.hardwareConcurrency <= 4) || (nav.deviceMemory > 0 && nav.deviceMemory <= 3)); }
  /** Resolución a la que conviene bajar según los cuadros por segundo medidos y el lado corto actual del video → {width,height} | null (quedarse como está). */
  function stepDown(fps, shortSide, canStill) {
    if (!(fps > 0)) return null;
    if (shortSide > 1080 && fps < FPS_MIN) return { width: 1920, height: 1080 };
    if (canStill && shortSide > 720 && fps < FPS_MIN_720) return { width: 1280, height: 720 };   // solo si hay foto fija (takePhoto): por debajo de 1080p el cuadro del video no alcanza para leer
    return null;
  }
  const STILL_MAX = 4600;                    // lado mayor máximo pedido a takePhoto (más no aporta y pesa en memoria)
  const MRZ_CROP_W = 1800;                   // ancho de trabajo del recorte de las 3 líneas (≈60 px por carácter)
  const SERVER_MAX = 2400;                   // lado mayor de la copia que va al servidor (respaldo)
  const SERVER_TIMEOUT_MS = 25000;
  const HD_SHORT_SIDE = 1080;                 // video con lado corto ≥ 1080 px: su cuadro ya es alta definición (no hace falta takePhoto)
  const OLD_BUDGET_MS = [1000, 1800, 900, 900];   // cédula vieja: recuadro de la foto 1 y luego la foto COMPLETA de cada cuadro de la ráfaga (el código donde esté): ≈4,6 s en el peor caso
  const FIND_MAX = 3200;                     // lado mayor de la copia en gris donde se buscan las 3 líneas (recorte automático)
  const NEW_DEADLINE_MS = 5500;              // cédula nueva: tope de espera por foto (navegador y servidor); pasado esto se pide otra foto
  const SMALL_LETTER_PX = 24, SMALL_PPM = 2.2;   // letras de menos de 24 px de alto / código con menos de 2,2 px por módulo: «muy lejos» (vale la pena la foto fija)
  const WASH_K = 0.4;                        // una celda está «lavada» si su contraste es < 40 % del contraste típico de las demás
  const SERVER_CROP_PAD = 36;                // borde blanco alrededor del recorte que va al servidor
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
  /** CHEQUEO PREVIO (24-nov-2026, pedido de Juan David: avisar de una vez en lugar de dejar pensando). Zonas donde DEBE haber tinta en todo el ancho (cada una de las
   *  3 líneas; las filas del código de barras) partidas en `cols` celdas: una celda con mucho menos contraste que las demás está «lavada» (brillo) o tapada.
   *  g: gris w×h; rects: [{x0,x1,y0,y1}] → { n, low, bright } (bright = lavadas MÁS claras que lo normal: eso es brillo; si no, sombra u objeto). */
  function washedCells(g, w, h, rects, cols) {
    const cells = [], hist = new Uint32Array(256); let rowN = 0;
    for (const r of rects) {
      const x0 = Math.max(0, r.x0 | 0), x1 = Math.min(w - 1, r.x1 | 0), y0 = Math.max(0, r.y0 | 0), y1 = Math.min(h - 1, r.y1 | 0);
      if (x1 - x0 < cols * 2 || y1 - y0 < 2) continue;
      const row = rowN++;
      for (let c = 0; c < cols; c++) {
        const a = x0 + Math.round((x1 - x0 + 1) * c / cols), b = x0 + Math.round((x1 - x0 + 1) * (c + 1) / cols); let sum = 0, n = 0; hist.fill(0);
        for (let y = y0; y <= y1; y++) { const o = y * w; for (let x = a; x < b; x++) { const v = g[o + x]; hist[v]++; sum += v; n++; } }
        if (!n) continue;
        let lo = 0, hi = 255, acc = 0; const cut = n * 0.06;
        for (acc = 0; lo < 255 && (acc += hist[lo]) <= cut; lo++);
        for (acc = 0; hi > 0 && (acc += hist[hi]) <= cut; hi--);
        cells.push({ contrast: Math.max(0, hi - lo), mean: sum / n, row, end: c === 0 || c === cols - 1 });
      }
    }
    if (cells.length < 8) return { n: cells.length, low: 0, bright: 0 };
    const med = (arr) => { const a = arr.slice().sort((p, q) => p - q); return a[a.length >> 1]; };
    const mc = med(cells.map((c) => c.contrast)), mm = med(cells.map((c) => c.mean));
    let low = 0, bright = 0;
    for (const c of cells) if (!c.end && c.contrast < mc * WASH_K) { low++; if (c.mean > mm) bright++; }   // la primera y la última celda de cada fila no cuentan: el borde de la zona no es exacto
    return { n: cells.length, low, bright };
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
  async function takeStill(track, video, force) {
    // 24-nov-2026 (rapidez): si el video ya es HD (lado corto ≥ 1080 px) se usa su cuadro: es inmediato y basta para el recuadro guía. takePhoto() solo
    // cuando la cámara no da video HD (en Android reenfoca y decodifica un JPEG de 12 MP: 1-3 s de espera).
    if (!force && Math.min(video.videoWidth || 0, video.videoHeight || 0) >= HD_SHORT_SIDE) return frameOf(video);   // force: segundo intento con TODO el detalle del sensor
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

  /** Recorte automático de la cédula nueva: las 3 líneas en cualquier parte de la foto → { g, w, h, info, flip() } (gris, ya enderezado) o null. */
  function findMrz(R, shot) {
    if (!R || !R.mrzFind || !shot) return null;
    try {
      const k = Math.min(1, FIND_MAX / Math.max(shot.w, shot.h)), c = cropCanvas(shot.img, { x: 0, y: 0, w: shot.w, h: shot.h }, shot.w * k);
      const f = R.mrzFind(grayOf(c), c.width, c.height);
      if (f) return f;
      // Torcida (entre ~25° y ~65°): la misma búsqueda sobre la foto girada 45°. Entre las dos se cubre cualquier ángulo.
      const k2 = Math.min(1, FIND_MAX / 1.42 / Math.max(shot.w, shot.h)), W = shot.w * k2, H = shot.h * k2, D = Math.ceil(Math.hypot(W, H)), t = canvasOf(D, D), x = t.getContext('2d', { willReadFrequently: true });
      x.fillStyle = '#808080'; x.fillRect(0, 0, D, D); x.imageSmoothingQuality = 'high'; x.translate(D / 2, D / 2); x.rotate(Math.PI / 4); x.drawImage(shot.img, -W / 2, -H / 2, W, H);
      return R.mrzFind(grayOf(t), D, D);
    } catch (e) { return null; }
  }
  /** Chequeo previo de la cédula nueva sobre el recorte ya ubicado → { low, bright, small }. */
  function checkFound(f) {
    const I = f.info, ws = washedCells(f.g, f.w, f.h, I.bands.map((b) => ({ x0: I.x0, x1: I.x1, y0: b.y0, y1: b.y1 })), 30);
    return { ...ws, small: Math.min(...I.bands.map((b) => b.y1 - b.y0 + 1)) < SMALL_LETTER_PX };
  }
  const washReason = (ws) => (ws.bright * 2 >= ws.low ? 'glare' : 'covered');
  /** Chequeo previo de la cédula vieja: el código ya ubicado (candidato del lector), enderezado, partido en 3 filas × 16 celdas. */
  function checkCode(sc, shot, cand) {
    try {
      const im = sc._cropCandidate(shot.img, cand, false, 0.5), w = im.width, h = im.height, d = im.data, g = new Uint8Array(w * h);
      for (let i = 0, j = 0; j < g.length; i += 4, j++) g[j] = (d[i] * 77 + d[i + 1] * 150 + d[i + 2] * 29) >> 8;
      const rows = [0, 1, 2].map((r) => ({ x0: w * 0.13, x1: w * 0.87, y0: h * (0.12 + r * 0.26), y1: h * (0.12 + (r + 1) * 0.26) - 1 }));
      return washedCells(g, w, h, rows, 16);
    } catch (e) { return { n: 0, low: 0, bright: 0 }; }
  }
  /** El recorte (gris) como lienzo con borde blanco: es lo que se le manda al servidor cuando el navegador ya ubicó las 3 líneas. */
  function foundCanvas(f, pad) {
    const c = canvasOf(f.w + 2 * pad, f.h + 2 * pad), x = c.getContext('2d'), im = x.createImageData(f.w, f.h), d = im.data;
    for (let i = 0, j = 0; j < f.g.length; i += 4, j++) { d[i] = d[i + 1] = d[i + 2] = f.g[j]; d[i + 3] = 255; }
    x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.putImageData(im, pad, pad);
    return c;
  }

  /** Cédula vieja sobre la RÁFAGA: el recuadro de cada cuadro (lo que un brillo o el pulso arruinan en uno suele verse en otro) y al final la foto completa. */
  async function decodeOld(R, shots, guidePhoto, alive) {
    const sc = await decoder(R, 'old');
    let unknown = false, located = false, small = false;
    sc.onResult = () => {}; sc.onStatus = () => {}; sc.onUnknown = () => { unknown = true; };
    const cands = () => (sc.lastDebug && sc.lastDebug.cands) || [];
    // plan 'photo': derecho y AL REVÉS alternados desde el primer intento (antes los giros de 180° llegaban al final y el tiempo no alcanzaba).
    if (guidePhoto) {                                                                                                  // 1) el recuadro con margen: lo más rápido cuando quedó encuadrada
      const datos = await sc.scanImage(cropCanvas(shots[0].img, expandRect(guidePhoto, 0.06, 0.9, shots[0].w, shots[0].h)), { budgetMs: OLD_BUDGET_MS[0], plan: 'photo' });
      if (datos) return { datos };
      located = cands().length > 0;
    }
    for (let k = 0; k < Math.min(3, shots.length); k++) {                                                              // 2) la foto COMPLETA de cada cuadro: el código donde esté, enderezado y recortado
      if (!alive()) return { datos: null };
      const datos = await sc.scanImage(shots[k].img, { budgetMs: OLD_BUDGET_MS[k + 1], plan: 'photo', cropsOnly: true });
      if (datos) return { datos };
      if (k > 0) continue;
      const c = cands()[0];                                                                                            // chequeo tras el primer cuadro: ¿vale la pena seguir?
      if (!c && !located) return { datos: null, unknown, reason: 'nocode' };                                           // no hay código a la vista: se avisa ya
      if (c) {
        located = true; small = !!(sc.lastDebug.ppm && sc.lastDebug.ppm < SMALL_PPM);
        const ws = checkCode(sc, shots[0], c);
        if (ws.low >= 4) return { datos: null, unknown, located, reason: washReason(ws) };                             // brillo o algo tapa el código: otro cuadro igual no lo arregla
      }
    }
    return { datos: null, unknown, located, small, reason: small ? 'small' : '' };
  }

  /** Cédula nueva sobre la ráfaga. `reads` se comparte con quien llama: si nada queda validado, de ahí sale lo que SÍ se leyó (partialFrom). La votación
   *  (pickMrz) junta las lecturas de los tres cuadros: dos lecturas iguales de cuadros distintos valen como confirmación de los nombres. */
  async function decodeNew(R, shots, guidePhoto, alive, reads = [], finds = []) {
    const mz = await decoder(R, 'new');
    mz.onStatus = () => {};
    // 24-nov (recorte automático): primero las 3 líneas DONDE ESTÉN en la foto (R.mrzFind las ubica, las endereza y entrega solo esa zona con la posición
    // exacta de cada línea); después, como siempre, el recuadro guía. Así el recuadro es una ayuda, no un requisito.
    let upside = false;
    const readFound = async (k) => {
      if (finds[k] === undefined) finds[k] = findMrz(R, shots[k]);
      const f = finds[k]; if (!f || !alive()) return null;
      let back = null;
      await readMrzCrop(async (flip, attempt) => {
        if (flip && attempt > 1) return {};                                           // la otra orientación: 2 intentos bastan
        const useBack = flip !== upside, v = useBack ? (back || (back = f.flip())) : f;
        const r = await mz._read(v.g, v.w, v.h, { info: v.info, attempt });
        if (useBack && !upside && r && r.texts && R.parseMrz(r.texts.map((t) => t.text))) upside = true;   // la cédula está al revés: los cuadros siguientes empiezan por ahí
        return r;
      }, R.parseMrz, R.mrzStrong, reads, alive);
      return pickMrz(reads, R.mrzStrong, false);
    };
    const readGuide = async (shot, r) => {
      if (!alive()) return null;
      const c = cropCanvas(shot.img, r, MRZ_CROP_W), g = grayOf(c);
      await readMrzCrop((flip, attempt) => mz._read(g, c.width, c.height, { flip, attempt }), R.parseMrz, R.mrzStrong, reads, alive);
      return pickMrz(reads, R.mrzStrong, false);
    };
    // CHEQUEO PREVIO sobre el primer cuadro: sin las 3 líneas a la vista, o con varias letras lavadas por un brillo, se avisa de una vez (no se queda pensando).
    if (finds[0] === undefined) finds[0] = findMrz(R, shots[0]);
    const f0 = finds[0], ws = f0 ? checkFound(f0) : null;
    if (f0) { reads.located = true; reads.small = ws.small; }
    if (ws && ws.low >= 3) { reads.reason = washReason(ws); return null; }
    if (f0) { const got = await readFound(0); if (got) return got.datos; }
    if (guidePhoto && alive()) {                                                        // el recuadro, como siempre (respaldo del recorte automático)
      let got = await readGuide(shots[0], expandRect(guidePhoto, 0.03, 0.08, shots[0].w, shots[0].h)); if (got) return got.datos;
      got = await readGuide(shots[0], expandRect(guidePhoto, 0.08, 0.45, shots[0].w, shots[0].h)); if (got) return got.datos;
    }
    if (!f0) {                                                                          // no se ubicaron: el localizador anterior, por si acaso (si tampoco las ve, responde enseguida)
      let full = null; mz.onResult = (d) => { full = d; };
      try { if (alive()) await mz.scanImage(shots[0].img); } finally { mz.onResult = () => {}; }
      if (full) reads.push({ parsed: full, conf: null });
      const g0 = pickMrz(reads, R.mrzStrong, true); if (!g0) reads.reason = 'nolines';
      return g0 ? g0.datos : null;
    }
    if (ws.low >= 1) { reads.reason = washReason(ws); const g0 = pickMrz(reads, R.mrzStrong, true); return g0 ? g0.datos : null; }   // una o dos letras lavadas y no se leyó: es el brillo
    for (let k = 1; k < shots.length; k++) {                                            // los otros cuadros de la ráfaga
      if (!alive()) return null;
      const got = await readFound(k); if (got) return got.datos;
    }
    if (ws.small) reads.reason = 'small';
    if (!alive()) return null;
    const g2 = pickMrz(reads, R.mrzStrong, true);
    return g2 ? g2.datos : null;
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
    const shot = shots[0], finds = [], deadline = performance.now() + NEW_DEADLINE_MS;
    if (R) finds[0] = findMrz(R, shot);                                             // se busca UNA vez: lo usan el chequeo previo, el navegador y el servidor
    const useServer = serverUsable(eventId) && (!R || !!finds[0]);                  // sin las 3 líneas ubicadas no se manda nada: el servidor tardaba mucho en decir que no
    let won = false, kick = null;
    const still = () => alive() && !won && performance.now() < deadline;
    if (!useServer) return R ? decodeNew(R, shots, guidePhoto, still, reads, finds) : null;
    if (finds[0] && checkFound(finds[0]).low >= 3) return decodeNew(R, shots, guidePhoto, still, reads, finds);   // brillo fuerte: decodeNew lo anota y devuelve null al instante
    const startServer = new Promise((ok) => { kick = ok; setTimeout(ok, SERVER_HEAD_START_MS); });
    const local = R ? decodeNew(R, shots, guidePhoto, still, reads, finds).catch(() => null).then((d) => { if (!d) kick(); return d; }) : (kick(), null);
    const server = startServer.then(() => (still() ? Promise.race([serverMrz(shot, eventId, still, finds[0], Math.max(500, deadline - performance.now())), new Promise((ok) => setTimeout(() => ok(null), Math.max(0, deadline - performance.now())))]) : null));
    const d = await firstFound([local, server]);
    won = true;
    return d;
  }
  async function serverMrz(shot, eventId, alive, found, timeoutMs) {
    if (!serverUsable(eventId) || !alive()) return null;
    const k = Math.min(1, SERVER_MAX / Math.max(shot.w, shot.h));
    const c = found ? foundCanvas(found, SERVER_CROP_PAD) : cropCanvas(shot.img, { x: 0, y: 0, w: shot.w, h: shot.h }, shot.w * k);   // con las 3 líneas ya ubicadas va SOLO ese recorte (más liviano y sin el resto de la cédula)
    let blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.92));
    if (!blob || !alive()) return null;
    const fd = new FormData(); fd.append('file', blob, 'reverso.jpg'); blob = null;
    const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null, t = ctl ? setTimeout(() => ctl.abort(), Math.min(SERVER_TIMEOUT_MS, timeoutMs || SERVER_TIMEOUT_MS)) : 0;
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
      // El lienzo de la guía mide lo que mide EN PANTALLA (no la resolución del video: un lienzo 4K encima del video era parte del atasco). El recuadro es el mismo:
      // guideRect sobre la parte visible del video equivale a guideRect sobre la caja en pantalla.
      const r = video.getBoundingClientRect(), dpr = Math.min(OVERLAY_DPR_MAX, window.devicePixelRatio || 1), vw = Math.max(1, Math.round(r.width * dpr)), vh = Math.max(1, Math.round(r.height * dpr));
      const g = guideRect(vw, vh, vw, vh, G.ar, G.fill), x = overlay.getContext('2d');
      if (overlay.width !== vw || overlay.height !== vh) { overlay.width = vw; overlay.height = vh; }
      const line = busy ? tok(overlay, '--gw-gold-2', '#e8c25a') : glare ? tok(overlay, '--gw-warn-line', '#c98a00') : tok(overlay, '--gw-ok-line', '#1f8a4c');
      x.clearRect(0, 0, vw, vh);
      x.fillStyle = tok(overlay, '--gw-overlay', 'rgba(0,0,0,.45)');                   // oscurece lo que queda fuera del recuadro
      x.beginPath(); x.rect(0, 0, vw, vh); x.rect(g.x, g.y, g.w, g.h); x.fill('evenodd');
      const lw = Math.max(1.5 * dpr, vw / 260), c = Math.min(g.h * 0.35, g.w * 0.06);
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
    let probing = false;
    async function checkGlare() {
      if (dead || busy || frozen || probing || !video.videoWidth || document.hidden) return;
      const vw = video.videoWidth, vh = video.videoHeight, r = video.getBoundingClientRect(), g = guideRect(vw, vh, r.width, r.height, G.ar, G.fill);
      probe.height = Math.max(8, Math.round(probe.width / G.ar));
      const x = probe.getContext('2d', { willReadFrequently: true });
      probing = true;
      try {
        // Recorte y reducción en la tarjeta gráfica (createImageBitmap): así no se trae a memoria el cuadro completo del video cada medio segundo.
        let bmp = null;
        if (typeof createImageBitmap === 'function') { try { bmp = await createImageBitmap(video, Math.round(g.x), Math.round(g.y), Math.round(g.w), Math.round(g.h), { resizeWidth: probe.width, resizeHeight: probe.height, resizeQuality: 'low' }); } catch (e) { bmp = null; } }
        if (dead || busy || frozen) { if (bmp && bmp.close) bmp.close(); return; }
        if (bmp) { x.drawImage(bmp, 0, 0); if (bmp.close) bmp.close(); } else x.drawImage(video, g.x, g.y, g.w, g.h, 0, 0, probe.width, probe.height);
      } catch (e) { return; } finally { probing = false; }
      const now = glareRatio(x.getImageData(0, 0, probe.width, probe.height).data) > GLARE_RATIO;
      if (now !== glare) { glare = now; redraw(); if (!busy) say(glare ? (torchOn ? MSG.glareTorch : MSG.glare) : aimMsg(), glare ? 'warn' : ''); }
    }

    /* Fluidez: se cuentan los cuadros que la vista previa pinta de verdad; si son pocos, se baja la resolución del video (sin volver a pedir permiso). */
    function measureFps() {
      return new Promise((done) => {
        if (typeof video.requestVideoFrameCallback !== 'function') { done(0); return; }
        let n = 0, t0 = 0;
        const tick = (now) => { if (dead) { done(0); return; } if (!t0) t0 = now; else n++; if (now - t0 >= FPS_WINDOW_MS) done(n * 1000 / (now - t0)); else video.requestVideoFrameCallback(tick); };
        setTimeout(() => { if (dead) done(0); else video.requestVideoFrameCallback(tick); }, FPS_WARMUP_MS);
        setTimeout(() => done(t0 ? n * 1000 / FPS_WINDOW_MS : 0), FPS_WARMUP_MS + FPS_WINDOW_MS * 3);       // pestaña en segundo plano: no se queda esperando
      });
    }
    async function tunePreview() {
      for (let round = 0; round < 2 && !dead && track; round++) {
        const fps = await measureFps(); if (dead || busy || !track) return;
        const to = stepDown(fps, Math.min(video.videoWidth || 0, video.videoHeight || 0), typeof ImageCapture !== 'undefined'); if (!to) return;
        // Se conserva la FORMA del video (un celular en vertical entrega 1080×1920): se prueba ancho×alto y, si la imagen queda recortada, alto×ancho; si ninguna sirve, se deja como estaba.
        const shape = () => Math.max(video.videoWidth, video.videoHeight) / Math.max(1, Math.min(video.videoWidth, video.videoHeight)), was = shape(), w0 = video.videoWidth, h0 = video.videoHeight;
        let ok = false; const tall = h0 > w0;
        for (const [w, h] of (tall ? [[to.height, to.width], [to.width, to.height]] : [[to.width, to.height], [to.height, to.width]])) {
          try { await track.applyConstraints({ width: { ideal: w }, height: { ideal: h } }); } catch (e) { continue; }
          await new Promise((r) => setTimeout(r, 450));
          if (dead) return;
          if (Math.abs(shape() - was) < was * 0.06 && (video.videoHeight > video.videoWidth) === tall) { ok = true; break; }
        }
        if (!ok) { try { await track.applyConstraints({ width: { ideal: w0 }, height: { ideal: h0 } }); } catch (e) { /* queda como la dejó el navegador */ } redraw(); return; }
        redraw();
      }
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
      for (const size of (lowEnd(navigator) ? SIZES.slice(2) : SIZES)) {                 // equipo modesto: 1080p de entrada
        try { s = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: 'environment' }, ...size } }); break; }
        catch (e) { last = e; if (e.name === 'NotAllowedError' || e.name === 'SecurityError' || e.name === 'NotFoundError') break; }
      }
      if (dead) { if (s) s.getTracks().forEach((t) => t.stop()); return; }
      if (!s) { say(last && last.name === 'NotFoundError' ? MSG.camNone : MSG.camPerm, 'err'); return; }
      stream = s; track = s.getVideoTracks()[0];
      try { await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) { /* sin control de enfoque */ }
      video.srcObject = s; video.setAttribute('playsinline', ''); video.muted = true;
      video.addEventListener('loadedmetadata', redraw); video.addEventListener('resize', redraw);                    // 'resize': cambió la resolución del video (tunePreview)
      try { await video.play(); } catch (e) { /* iOS: arranca con el primer toque */ }
      if (dead) return;
      if (btn) btn.disabled = busy;
      redraw(); setTimeout(redraw, 300);
      setupTorch();
      glareTimer = setInterval(checkGlare, 500);
      if (!busy) say(aimMsg());
      await tunePreview();                                                              // mide la fluidez y, si hace falta, baja la resolución
      preload();                                                                        // los lectores se cargan DESPUÉS: su arranque (OCR, zxing) no compite con la cámara al abrir
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
        let datos = null, unknown = false, readerErr = null, retake = false, reason = '';
        if (!R) { try { R = await o.readers(); } catch (e) { readerErr = e; } }
        const run = async (list, gp) => {
          reads.reason = ''; reads.located = false; reads.small = false;
          if (kind === 'old') { const out = await decodeOld(R, list, gp, alive); unknown = unknown || !!out.unknown; reason = out.reason || ''; retake = !!out.located && !!out.small; return out.datos; }
          const d = await decodeNewRace(R, list, gp, alive, o.eventId, reads); reason = reads.reason || ''; retake = !!reads.located && !!reads.small && reason !== 'glare' && reason !== 'covered'; return d;
        };
        if (R && !dead) { try { datos = await run(shots, guidePhoto); } catch (e) { readerErr = e; try { console.warn('[cedula-foto] fallo interno del lector:', e && e.message); } catch (_) { /* sin consola */ } } }
        if (!datos && kind === 'new' && !R && !dead) datos = await decodeNewRace(null, shots, guidePhoto, alive, o.eventId, reads);   // el lector del navegador no cargó: solo el servidor
        // La cédula SÍ se vio, sin brillo, pero quedó lejos (letras o código muy pequeños en el cuadro del video) → una foto fija con toda la resolución del sensor y se repite.
        if (!datos && R && !dead && retake && shot.source === 'frame' && track && typeof ImageCapture !== 'undefined') {
          say(MSG.detail, 'warn');
          try {
            const hd = await takeStill(track, video, true);
            if (hd.source === 'still' && !dead && Math.max(hd.w, hd.h) > Math.max(shot.w, shot.h) * 1.2) { shots.push(hd); datos = await run([hd], photoRect(g, vw, vh, hd.w, hd.h)); }
            else if (hd.img && hd.img.close) hd.img.close();
          } catch (e) { /* sin foto fija: queda el resultado del primer intento */ }
        }
        if (dead) return;
        if (datos) { say('Cédula leída.', 'ok'); setBusy(false); o.onResult(datos, kind); resumePreview(); return; }
        if (kind === 'new' && await offerNear(partialFrom(reads))) { say(MSG.partial, 'warn'); return; }
        const why = { glare: MSG.failGlare, covered: MSG.covered, nolines: MSG.noLines, nocode: MSG.noCode, small: MSG.small }[reason];
        say(readerErr && !R ? MSG.noReader : unknown ? MSG.unknown : why || ((hadGlare || glare) ? MSG.failGlare : MSG.fail), 'err');
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
    openCamera().catch(() => {});
    // Los lectores se cargan mientras el operador encuadra (la primera vez la cédula nueva baja el OCR: unos segundos). Si se toma la foto antes, shoot() los espera.
    let preloaded = false;
    function preload() { if (preloaded || dead) return; preloaded = true; Promise.resolve().then(() => o.readers()).then((r) => { R = r; return decoder(r, kind); }).catch(() => { /* se reintenta al tomar la foto */ }); }
    setTimeout(preload, 4000);                                                          // por si la cámara no abre o tarda: no se queda sin precargar

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

  const api = { attach, firstFound, lowEnd, stepDown, washedCells, findMrz, checkFound, glareRatio, partialFrom, guideRect, expandRect, photoRect, stillOptions, pickMrz, readMrzCrop, fromServer, MSG, GUIDE };
  if (typeof window !== 'undefined') window.CedulaFoto = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
