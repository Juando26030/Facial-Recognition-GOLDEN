/* QR como método de registro (Sprint 4): NO es un módulo aparte, es otra forma de entregar la cédula en el
   Registro, el Control de Áreas y el Control de Inventario. Dos piezas compartidas:

   QrCode.parse(texto)  -> { cedula, nombres, apellidos, isQr } (o null si el texto está vacío)
     Contenido de los QR propios (escarapela impresa / digital): las variables del elemento `qr` unidas por `|`
     (ver renderQr en badge-render.js). Por defecto solo la cédula ("1016100329"); también puede venir
     "cédula|nombre|apellido". La cédula es el primer trozo numérico (4+ dígitos, con o sin puntos); si ninguno lo
     es, el primero. El resto se toma como nombre para la búsqueda por nombre (igual que con la cédula vieja).
     `isQr` = true solo cuando trae `|` (un ID suelto no se distingue de una cédula escrita a mano).

   QrScanner.open({ title, onCode, cooldownMs })
     Abre la cámara del dispositivo (celular, tablet o computador) y lee QR en vivo. Usa BarcodeDetector si el
     navegador lo tiene (Chrome/Edge/Android) y, si no, jsQR (se carga bajo demanda). Se queda abierto para
     escanear varias personas seguidas; ignora el mismo código durante `cooldownMs` (3 s por defecto). */
(function () {
  const NUMERIC_ID = /^\d[\d.\s-]{2,}\d$/;

  function parse(raw) {
    const text = String(raw == null ? '' : raw).trim();
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

  let jsQrPromise = null;
  function loadJsQr() {
    if (window.jsQR) return Promise.resolve(window.jsQR);
    if (!jsQrPromise) {
      jsQrPromise = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js';
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
    overlay.style.cssText = 'position:fixed; inset:0; background:rgba(10,14,46,0.6); z-index:9998; display:flex; align-items:center; justify-content:center; padding:1rem;';
    const box = document.createElement('div');
    box.style.cssText = 'background:white; border-radius:16px; padding:1.4rem; max-width:480px; width:100%; box-shadow:0 20px 60px rgba(0,0,0,0.4); text-align:center; font-family: var(--font-body, sans-serif);';
    box.innerHTML = `
      <h4 style="margin-top:0; color:var(--golden-dark);">${opts.title || 'Escanear código QR'}</h4>
      <video autoplay playsinline muted style="width:100%; border-radius:10px; background:#000;"></video>
      <canvas style="display:none;"></canvas>
      <p class="qr-status" style="font-size:0.85rem; color:#555; margin:0.6rem 0 0;">Apunta la cámara al código QR.</p>
      <div style="display:flex; justify-content:center; margin-top:1rem;">
        <button type="button" class="qr-close" style="border:1px solid #ccc; background:white; border-radius:20px; padding:8px 22px; cursor:pointer; font-weight:600;">Cerrar</button>
      </div>`;
    overlay.appendChild(box);
    document.body.appendChild(overlay);

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

    function emit(text) {
      const now = Date.now();
      if (text === last.text && now - last.at < cooldown) return;
      last = { text, at: now };
      status.textContent = 'Leído: ' + text.slice(0, 60);
      onCode(text);
    }

    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      } catch (e) {
        status.style.color = '#dc3545';
        status.textContent = 'No se pudo acceder a la cámara — revisa los permisos del navegador (la cámara solo funciona en una página segura, https).';
        return;
      }
      video.srcObject = stream;
      let detector = null;
      if ('BarcodeDetector' in window) {
        try { detector = new BarcodeDetector({ formats: ['qr_code'] }); } catch (e) { detector = null; }
      }
      const jsQR = detector ? null : await loadJsQr().catch(() => null);
      if (!detector && !jsQR) { status.style.color = '#dc3545'; status.textContent = 'No se pudo cargar el lector de QR (sin internet). Usa el lector de mano o escribe la cédula.'; return; }
      const ctx = canvas.getContext('2d', { willReadFrequently: true });

      async function tick() {
        if (stopped) return;
        if (video.videoWidth) {
          try {
            if (detector) {
              const codes = await detector.detect(video);
              if (codes.length) emit(codes[0].rawValue);
            } else {
              canvas.width = video.videoWidth; canvas.height = video.videoHeight;
              ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
              const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
              const code = jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
              if (code && code.data) emit(code.data);
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

  if (typeof window !== 'undefined') { window.QrCode = { parse }; window.QrScanner = { open }; }
  if (typeof module !== 'undefined') module.exports = { parse };  // para las pruebas en Node
})();
