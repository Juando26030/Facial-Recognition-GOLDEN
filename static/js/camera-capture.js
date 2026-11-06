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
    overlay.className = 'gw-modal-backdrop gw-modal-backdrop--top'; overlay.setAttribute('data-open', 'true');
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', title);
    const box = document.createElement('div');
    box.className = 'gw-modal gw-modal--dialog gw-cam';
    const iconUrl = (window.GW_ICON_URL || '/static/img/icons.svg');
    box.innerHTML = `
      <div class="gw-modal__head"><h2 class="gw-modal__title"></h2></div>
      <div class="gw-modal__body">
        <video class="gw-cam__video" autoplay playsinline aria-label="Vista de la cámara"></video>
        <canvas hidden></canvas>
        <p class="gw-alert gw-alert--err cam-error" role="alert" hidden></p>
      </div>
      <div class="gw-modal__foot">
        <button type="button" class="gw-btn gw-btn--secondary cam-cancel">Cancelar</button>
        <button type="button" class="gw-btn gw-btn--primary cam-capture"><svg class="gw-icon" aria-hidden="true"><use href="${iconUrl}#i-camera"/></svg>Tomar foto</button>
      </div>
    `;
    box.querySelector('.gw-modal__title').textContent = title;
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
        errorEl.hidden = false;
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
