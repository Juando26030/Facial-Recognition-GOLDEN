/* QR como método de registro (Sprint 4): NO es un módulo aparte, es otra forma de entregar la cédula en el
   Registro, el Control de Áreas y el Control de Inventario. Dos piezas compartidas:

   QrCode.parse(texto)  -> { cedula, nombres, apellidos, isQr } (o null si el texto está vacío)
     Contenido de los QR propios (escarapela impresa / digital): las variables del elemento `qr` unidas por `|`
     (ver renderQr en badge-render.js). Por defecto solo la cédula ("1016100329"); también puede venir
     "cédula|nombre|apellido". La cédula es el primer trozo numérico (4+ dígitos, con o sin puntos); si ninguno lo
     es, el primero. El resto se toma como nombre para la búsqueda por nombre (igual que con la cédula vieja).
     `isQr` = true solo cuando trae `|` (un ID suelto no se distingue de una cédula escrita a mano).

   QrScanner.open({ title, onCode(texto, formato), cooldownMs, formats, onPhoto, modes, onCedula })
     `formats` (por defecto solo QR; el Registro pide también 'pdf417'). `onPhoto(blob)`: si se pasa, la ventana ofrece «Foto del reverso (cédula nueva)», que toma un cuadro de la MISMA cámara
     (no se adjunta ningún archivo) y lo entrega para leer la MRZ en el servidor.
     `modes` (opcional, p. ej. ['old','new','qr']): la ventana muestra un selector «Cédula vieja · Cédula nueva · QR» y se prepara para lo que se elija (el Registro lo usa). 'qr' = el comportamiento de siempre (onCode);
     'old' = código de barras PDF417 de la cédula vieja y 'new' = las 3 líneas de la cédula nueva: ambos con los lectores de static/js/cedula-readers.js (se cargan al elegirlos) y entregan `onCedula(datos, 'old'|'new')`
     con { cedula, nombre1, nombre2, apellido1, apellido2, nacimiento, … }. Sin `modes` todo funciona exactamente como antes.
     Abre la cámara del dispositivo (celular, tablet o computador) y lee QR en vivo. Usa BarcodeDetector si el
     navegador lo tiene (Chrome/Edge/Android) y, si no, jsQR (copia propia en /static/vendor/jsqr, se carga bajo demanda). Se queda abierto para
     escanear varias personas seguidas; ignora el mismo código durante `cooldownMs` (3 s por defecto). */
(function () {
  const NUMERIC_ID = /^\d[\d.\s-]{2,}\d$/;

  /* Fase 10 (C): el QR de la escarapela / credencial digital / Wallet ahora es una vCard (static/js/vcard.js) con el código de siempre en NOTE; se acepta ese formato y el anterior.
     unwrap() saca el código de la vCard de Golden y deja IGUAL cualquier otro texto. */
  function vc() { return (typeof module !== 'undefined' && typeof require === 'function') ? require('./vcard.js') : (typeof window !== 'undefined' ? window.GWVcard : null); }
  function unwrap(raw) { const v = vc(); return v ? v.unwrap(raw) : String(raw == null ? '' : raw); }

  /* Lector de mano (teclado): una vCard llega como VARIAS líneas, cada una con su Enter. collect(línea) devuelve null mientras la vCard no termina (quien llama no hace nada) y, al completarse,
     el texto completo; cualquier otra lectura se devuelve tal cual. */
  let vcBuf = null, vcAt = 0;
  function collect(line) {
    const t = String(line == null ? '' : line).trim();
    const now = Date.now();
    if (vcBuf !== null && now - vcAt > 5000) vcBuf = null;           // quedó a medias: se descarta
    if (vcBuf === null) { if (!/^BEGIN:VCARD$/i.test(t)) return t; vcBuf = []; }
    vcAt = now;
    if (t) vcBuf.push(t);
    if (/^END:VCARD$/i.test(t)) { const full = vcBuf.join('\n'); vcBuf = null; return full; }
    return null;
  }

  function parse(raw) {
    const text = unwrap(raw).trim();
    if (!text) return null;
    if (!text.includes('|')) return { cedula: text, nombres: '', apellidos: '', isQr: false };
    const parts = text.split('|').map((p) => p.trim()).filter(Boolean);
    if (!parts.length) return null;
    let idx = parts.findIndex((p) => NUMERIC_ID.test(p) && p.replace(/\D/g, '').length >= 4);
    if (idx < 0) idx = 0;
    const cedula = parts[idx].replace(/[.\s]/g, '');
    const names = parts.filter((_, i) => i !== idx);
    const nombres = names.length > 1 ? names[0] : names.join(' ');
    const apellidos = names.length > 1 ? names.slice(1).join(' ') : '';
    return { cedula, nombres, apellidos, isQr: true };
  }

  /* Un solo «Escanear»: la cámara lee QR y, si el navegador lo permite (BarcodeDetector), también el PDF417 de la cédula colombiana. classify() decide qué se leyó:
       { kind: 'qr', cedula, nombres, apellidos }      QR propio (escarapela): trae `|`.
       { kind: 'cedula', cedula, nombres, apellidos }  PDF417 de la cédula (CSV del lector viejo «cédula,nombres,apellidos») o un número suelto de cédula.
       null                                            nada utilizable.
     `format` es el que informa el detector ('qr_code' | 'pdf417'); jsQR (sin detector) solo lee QR. */
  function classify(raw, format, parseOld) {
    const text = unwrap(raw).trim();
    if (!text) return null;
    const q = parse(text);
    if (q && q.isQr) return { kind: 'qr', cedula: q.cedula, nombres: q.nombres, apellidos: q.apellidos };
    const old = parseOld ? parseOld(text) : null;
    if (old) return { kind: 'cedula', cedula: old.cedula, nombres: old.nombres, apellidos: old.apellidos };
    const plain = text.replace(/[.\s]/g, '');
    if (/^\d{4,12}$/.test(plain)) return { kind: format === 'pdf417' ? 'cedula' : 'qr', cedula: plain, nombres: '', apellidos: '' };
    if (format === 'pdf417') {                                   // PDF417 con bytes de más: el primer número de 6 a 10 dígitos es la cédula
      const m = text.match(/(?:^|\D)(\d{6,10})(?!\d)/);
      if (m) return { kind: 'cedula', cedula: m[1], nombres: '', apellidos: '' };
    }
    return format === 'pdf417' ? null : { kind: 'qr', cedula: q ? q.cedula : plain, nombres: '', apellidos: '' };
  }

  /* QR DINÁMICO de la credencial digital (Fase 8, app/dynamic_qr.py): «gwq1.<id>.<ventana>.<firma>» (cambia cada 30 s) o «gwq1s.<id>.<firma>» (el del pase de Wallet). No trae la cédula: el SERVIDOR valida firma y vigencia
     y devuelve la persona. `resolveDynamic(texto, eventId)` devuelve el mismo texto si NO es dinámico y, si lo es, «cédula|nombres|apellidos» (el formato del QR de la escarapela, así el resto del flujo no cambia).
     Rechaza con Error(mensaje en español) si el código es inválido, vencido o de otro evento. */
  const DYNAMIC_RE = /^gwq1s?\.\d{1,12}(?:\.\d{1,12})?\.[0-9a-f]{20}$/i;
  function isDynamic(raw) { return DYNAMIC_RE.test(unwrap(raw).trim()); }
  async function resolveDynamic(raw, eventId, purpose) {          // purpose: 'entry' (por defecto) | 'area' | 'inventory' — el código estático del pase de Wallet solo vale en la entrada
    const text = unwrap(raw).trim();
    if (!isDynamic(text)) return unwrap(raw);
    const res = await fetch('/api/qr/resolve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, event_id: eventId == null ? window.EVENT_ID : eventId, purpose: purpose || 'entry' }) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo validar el código');
    return [data.cedula, data.first_name, data.last_name].map((x) => String(x == null ? '' : x).replace(/\|/g, ' ').trim()).join('|');
  }

  // Copia PROPIA de jsQR (static/vendor/jsqr, Apache-2.0): sin CDN, así el escáner de QR por cámara también funciona sin red (el service worker del quiosco la guarda en la primera visita).
  const JSQR_URL = '/static/vendor/jsqr/jsQR.js?v=1.4.0';
  let jsQrPromise = null;
  function loadJsQr() {
    if (window.jsQR) return Promise.resolve(window.jsQR);
    if (!jsQrPromise) {
      jsQrPromise = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = JSQR_URL;
        s.onload = () => resolve(window.jsQR);
        s.onerror = () => reject(new Error('No se pudo cargar el lector de QR'));
        document.head.appendChild(s);
      });
    }
    return jsQrPromise;
  }

  // Lectores de cédula (vieja: PDF417 · nueva: las 3 líneas): archivo generado desde la página de prueba (scripts/build_cedula_readers.py); se carga solo si el operador elige uno de esos modos.
  const READERS_URL = '/static/js/cedula-readers.js?v=1';
  const MODE_KEY = 'gw_scan_mode';
  let readersPromise = null;
  function loadReaders() {
    if (window.CedulaReaders) return Promise.resolve(window.CedulaReaders);
    if (window.CEDULA_VENDOR === undefined) window.CEDULA_VENDOR = '/static/vendor/cedula';        // copia propia de zxing/tesseract si se generó (scripts/vendor_cedula_readers.sh); si no, los lectores usan el CDN
    if (!readersPromise) {
      readersPromise = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = READERS_URL;
        s.onload = () => resolve(window.CedulaReaders);
        s.onerror = () => { readersPromise = null; reject(new Error('No se pudo cargar el lector de cédulas (sin conexión).')); };
        document.head.appendChild(s);
      });
    }
    return readersPromise;
  }

  function open(opts) {
    opts = opts || {};
    const onCode = opts.onCode || function () {};
    const cooldown = opts.cooldownMs || 3000;

    const overlay = document.createElement('div');
    overlay.className = 'gw-modal-backdrop gw-modal-backdrop--top'; overlay.setAttribute('data-open', 'true');
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', opts.title || 'Escanear código QR');
    const box = document.createElement('div');
    box.className = 'gw-modal gw-modal--dialog gw-cam';
    const MODE_LABEL = { old: 'Cédula vieja', new: 'Cédula nueva', qr: 'QR' };
    const modes = Array.isArray(opts.modes) ? opts.modes.filter((m) => MODE_LABEL[m]) : [];
    const modesHtml = modes.length ? `<div class="gw-segment gw-cam__modes" role="group" aria-label="¿Qué vas a escanear?">${modes.map((m) => `<button type="button" class="gw-segment__opt" data-mode="${m}" aria-pressed="false">${MODE_LABEL[m]}</button>`).join('')}</div><canvas hidden></canvas>` : '';
    const videoHtml = modes.length ? '<div class="gw-cam__stage"><video class="gw-cam__video" autoplay playsinline muted aria-label="Vista de la cámara"></video><canvas class="gw-cam__overlay" aria-hidden="true"></canvas></div>'
      : '<video class="gw-cam__video" autoplay playsinline muted aria-label="Vista de la cámara"></video><canvas hidden></canvas>';
    box.innerHTML = `
      <div class="gw-modal__head"><h2 class="gw-modal__title"></h2></div>
      <div class="gw-modal__body">
        ${modesHtml}
        ${videoHtml}
        <p class="gw-cam__status qr-status" role="status" aria-live="polite">Apunta la cámara al código QR.</p>
      </div>
      <div class="gw-modal__foot">
        <button type="button" class="gw-btn gw-btn--secondary qr-photo" hidden>Foto del reverso (cédula nueva)</button>
        <button type="button" class="gw-btn gw-btn--secondary qr-close">Cerrar</button>
      </div>`;
    box.querySelector('.gw-modal__title').textContent = opts.title || 'Escanear código QR';
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    if (opts.formats && opts.formats.includes('pdf417')) box.querySelector('.qr-status').textContent = 'Apunta la cámara al código QR o al código de barras del reverso de la cédula.';
    const video = box.querySelector('video');
    const canvas = box.querySelector('canvas');
    const status = box.querySelector('.qr-status');
    const overlayCv = box.querySelector('.gw-cam__overlay');
    let stream = null, stopped = false, last = { text: '', at: 0 }, loopId = 0, epoch = 0, reader = null, mode = null, lastCed = { id: '', at: 0 };
    const qrMsg = () => (opts.formats && opts.formats.includes('pdf417') ? 'Apunta la cámara al código QR o al código de barras del reverso de la cédula.' : 'Apunta la cámara al código QR.');
    status.textContent = qrMsg();

    function stopQr() { loopId++; if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; } }
    function stopReader() {
      if (reader) { try { reader.stop(); } catch (e) { /* ya detenido */ } reader = null; }
      if (overlayCv) overlayCv.getContext('2d').clearRect(0, 0, overlayCv.width, overlayCv.height);
    }
    function close() {
      stopped = true; epoch++;
      stopQr(); stopReader();
      overlay.remove();
    }
    box.querySelector('.qr-close').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    function emit(text, format) {
      const now = Date.now();
      if (text === last.text && now - last.at < cooldown) return;
      last = { text, at: now };
      status.textContent = 'Código leído.';                      // sin eco del contenido: puede traer una cédula
      onCode(unwrap(text), format);                              // una vCard de Golden entrega el código de adentro; todo lo demás, igual
    }
    const photoBtn = box.querySelector('.qr-photo');
    if (opts.onPhoto) {
      photoBtn.hidden = false;
      photoBtn.addEventListener('click', () => {
        if (!video.videoWidth) { status.textContent = 'Espera a que la cámara muestre la imagen.'; return; }
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => { if (blob) { close(); opts.onPhoto(blob); } }, 'image/jpeg', 0.92);
      });
    }

    async function start() {
      const id = ++loopId;
      let s;
      try {
        s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      } catch (e) {
        status.classList.add('gw-cam__status--err');
        status.textContent = 'No se pudo acceder a la cámara — revisa los permisos del navegador (la cámara solo funciona en una página segura, https).';
        return;
      }
      if (stopped || id !== loopId) { s.getTracks().forEach((t) => t.stop()); return; }       // se cerró o se cambió de modo mientras se pedía el permiso
      stream = s;
      video.srcObject = stream;
      let detector = null;
      if ('BarcodeDetector' in window) {
        try {
          let formats = opts.formats || ['qr_code'];
          if (BarcodeDetector.getSupportedFormats) { const ok = await BarcodeDetector.getSupportedFormats(); formats = formats.filter((f) => ok.includes(f)); }
          detector = formats.length ? new BarcodeDetector({ formats }) : null;
        } catch (e) { detector = null; }
      }
      const jsQR = detector ? null : await loadJsQr().catch(() => null);
      if (stopped || id !== loopId) return;
      if (!detector && !jsQR) { status.classList.add('gw-cam__status--err'); status.textContent = 'No se pudo cargar el lector de QR (sin internet). Usa el lector de mano o escribe la cédula.'; return; }
      const ctx = canvas.getContext('2d', { willReadFrequently: true });

      async function tick() {
        if (stopped || id !== loopId) return;
        if (video.videoWidth) {
          try {
            if (detector) {
              const codes = await detector.detect(video);
              if (codes.length) emit(codes[0].rawValue, codes[0].format);
            } else {
              canvas.width = video.videoWidth; canvas.height = video.videoHeight;
              ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
              const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
              const code = jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
              if (code && code.data) emit(code.data, 'qr_code');
            }
          } catch (e) { /* un cuadro que no se pudo leer: sigue con el siguiente */ }
        }
        setTimeout(tick, 200);
      }
      tick();
    }

    /* ---- Cédula vieja / nueva (solo con `modes`): lectores de static/js/cedula-readers.js ---- */
    function failStatus(msg) { status.classList.add('gw-cam__status--err'); status.textContent = msg; }
    function onCedulaRead(d, kind, my) {
      if (stopped || my !== epoch) return;
      status.classList.remove('gw-cam__status--err');
      if (!(d.cedula === lastCed.id && Date.now() - lastCed.at < Math.max(cooldown, 4000))) {      // la misma cédula quieta frente a la cámara no se envía dos veces
        lastCed = { id: d.cedula, at: Date.now() };
        status.textContent = 'Cédula leída.';
        try { if (opts.onCedula) opts.onCedula(d, kind); } catch (e) { console.error(e); }
      }
      setTimeout(() => { if (!stopped && my === epoch && reader) reader.resume(); }, 2500);          // sigue con la siguiente persona
    }
    async function startCedula(kind, my) {
      status.classList.remove('gw-cam__status--err'); status.textContent = 'Cargando el lector…';
      let R;
      try { R = await loadReaders(); } catch (e) { if (my === epoch) failStatus(e.message); return; }
      if (stopped || my !== epoch) return;
      const common = { onStatus: (m, k) => { if (!stopped && my === epoch) { status.textContent = m; status.classList.toggle('gw-cam__status--err', k === 'err'); } } };
      try {
        const rd = kind === 'old'
          ? new R.CedulaScanner({ ...common, onResult: (d) => onCedulaRead(d, 'old', my),
              onUnknown: () => { if (my !== epoch) return; status.textContent = 'Se leyó un código, pero no tiene el formato de la cédula.'; setTimeout(() => { if (!stopped && my === epoch && reader) reader.resume(); }, 1500); } })
          : new R.MrzScanner({ ...common, onlyVerified: true, onResult: (d) => onCedulaRead(d, 'new', my) });          // acreditar a alguien exige lectura verificada con los dígitos de control
        if (kind === 'old') await rd.init();
        if (stopped || my !== epoch) return;
        reader = rd;
        await rd.startCamera(video, overlayCv);
        if (stopped || my !== epoch) rd.stop();
      } catch (e) {
        if (my !== epoch) return;
        failStatus(e && (e.name === 'NotAllowedError' || e.name === 'SecurityError') ? 'No se pudo acceder a la cámara — revisa los permisos del navegador (la cámara solo funciona en una página segura, https).'
          : e && e.name === 'NotFoundError' ? 'No se encontró ninguna cámara.' : 'No se pudo iniciar el lector: ' + ((e && e.message) || 'error desconocido'));
      }
    }
    async function setMode(m) {
      const my = ++epoch;
      stopQr(); stopReader(); mode = m;
      box.querySelectorAll('.gw-cam__modes [data-mode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === m)));
      try { localStorage.setItem(MODE_KEY, m); } catch (e) { /* sin almacenamiento: no se recuerda */ }
      const isQr = m === 'qr';
      if (overlayCv) overlayCv.hidden = isQr;
      if (opts.onPhoto) photoBtn.hidden = !isQr;                     // «Foto del reverso» (servidor) solo con QR: las cédulas ya tienen su propio lector
      if (isQr) { status.classList.remove('gw-cam__status--err'); status.textContent = qrMsg(); await start(); } else await startCedula(m, my);
    }

    if (modes.length) {
      box.querySelectorAll('.gw-cam__modes [data-mode]').forEach((b) => b.addEventListener('click', () => { if (b.dataset.mode !== mode) setMode(b.dataset.mode); }));
      let saved = null; try { saved = localStorage.getItem(MODE_KEY); } catch (e) { /* ignorar */ }
      setMode(modes.includes(saved) ? saved : modes.includes(opts.defaultMode) ? opts.defaultMode : modes.includes('qr') ? 'qr' : modes[0]);
    } else start();
    return { close };
  }

  if (typeof window !== 'undefined') { window.QrCode = { parse, classify, isDynamic, resolveDynamic, unwrap, collect }; window.QrScanner = { open, loadJsQr, JSQR_URL, READERS_URL }; }
  if (typeof module !== 'undefined') module.exports = { parse, classify, isDynamic, resolveDynamic, unwrap, collect };  // para las pruebas en Node
})();
