/* Documentos del evento (Fase 1.5): lista como tarjetas, subida directa con rueda en el botón y archivado y borrado definitivo con confirmación.
   La lógica y las rutas de la API son las de siempre; solo cambió cómo se ve. */
(function () {
  'use strict';
  const EVENT_ID = window.EVENT_ID;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icon = (n) => '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="' + window.GW_ICONS + '#i-' + n + '"/></svg>';
  const fmtSize = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round((b || 0) / 1024)) + ' KB');
  const fileKind = (n) => { const m = /\.([A-Za-z0-9]{1,5})$/.exec(n || ''); return m ? m[1].toUpperCase() : 'Archivo'; };
  const ROLE = window.STAFF_ROLE || '', isAdmin = ROLE === 'admin' || ROLE === 'super_admin', isSuper = ROLE === 'super_admin';
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));

  function setList(html, loading) {
    const list = $('docList');
    list.innerHTML = html;
    list.setAttribute('aria-busy', loading ? 'true' : 'false');
  }

  async function loadDocs() {
    let docs = [];
    try {
      const withArchived = isAdmin && $('showArchived') && $('showArchived').checked;
      const res = await fetch('/api/events/' + EVENT_ID + '/documents' + (withArchived ? '?include_archived=true' : ''));
      if (!res.ok) throw new Error('http ' + res.status);
      docs = await res.json();
    } catch (err) {
      $('docCount').textContent = '';
      $('docTotal').textContent = '–';
      $('zipBtn').hidden = true;
      setList('<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudieron cargar los documentos</p><p class="gw-state__text">Revisa tu conexión e inténtalo de nuevo.</p><button type="button" class="gw-btn gw-btn--secondary" data-retry>Reintentar</button></div>');
      return;
    }
    const active = docs.filter((d) => !d.archived).length;
    $('docTotal').textContent = String(active);
    $('docCount').textContent = docs.length ? '(' + docs.length + ')' : '';
    $('zipBtn').hidden = !active;
    if (!docs.length) {
      setList('<div class="gw-state"><span class="gw-state__icon">' + icon('inbox').replace(' gw-icon--sm', '') + '</span><p class="gw-state__title">Todavía no hay documentos</p><p class="gw-state__text">Sube el primero con el botón «Subir documento» de arriba.</p></div>');
      return;
    }
    setList(docs.map((d) => `
      <article class="gw-card-row">
        <div class="gw-card-row__head"><h3 class="gw-card-row__title">${esc(d.name)}</h3><span class="gw-badge gw-badge--ok">${esc(fileKind(d.filename))}</span>${d.archived ? ' <span class="gw-badge">Archivado</span>' : ''}</div>
        <p class="gw-card-row__meta">${esc(d.filename)} · ${fmtSize(d.size_bytes)}${d.created_at ? ' · ' + new Date(d.created_at + 'Z').toLocaleDateString() : ''}</p>
        ${d.description ? `<p class="gw-text-sm">${esc(d.description)}</p>` : ''}
        <div class="gw-card-row__actions">
          <a class="gw-btn gw-btn--secondary gw-btn--sm" href="/api/events/${EVENT_ID}/documents/${d.id}/download">${icon('download')} Descargar</a>
          ${isAdmin && !d.archived ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-archive="${d.id}" data-name="${esc(d.name)}">Archivar</button>` : ''}
          ${isAdmin && d.archived ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-restore="${d.id}" data-name="${esc(d.name)}">${icon('undo')} Restaurar</button>` : ''}
          ${isSuper && d.archived ? `<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-del="${d.id}" data-name="${esc(d.name)}">${icon('trash')} Eliminar definitivamente</button>` : ''}
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
    const btn = e.target.closest('[data-archive], [data-restore], [data-del]');
    if (!btn) return;
    const name = window.escapeHtml(btn.dataset.name);
    const act = btn.dataset.archive ? 'archive' : btn.dataset.restore ? 'restore' : 'delete';
    const id = btn.dataset.archive || btn.dataset.restore || btn.dataset.del;
    const cfg = {
      archive: ['¿Archivar el documento "' + name + '"? Se oculta de la lista y del ZIP, pero se conserva y se puede restaurar.', 'Archivar', 'Documento archivado'],
      restore: ['¿Restaurar el documento "' + name + '"?', 'Restaurar', 'Documento restaurado'],
      delete: ['¿Eliminar definitivamente el documento "' + name + '" y su archivo? No se puede deshacer.', 'Eliminar definitivamente', 'Documento eliminado definitivamente'],
    }[act];
    if (!await showConfirm(cfg[0], { confirmLabel: cfg[1] })) return;
    const url = '/api/events/' + EVENT_ID + '/documents/' + id + (act === 'delete' ? '' : '/' + act);
    let ok = false, msg = '';
    try {
      await busy(btn, async () => {
        const res = await fetch(url, { method: act === 'delete' ? 'DELETE' : 'POST' });
        ok = res.ok;
        if (!ok) msg = (await res.json().catch(() => ({}))).detail || '';
      });
    } catch (err) { ok = false; }
    showToast(ok ? cfg[2] : (msg || 'No se pudo completar la acción'), ok ? 'success' : 'error');
    loadDocs();
  });

  if ($('showArchived')) $('showArchived').addEventListener('change', loadDocs);
  loadDocs();
})();
