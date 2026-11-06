/* Documentos del evento (Fase 1.5): lista como tarjetas, subida directa con rueda en el botón y borrado con confirmación.
   La lógica y las rutas de la API son las de siempre; solo cambió cómo se ve. */
(function () {
  'use strict';
  const EVENT_ID = window.EVENT_ID;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icon = (n) => '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="' + window.GW_ICONS + '#i-' + n + '"/></svg>';
  const fmtSize = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round((b || 0) / 1024)) + ' KB');
  const fileKind = (n) => { const m = /\.([A-Za-z0-9]{1,5})$/.exec(n || ''); return m ? m[1].toUpperCase() : 'Archivo'; };
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));

  function setList(html, loading) {
    const list = $('docList');
    list.innerHTML = html;
    list.setAttribute('aria-busy', loading ? 'true' : 'false');
  }

  async function loadDocs() {
    let docs = [];
    try {
      const res = await fetch('/api/events/' + EVENT_ID + '/documents');
      if (!res.ok) throw new Error('http ' + res.status);
      docs = await res.json();
    } catch (err) {
      $('docCount').textContent = '';
      $('docTotal').textContent = '–';
      $('zipBtn').hidden = true;
      setList('<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudieron cargar los documentos</p><p class="gw-state__text">Revisa tu conexión e inténtalo de nuevo.</p><button type="button" class="gw-btn gw-btn--secondary" data-retry>Reintentar</button></div>');
      return;
    }
    $('docTotal').textContent = String(docs.length);
    $('docCount').textContent = docs.length ? '(' + docs.length + ')' : '';
    $('zipBtn').hidden = !docs.length;
    if (!docs.length) {
      setList('<div class="gw-state">' + icon('inbox') + '<p class="gw-state__title">Todavía no hay documentos</p><p class="gw-state__text">Sube el primero con el botón «Subir documento» de arriba.</p></div>');
      return;
    }
    setList(docs.map((d) => `
      <article class="gw-card-row">
        <div class="gw-card-row__head"><h3 class="gw-card-row__title">${esc(d.name)}</h3><span class="gw-badge gw-badge--ok">${esc(fileKind(d.filename))}</span></div>
        <p class="gw-card-row__meta">${esc(d.filename)} · ${fmtSize(d.size_bytes)}${d.created_at ? ' · ' + new Date(d.created_at + 'Z').toLocaleDateString() : ''}</p>
        ${d.description ? `<p class="gw-text-sm">${esc(d.description)}</p>` : ''}
        <div class="gw-card-row__actions">
          <a class="gw-btn gw-btn--secondary gw-btn--sm" href="/api/events/${EVENT_ID}/documents/${d.id}/download">${icon('download')} Descargar</a>
          <button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-del="${d.id}" data-name="${esc(d.name)}">${icon('trash')} Eliminar</button>
        </div>
      </article>`).join(''));
  }

  $('docForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    busy(btn, async () => {
      const fd = await DirectUpload.replaceFiles(new FormData(form), { file: ['upload', 'event_doc'] }, { body: { event_id: EVENT_ID } });
      const res = await fetch('/api/events/' + EVENT_ID + '/documents', { method: 'POST', body: fd });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'No se pudo subir el documento');
    }).then(() => {
      form.reset();
      showToast('Documento subido', 'success');
      loadDocs();
    }).catch((err) => showToast(err.message || 'No se pudo subir el documento', 'error'));
  });

  $('docList').addEventListener('click', async (e) => {
    if (e.target.closest('[data-retry]')) { setList('<span class="gw-skeleton" role="status"><span class="gw-sr-only">Cargando documentos…</span></span>', true); loadDocs(); return; }
    const btn = e.target.closest('[data-del]');
    if (!btn) return;
    if (!await showConfirm('¿Eliminar el documento "' + window.escapeHtml(btn.dataset.name) + '"? No se puede deshacer.', { confirmLabel: 'Eliminar' })) return;
    let ok = false;
    try { await busy(btn, async () => { ok = (await fetch('/api/events/' + EVENT_ID + '/documents/' + btn.dataset.del, { method: 'DELETE' })).ok; }); } catch (err) { ok = false; }
    showToast(ok ? 'Documento eliminado' : 'No se pudo eliminar', ok ? 'success' : 'error');
    loadDocs();
  });

  loadDocs();
})();
