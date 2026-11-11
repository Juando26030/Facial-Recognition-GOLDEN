/* Panel «Historial de cambios» de Editar evento (Fase 5). Solo lectura, paginado, filtrable por campo. API: GET /api/events/{id}/change-history.
   Uso: EventHistoryPanel.bind(detailsEl) una vez; EventHistoryPanel.show(eventId) cada vez que se abre la ventana (la carga es perezosa: solo al desplegar el grupo). */
(function () {
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const SOURCES = { edit: 'Edición', state: 'Estado', switch: 'Opción', import: 'Importación' };
  let root = null, eventId = null, page = 1, field = '', loadedFor = null;

  const el = (sel) => root.querySelector(sel);

  async function load() {
    if (!root || !eventId) return;
    const body = el('[data-eh="body"]'), info = el('[data-eh="info"]');
    if (window.GW && GW.skeleton) GW.skeleton(body, { kind: 'table', rows: 5, cols: 4, label: 'Cargando el historial…' });
    else body.innerHTML = '<tr><td colspan="4" class="gw-hint">Cargando…</td></tr>';
    let data;
    try {
      const qs = new URLSearchParams({ page: String(page), per_page: '10' });
      if (field) qs.set('field', field);
      const res = await fetch(`/api/events/${eventId}/change-history?${qs}`);
      if (!res.ok) throw new Error('http ' + res.status);
      data = await res.json();
    } catch (e) {
      if (window.GW && GW.skeleton) GW.skeleton.error(body, { cols: 4, title: 'No se pudo cargar el historial', text: 'Cierra y vuelve a abrir este grupo para intentarlo de nuevo.', retry: false });
      else body.innerHTML = '<tr><td colspan="4" class="gw-hint">No se pudo cargar el historial.</td></tr>';
      if (window.showToast) showToast('No se pudo cargar el historial de cambios', 'error');
      return;
    }
    loadedFor = eventId;
    const sel = el('[data-eh="field"]');
    sel.innerHTML = '<option value="">Todos los campos</option>' + data.fields.map((f) => `<option value="${esc(f.key)}"${f.key === field ? ' selected' : ''}>${esc(f.label)}</option>`).join('');
    body.innerHTML = data.items.length
      ? data.items.map((r) => `<tr><td>${esc(r.changed_at_local)}</td><td>${esc(r.changed_by || '—')}</td><td>${esc(r.field_label)} <span class="gw-badge gw-badge--info">${esc(SOURCES[r.source] || r.source)}</span></td>`
        + `<td>${r.old_value == null ? '<span class="gw-hint">(vacío)</span>' : esc(r.old_value)} &rarr; ${r.new_value == null ? '<span class="gw-hint">(vacío)</span>' : esc(r.new_value)}</td></tr>`).join('')
      : '<tr><td colspan="4" class="gw-hint">Aún no hay cambios registrados.</td></tr>';
    const pages = Math.max(1, Math.ceil(data.total / data.per_page));
    info.textContent = `${data.total} cambio(s) · página ${data.page} de ${pages}`;
    el('[data-eh="prev"]').disabled = data.page <= 1;
    el('[data-eh="next"]').disabled = data.page >= pages;
  }

  function bind(details) {
    root = details;
    details.addEventListener('toggle', () => { if (details.open && loadedFor !== eventId) { page = 1; load(); } });
    details.addEventListener('change', (e) => { if (e.target.matches('[data-eh="field"]')) { field = e.target.value; page = 1; load(); } });
    details.addEventListener('click', (e) => {
      const b = e.target.closest('[data-eh="prev"],[data-eh="next"]');
      if (!b || b.disabled) return;
      page += b.dataset.eh === 'next' ? 1 : -1;
      load();
    });
  }

  function show(id) {
    eventId = id; page = 1; field = ''; loadedFor = null;
    if (root && root.open) load();
  }

  window.EventHistoryPanel = { bind, show };
})();
