/* Clientes - Cuentas (templates/clientes.html). Lógica de siempre (rutas /api/tenants y /api/events, permisos por rol), con la piel nueva: tarjetas, estados vacío/cargando/error,
   GW.busy en los botones que hacen peticiones y delegación de eventos (sin onclick en línea). */
(function () {
  'use strict';
  const root = document.getElementById('clientesRoot');
  if (!root) return;
  const role = root.dataset.staffRole || '';
  const ICONS = root.dataset.icons || '';
  const isAdmin = role === 'admin' || role === 'super_admin';
  const isSuper = role === 'super_admin';
  // 4-nov-2026 (decisión del dueño): el coordinador también crea EVENTOS (en su cliente); crear CLIENTES sigue siendo comercial+ (el grupo de crear cliente no se pinta para el coordinador).
  const canCreate = true;
  const STATUS_LABELS = { creado: 'Creado', en_proceso: 'En Proceso', finalizado: 'Finalizado' };
  const STATUS_BADGE = { creado: 'gw-badge--info', en_proceso: 'gw-badge--ok', finalizado: '' };

  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const stripAccents = (text) => String(text || '').normalize('NFD').replace(/[̀-ͯ]/g, '');
  const fmtDate = (d) => (d ? new Date(d).toLocaleDateString() : '-');
  const icon = (name, cls) => '<svg class="gw-icon ' + (cls || '') + '" aria-hidden="true"><use href="' + esc(ICONS) + '#i-' + name + '"/></svg>';
  const emptyBox = (title, text) => '<div class="gw-empty" role="status"><p><strong>' + esc(title) + '</strong></p><p>' + esc(text) + '</p></div>';
  const errorBox = (text, retry) => '<div class="gw-alert gw-alert--err" role="alert">' + icon('error') + '<div class="gw-alert__body">' + esc(text) + '</div>' +
    (retry ? '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-retry="' + retry + '">Reintentar</button>' : '') + '</div>';
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));

  const listEl = document.getElementById('tenantsList');
  let allTenants = [];
  const tenantEventsCache = new WeakMap();

  /* ---------------------------------------------------------------- Lista de clientes */
  async function loadTenants() {
    listEl.setAttribute('aria-busy', 'true');
    try {
      const res = await fetch('/api/tenants');
      if (!res.ok) throw new Error('http');
      allTenants = await res.json();
      renderTenants(allTenants);
    } catch (e) {
      listEl.innerHTML = errorBox('No se pudieron cargar los clientes. Revisa la conexión e inténtalo de nuevo.', 'tenants');
    } finally { listEl.removeAttribute('aria-busy'); }
  }

  function renderTenants(list) {
    if (!allTenants.length) { listEl.innerHTML = emptyBox('Todavía no hay clientes', role === 'coordinador' ? 'Cuando un administrador cree una cuenta, aparecerá aquí.' : 'Crea el primero con «Nuevo cliente/cuenta».'); return; }
    if (!list.length) { listEl.innerHTML = emptyBox('Sin resultados', 'Ningún cliente coincide con la búsqueda. Prueba con otra parte del nombre.'); return; }
    listEl.innerHTML = list.map((t) => `
      <article class="gw-card-row tenant-card" data-tenant-id="${esc(t.id)}">
        <button type="button" class="gw-tenant__head" data-action="toggle-tenant" aria-expanded="false" aria-controls="tenantBody${esc(t.id)}">
          <span>
            <span class="gw-card-row__title">${esc(t.name)} <span class="gw-tenant__code">#${esc(t.client_code)}</span></span>
            <span class="gw-card-row__meta">${esc(t.contact_name) || 'Sin contacto'}${t.contact_phone ? ' · ' + esc(t.contact_phone) : ''}</span>
          </span>
          <span class="gw-tenant__toggle">Ver eventos ${icon('chevron', 'gw-icon--sm')}</span>
        </button>
        ${canCreate ? `<a href="/clientes/${esc(t.id)}/nuevo-evento" class="gw-btn gw-btn--primary gw-btn--xl p-cli__new">${icon('plus')} Nuevo evento</a>` : ''}
        <div class="gw-tenant__body" id="tenantBody${esc(t.id)}" data-tenant-body hidden>
          ${isSuper ? `<div class="gw-card-row__actions"><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-import-event data-tenant-id="${esc(t.id)}" data-tenant-name="${esc(t.name)}" title="Crear un evento nuevo de este cliente a partir de un paquete exportado de otro entorno">${icon('upload', 'gw-icon--sm')} Importar evento</button></div>` : ''}
          <div class="gw-field">
            <label class="gw-label" for="evSearch${esc(t.id)}">Buscar evento de este cliente/cuenta</label>
            <input type="search" class="gw-input" id="evSearch${esc(t.id)}" data-events-search placeholder="Buscar evento de este cliente/cuenta..." autocomplete="off">
          </div>
          <div data-events-container aria-live="polite"></div>
        </div>
      </article>`).join('');
  }

  /* ---------------------------------------------------------------- Eventos de un cliente */
  async function loadEventsForTenant(tenantId, card) {
    const el = card.querySelector('[data-events-container]');
    if (!tenantEventsCache.has(card)) el.innerHTML = '<div class="gw-skeleton gw-adm-skeleton" aria-hidden="true"></div><span class="gw-sr-only">Cargando eventos…</span>';
    try {
      const res = await fetch('/api/events?tenant_id=' + encodeURIComponent(tenantId));
      if (!res.ok) throw new Error('http');
      const events = await res.json();
      tenantEventsCache.set(card, events);
      if (!events.length) { el.innerHTML = emptyBox('Sin eventos todavía', 'Usa «Nuevo evento» para crear el primero de esta cuenta.'); return; }
      renderEventRows(events, el);
    } catch (e) {
      el.innerHTML = errorBox('No se pudieron cargar los eventos de esta cuenta.', 'events');
    }
  }

  // Búsqueda de eventos DENTRO de la tarjeta de un cliente/cuenta (2026-09-17): filtra en memoria sobre lo que ya trajo loadEventsForTenant.
  function renderEventRows(events, el) {
    if (!events.length) { el.innerHTML = emptyBox('Sin resultados', 'Ningún evento coincide con la búsqueda.'); return; }
    el.innerHTML = '<div class="gw-event-list">' + events.map((e) => `
      <div class="gw-card-row gw-event-card">
        <div class="gw-card-row__head">
          <span class="gw-card-row__title">${window.reportBulbHtml ? reportBulbHtml(e) : ''} ${esc(e.name)} ${e.event_code ? `<span class="gw-event-code">(${esc(e.event_code)})</span>` : ''}</span>
          <span class="gw-badge ${STATUS_BADGE[e.status] || ''}">${esc(STATUS_LABELS[e.status] || e.status)}</span>
        </div>
        <p class="gw-card-row__meta">${esc(e.location) || ''}${e.city ? ' · ' + esc(e.city) : ''} · ${fmtDate(e.start_date)} · Coordinador: ${esc(e.coordinator_name) || '-'}</p>
        <div class="gw-card-row__actions">
          <a class="gw-btn gw-btn--secondary gw-btn--sm" href="/kiosk/${esc(e.id)}">${icon('home', 'gw-icon--sm')} Ingresar</a>
          <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-edit-event="${esc(e.id)}">${icon('edit', 'gw-icon--sm')} Editar</button>
          ${isAdmin && e.status === 'en_proceso' ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-revert-event="${esc(e.id)}" title="Devolver el evento a Creado (no se borra nada)">${icon('undo', 'gw-icon--sm')} Devolver a Creado</button>` : ''}
          ${isSuper ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-export-event="${esc(e.id)}" data-event-name="${esc(e.name)}" title="Exportar el evento completo (paquete .zip)">${icon('download', 'gw-icon--sm')} Exportar</button>` : ''}
          <select class="gw-select gw-select--auto" data-status-select data-event-id="${esc(e.id)}" aria-label="Estado de ${esc(e.name)}">
            ${Object.entries(STATUS_LABELS).map(([value, label]) => `<option value="${value}" ${value === e.status ? 'selected' : ''}>${label}</option>`).join('')}
          </select>
          ${isAdmin ? `<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-delete-event="${esc(e.id)}" data-event-name="${esc(e.name)}" data-event-status="${esc(e.status)}">${icon('trash', 'gw-icon--sm')} Eliminar</button>` : ''}
        </div>
      </div>`).join('') + '</div>';
  }

  /* ---------------------------------------------------------------- Acciones */
  async function setEventStatus(eventId, status, card) {
    const res = await fetch('/api/events/' + encodeURIComponent(eventId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
    loadEventsForTenant(card.dataset.tenantId, card);
    showToast(res.ok ? `Evento pasó a "${STATUS_LABELS[status]}"` : 'No se pudo actualizar el evento', res.ok ? 'success' : 'error');
  }

  async function deleteEvent(eventId, name, status, btn) {
    const confirmed = await showConfirm(
      `¿Está seguro que quiere eliminar el evento "${escapeHtml(name)}"?<br><br>` +
      `Recuerde que este evento está en estado <strong>${escapeHtml(STATUS_LABELS[status] || status)}</strong>. ` +
      'Esta acción es permanente y no se puede deshacer.',
      { confirmLabel: 'Eliminar evento' }
    );
    if (!confirmed) return;
    const card = btn.closest('.tenant-card');
    await busy(btn, async () => {
      const res = await fetch('/api/events/' + encodeURIComponent(eventId), { method: 'DELETE' });
      loadEventsForTenant(card.dataset.tenantId, card);
      showToast(res.ok ? 'Evento eliminado' : 'No se pudo eliminar el evento', res.ok ? 'success' : 'error');
    });
  }

  listEl.addEventListener('click', async (e) => {
    const retry = e.target.closest('[data-retry]');
    if (retry) {
      if (retry.dataset.retry === 'tenants') { loadTenants(); return; }
      const card = retry.closest('.tenant-card');
      if (card) loadEventsForTenant(card.dataset.tenantId, card);
      return;
    }
    const head = e.target.closest('[data-action="toggle-tenant"]');
    if (head) {
      const card = head.closest('.tenant-card');
      const body = card.querySelector('[data-tenant-body]');
      const open = body.hidden;
      body.hidden = !open;
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) loadEventsForTenant(card.dataset.tenantId, card);
      return;
    }
    const editBtn = e.target.closest('[data-edit-event]');
    if (editBtn) {
      const card = editBtn.closest('.tenant-card');
      const ev = (tenantEventsCache.get(card) || []).find((x) => String(x.id) === editBtn.dataset.editEvent);
      if (ev) openEventEditModal(ev, () => loadEventsForTenant(card.dataset.tenantId, card));
      return;
    }
    const deleteBtn = e.target.closest('[data-delete-event]');
    if (deleteBtn) { deleteEvent(deleteBtn.dataset.deleteEvent, deleteBtn.dataset.eventName, deleteBtn.dataset.eventStatus, deleteBtn); return; }
    const revertBtn = e.target.closest('[data-revert-event]');
    if (revertBtn) {
      const card = revertBtn.closest('.tenant-card');
      await busy(revertBtn, async () => { if (await revertEventToCreated(revertBtn.dataset.revertEvent)) loadEventsForTenant(card.dataset.tenantId, card); });
    }
  });

  listEl.addEventListener('input', (e) => {
    const searchInput = e.target.closest('[data-events-search]');
    if (!searchInput) return;
    const card = searchInput.closest('.tenant-card');
    const events = tenantEventsCache.get(card) || [];
    const el = card.querySelector('[data-events-container]');
    const q = stripAccents(searchInput.value.trim()).toLowerCase();
    if (!q) { renderEventRows(events, el); return; }
    renderEventRows(events.filter((ev) => stripAccents(`${ev.name} ${ev.event_code || ''}`).toLowerCase().includes(q)), el);
  });

  listEl.addEventListener('change', async (e) => {
    const select = e.target.closest('[data-status-select]');
    if (!select) return;
    const card = select.closest('.tenant-card');
    const newStatus = select.value;
    const previousStatus = Array.from(select.options).find((o) => o.defaultSelected)?.value;
    if (isAdmin && previousStatus === 'en_proceso' && newStatus === 'creado') {      // el retroceso tiene su propia ventana y su propio rastro
      select.value = previousStatus;
      if (await revertEventToCreated(select.dataset.eventId)) loadEventsForTenant(card.dataset.tenantId, card);
      return;
    }
    const confirmed = await confirmStatusChange(newStatus, STATUS_LABELS[newStatus]);
    if (!confirmed) { select.value = previousStatus; return; }
    select.disabled = true;
    await setEventStatus(select.dataset.eventId, newStatus, card);
  });

  /* ---------------------------------------------------------------- Crear cliente */
  const newTenantForm = document.getElementById('newTenantForm');
  if (newTenantForm) {
    newTenantForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const form = ev.target;
      const payload = Object.fromEntries(new FormData(form).entries());
      await busy(document.getElementById('newTenantSubmit'), async () => {
        const res = await fetch('/api/tenants', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (res.ok) {
          form.reset();
          const group = document.getElementById('newTenantGroup');
          if (group) group.open = false;
          loadTenants();
          showToast('Cliente/Cuenta creado', 'success');
        } else showToast('No se pudo crear el cliente/cuenta', 'error');
      });
    });
  }

  // Búsqueda: solo por nombre de cliente (pedido explícito), en memoria sobre lo que ya trajo /api/tenants.
  document.getElementById('searchBox').addEventListener('input', (e) => {
    const q = stripAccents(e.target.value.trim()).toLowerCase();
    renderTenants(q ? allTenants.filter((t) => stripAccents(t.name || '').toLowerCase().includes(q)) : allTenants);
  });

  loadTenants();
})();
