/* Widget compartido de captura por cámara (Sprint 2.2 Fase C, 2026-09-16) — pedido explícito:
   tanto el escaneo de la cédula nueva (foto del reverso, MRZ) como la foto de alta manual en
   eventos biométricos deben poder tomarse con la cámara del computador, no solo adjuntar un
   archivo. El escáner facial de la pestaña "Escáner de Acceso" (app.js) ya tenía su propio
   <video>/<canvas> fijo en el HTML — este módulo es para los dos usos NUEVOS, que abren y
   cierran la cámara bajo demanda (no la dejan prendida todo el tiempo), así que necesitan su
   propio modal con getUserMedia/stop en vez de reusar el <video> del escáner. */
(function () {
  function open(opts) {
    opts = opts || {};
    const title = opts.title || 'Tomar foto';
    const onCapture = opts.onCapture || function () {};

    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed; inset:0; background:rgba(10,14,46,0.6); z-index:9998; display:flex; align-items:center; justify-content:center; padding:1rem;';
    const box = document.createElement('div');
    box.style.cssText = 'background:white; border-radius:16px; padding:1.4rem; max-width:480px; width:100%; box-shadow:0 20px 60px rgba(0,0,0,0.4); text-align:center; font-family: var(--font-body, sans-serif);';
    box.innerHTML = `
      <h4 style="margin-top:0; color:var(--golden-dark);">${title}</h4>
      <video autoplay playsinline style="width:100%; border-radius:10px; background:#000;"></video>
      <canvas style="display:none;"></canvas>
      <p class="cam-error" style="color:#dc3545; font-size:0.85rem; display:none; margin-top:0.6rem;"></p>
      <div style="display:flex; justify-content:center; gap:10px; margin-top:1rem;">
        <button type="button" class="cam-cancel" style="border:1px solid #ccc; background:white; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:600;">Cancelar</button>
        <button type="button" class="cam-capture" style="border:none; background:var(--golden-primary,#D4AF37); color:#1a1200; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:700;">📸 Tomar foto</button>
      </div>
    `;
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    const video = box.querySelector('video');
    const canvas = box.querySelector('canvas');
    const errorEl = box.querySelector('.cam-error');
    let stream = null;

    function stopStream() {
      if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    }
    function close() { stopStream(); overlay.remove(); }

    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      .then(s => { stream = s; video.srcObject = s; })
      .catch(() => {
        errorEl.innerText = 'No se pudo acceder a la cámara — revisa los permisos del navegador, o usa "Adjuntar imagen" en su lugar.';
        errorEl.style.display = 'block';
      });

    box.querySelector('.cam-cancel').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    box.querySelector('.cam-capture').addEventListener('click', () => {
      if (!video.videoWidth) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        close();
        onCapture(blob);
      }, 'image/jpeg', 0.92);
    });
  }

  window.CameraCapture = { open };
})();
