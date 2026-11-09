/* Piezas comunes de las páginas de contactos (Fase 8): QR de un enlace y escritura de una etiqueta NFC desde el navegador.
   Web NFC solo existe en Chrome para Android, con https y tras un toque del usuario; en cualquier otro teléfono el botón se oculta y el QR sigue sirviendo. */
(function () {
  'use strict';
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function drawQr(host, text) {
    if (!host || typeof window.qrcode !== 'function') return;
    const q = window.qrcode(0, 'M');
    q.addData(text);
    q.make();
    host.innerHTML = q.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
    const svg = host.querySelector('svg');
    if (svg) { svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Código QR'); svg.style.width = '100%'; svg.style.height = 'auto'; }
  }

  const nfcSupported = () => 'NDEFReader' in window && window.isSecureContext;

  /* Escribe la dirección en una etiqueta NTAG213/215. Debe llamarse desde un clic. */
  async function writeTag(url, statusEl) {
    const say = (t) => { if (statusEl) statusEl.textContent = t; };
    try {
      const reader = new window.NDEFReader();
      say('Acerca la etiqueta a la parte de atrás del teléfono…');
      await reader.write({ records: [{ recordType: 'url', data: url }] });
      say('Listo: la etiqueta quedó escrita. Pruébala acercando otro teléfono.');
      return true;
    } catch (err) {
      say(err && err.name === 'NotAllowedError' ? 'El teléfono no dio permiso para usar el NFC. Actívalo en ajustes y vuelve a intentar.' : 'No se pudo escribir la etiqueta. Acércala mejor, o revisa que sea NTAG213 o NTAG215.');
      return false;
    }
  }

  function absolute(path) { return location.origin + path; }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { return false; }
  }

  window.GWContact = { esc, drawQr, nfcSupported, writeTag, absolute, copyText };
})();
