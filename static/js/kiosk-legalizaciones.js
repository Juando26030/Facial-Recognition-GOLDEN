/* Legalizaciones del evento (Fase 1.5): gastos como tarjetas, alta con rueda en el botón y archivado y borrado definitivo con confirmación.
   La lógica y las rutas de la API son las de siempre; solo cambió cómo se ve. */
(function () {
  'use strict';
  const EVENT_ID = window.EVENT_ID;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icon = (n) => '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="' + window.GW_ICONS + '#i-' + n + '"/></svg>';
  const money = (n) => Number(n || 0).toLocaleString('es-CO', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const ROLE = window.STAFF_ROLE || '', canArchive = ['coordinador', 'comercial', 'admin', 'super_admin'].includes(ROLE), isSuper = ROLE === 'super_admin';
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));

  function setList(html, loading) {
    const list = $('expList');
    list.innerHTML = html;
    list.setAttribute('aria-busy', loading ? 'true' : 'false');
  }

  async function loadExpenses() {
    let data;
    try {
      const withArchived = canArchive && $('showArchived') && $('showArchived').checked;
      const res = await fetch('/api/events/' + EVENT_ID + '/expenses' + (withArchived ? '?include_archived=true' : ''));
      if (!res.ok) throw new Error('http ' + res.status);
      data = await res.json();
    } catch (err) {
      setList('<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudieron cargar los gastos</p><p class="gw-state__text">Revisa tu conexión e inténtalo de nuevo.</p><button type="button" class="gw-btn gw-btn--secondary" data-retry>Reintentar</button></div>');
      return;
    }
    $('totalAmount').textContent = money(data.total);
    $('expCount').textContent = String(data.expenses.filter((x) => !x.archived).length);
    if (!data.expenses.length) {
      setList('<div class="gw-state">' + icon('form') + '<p class="gw-state__title">Todavía no hay gastos</p><p class="gw-state__text">Registra el primero con el botón «Registrar gasto» de arriba.</p></div>');
      return;
    }
    setList(data.expenses.map((x) => `
      <article class="gw-card-row">
        <div class="gw-card-row__head">
          <h3 class="gw-card-row__title">${esc(x.category)}</h3>
          <span class="gw-badge ${x.has_evidence ? 'gw-badge--ok' : 'gw-badge--warn'}">${x.has_evidence ? 'Con evidencia' : 'Sin evidencia'}</span>${x.archived ? ' <span class="gw-badge">Archivado</span>' : ''}
        </div>
        <p class="gw-card-row__amount">${money(x.amount)}</p>
        <p class="gw-card-row__meta">${x.created_at ? new Date(x.created_at + 'Z').toLocaleDateString() + ' · ' : ''}Responsable: ${esc(x.responsible)}${x.applies_to ? ' · Aplica a: ' + esc(x.applies_to) : ''}</p>
        ${x.description ? `<p class="gw-text-sm">${esc(x.description)}</p>` : ''}
        ${x.has_evidence ? `<a href="/api/events/${EVENT_ID}/expenses/${x.id}/evidence" target="_blank" rel="noopener" aria-label="Abrir la evidencia en una pestaña nueva"><img class="gw-card-row__thumb" src="/api/events/${EVENT_ID}/expenses/${x.id}/evidence" alt="Evidencia del gasto" loading="lazy"></a>` : ''}
        <div class="gw-card-row__actions">
          ${canArchive && !x.archived ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-archive="${x.id}">Archivar</button>` : ''}
          ${canArchive && x.archived ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-restore="${x.id}">${icon('undo')} Restaurar</button>` : ''}
          ${isSuper && x.archived ? `<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-del="${x.id}">${icon('trash')} Eliminar definitivamente</button>` : ''}
        </div>
      </article>`).join(''));
  }

  $('expForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    busy(btn, async () => {
      const fd = await DirectUpload.replaceFiles(new FormData(form), { evidence: ['evidence_upload', 'expense_evidence'] }, { body: { event_id: EVENT_ID } });
      const res = await fetch('/api/events/' + EVENT_ID + '/expenses', { method: 'POST', body: fd });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'No se pudo guardar el gasto');
    }).then(() => {
      form.reset();
      showToast('Gasto registrado', 'success');
      loadExpenses();
    }).catch((err) => showToast(err.message || 'No se pudo guardar el gasto', 'error'));
  });

  $('expList').addEventListener('click', async (e) => {
    if (e.target.closest('[data-retry]')) { setList('<span class="gw-skeleton" role="status"><span class="gw-sr-only">Cargando gastos…</span></span>', true); loadExpenses(); return; }
    const btn = e.target.closest('[data-archive], [data-restore], [data-del]');
    if (!btn) return;
    const act = btn.dataset.archive ? 'archive' : btn.dataset.restore ? 'restore' : 'delete';
    const id = btn.dataset.archive || btn.dataset.restore || btn.dataset.del;
    const cfg = {
      archive: ['¿Archivar este gasto? Sale de la lista, del total y del reporte, pero se conserva (con su evidencia) y se puede restaurar.', 'Archivar', 'Gasto archivado'],
      restore: ['¿Restaurar este gasto? Vuelve a la lista y a sumar en el total.', 'Restaurar', 'Gasto restaurado'],
      delete: ['¿Eliminar definitivamente este gasto y su evidencia? No se puede deshacer.', 'Eliminar definitivamente', 'Gasto eliminado definitivamente'],
    }[act];
    if (!await showConfirm(cfg[0], { confirmLabel: cfg[1] })) return;
    const url = '/api/events/' + EVENT_ID + '/expenses/' + id + (act === 'delete' ? '' : '/' + act);
    let ok = false, msg = '';
    try {
      await busy(btn, async () => {
        const res = await fetch(url, { method: act === 'delete' ? 'DELETE' : 'POST' });
        ok = res.ok;
        if (!ok) msg = (await res.json().catch(() => ({}))).detail || '';
      });
    } catch (err) { ok = false; }
    showToast(ok ? cfg[2] : (msg || 'No se pudo completar la acción'), ok ? 'success' : 'error');
    loadExpenses();
  });

  if ($('showArchived')) $('showArchived').addEventListener('change', loadExpenses);
  loadExpenses();
})();
