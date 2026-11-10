/* QR como método de registro (Sprint 4): NO es un módulo aparte, es otra forma de entregar la cédula en el
   Registro, el Control de Áreas y el Control de Inventario. Dos piezas compartidas:

   QrCode.parse(texto)  -> { cedula, nombres, apellidos, isQr } (o null si el texto está vacío)
     Contenido de los QR propios (escarapela impresa / digital): las variables del elemento `qr` unidas por `|`
     (ver renderQr en badge-render.js). Por defecto solo la cédula ("1016100329"); también puede venir
     "cédula|nombre|apellido". La cédula es el primer trozo numérico (4+ dígitos, con o sin puntos); si ninguno lo
     es, el primero. El resto se toma como nombre para la búsqueda por nombre (igual que con la cédula vieja).
     `isQr` = true solo cuando trae `|` (un ID suelto no se distingue de una cédula escrita a mano).

   QrScanner.open({ title, onCode(texto, formato), cooldownMs, formats, onPhoto })
     `formats` (por defecto solo QR; el Registro pide también 'pdf417'). `onPhoto(blob)`: si se pasa, la ventana ofrece «Foto del reverso (cédula nueva)», que toma un cuadro de la MISMA cámara
     (no se adjunta ningún archivo) y lo entrega para leer la MRZ en el servidor.
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

  function open(opts) {
    opts = opts || {};
    const onCode = opts.onCode || function () {};
    const cooldown = opts.cooldownMs || 3000;

    const overlay = document.createElement('div');
    overlay.className = 'gw-modal-backdrop gw-modal-backdrop--top'; overlay.setAttribute('data-open', 'true');
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', opts.title || 'Escanear código QR');
    const box = document.createElement('div');
    box.className = 'gw-modal gw-modal--dialog gw-cam';
    box.innerHTML = `
      <div class="gw-modal__head"><h2 class="gw-modal__title"></h2></div>
      <div class="gw-modal__body">
        <video class="gw-cam__video" autoplay playsinline muted aria-label="Vista de la cámara"></video>
        <canvas hidden></canvas>
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
    let stream = null, stopped = false, last = { text: '', at: 0 };

    function close() {
      stopped = true;
      if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
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
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      } catch (e) {
        status.classList.add('gw-cam__status--err');
        status.textContent = 'No se pudo acceder a la cámara — revisa los permisos del navegador (la cámara solo funciona en una página segura, https).';
        return;
      }
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
      if (!detector && !jsQR) { status.classList.add('gw-cam__status--err'); status.textContent = 'No se pudo cargar el lector de QR (sin internet). Usa el lector de mano o escribe la cédula.'; return; }
      const ctx = canvas.getContext('2d', { willReadFrequently: true });

      async function tick() {
        if (stopped) return;
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
    start();
    return { close };
  }

  if (typeof window !== 'undefined') { window.QrCode = { parse, classify, isDynamic, resolveDynamic, unwrap, collect }; window.QrScanner = { open, loadJsQr, JSQR_URL }; }
  if (typeof module !== 'undefined') module.exports = { parse, classify, isDynamic, resolveDynamic, unwrap, collect };  // para las pruebas en Node
})();
