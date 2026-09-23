/* Enlace público para que cada persona descargue su certificado (/c/<token>, sin iniciar sesión).
   Se usa en el diseñador del certificado y en la página "Certificados" del evento:
   CertificateLink.mount(contenedor, eventId). Sin enlace muestra el botón "Generar enlace"; con enlace,
   el campo para copiarlo y "Cambiar enlace" (el anterior deja de funcionar). */
(function () {
  const api = (eventId) => `/api/events/${eventId}/certificates/public-link`;
  const esc = (t) => String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

  async function mount(box, eventId) {
    let url = null;
    try {
      const res = await fetch(api(eventId));
      if (res.ok) url = (await res.json()).url;
    } catch (e) { /* se muestra el botón de generar */ }

    const head = `<h4 style="margin:0 0 0.4rem; color:var(--golden-dark);">Enlace para que cada persona descargue su certificado</h4>
      <p style="margin:0 0 0.6rem; font-size:0.85rem; color:#666;">Es un enlace público: quien lo abre <strong>no necesita iniciar sesión</strong>, escribe su cédula, confirma que es él/ella y descarga su propio certificado. Desde ahí no se puede entrar a nada más de la plataforma. Solo aparecen quienes tengan Certificado = Sí, y cuando el evento esté Finalizado.</p>`;

    if (!url) {
      box.innerHTML = head + `<button type="button" id="clGenerate" class="golden-btn golden-btn-primary" style="width:auto; padding:0.6rem 1.6rem;">🔗 Generar enlace</button>`;
      box.querySelector('#clGenerate').addEventListener('click', async () => {
        const res = await fetch(api(eventId), { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.detail || 'No se pudo generar el enlace', 'error'); return; }
        showToast('Enlace generado', 'success');
        mount(box, eventId);
      });
      return;
    }

    box.innerHTML = head + `
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
        <input type="text" id="clInput" readonly value="${esc(url)}" style="flex:1 1 280px; padding:0.6rem; border:1px solid #ddd; border-radius:10px; font-size:0.85rem;">
        <button type="button" id="clCopy" class="golden-btn golden-btn-primary" style="width:auto; padding:0.6rem 1.4rem;">Copiar enlace</button>
        <a href="${esc(url)}" target="_blank" rel="noopener" class="golden-btn" style="width:auto; padding:0.6rem 1rem; background:#f0f0f0; color:var(--golden-dark); text-decoration:none;">Abrir</a>
        <button type="button" id="clRegen" class="golden-btn" style="width:auto; padding:0.6rem 1rem; background:#f0f0f0; color:var(--golden-dark);" title="El enlace anterior deja de funcionar">Cambiar enlace</button>
      </div>`;
    box.querySelector('#clCopy').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(url); }
      catch (e) { const i = box.querySelector('#clInput'); i.select(); document.execCommand('copy'); }
      showToast('Enlace copiado', 'success');
    });
    box.querySelector('#clRegen').addEventListener('click', async () => {
      if (!(await showConfirm('Se creará un enlace nuevo y el anterior dejará de funcionar. ¿Continuar?', { variant: 'warning', confirmLabel: 'Sí, cambiar enlace' }))) return;
      const res = await fetch(api(eventId) + '?regenerate=true', { method: 'POST' });
      if (!res.ok) { showToast('No se pudo cambiar el enlace', 'error'); return; }
      mount(box, eventId);
    });
  }

  window.CertificateLink = { mount };
})();
