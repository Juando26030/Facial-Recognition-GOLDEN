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
  const canEdit = ['comercial', 'admin', 'super_admin'].includes(role);          // Fase 3: crea y edita comercial+; archiva admin+; borrado definitivo solo super_admin
  let showArchived = false;                                                      // «Ver archivados» (admin+)
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
      const res = await fetch('/api/tenants' + (showArchived && isAdmin ? '?include_archived=true' : ''));
      if (!res.ok) throw new Error('http');
      allTenants = await res.json();
      renderTenants(allTenants);
    } catch (e) {
      listEl.innerHTML = errorBox('No se pudieron cargar los clientes. Revisa la conexión e inténtalo de nuevo.', 'tenants');
    } finally { listEl.removeAttribute('aria-busy'); }
  }

  function renderTenants(list) {
    if (!allTenants.length) { listEl.innerHTML = showArchived ? emptyBox('No hay clientes archivados', 'Cuando archives uno, aparecerá aquí para poder restaurarlo.') : emptyBox('Todavía no hay clientes', role === 'coordinador' ? 'Cuando un administrador cree una cuenta, aparecerá aquí.' : 'Crea el primero con «Nuevo cliente/cuenta».'); return; }
    if (!list.length) { listEl.innerHTML = emptyBox('Sin resultados', 'Ningún cliente coincide con la búsqueda. Prueba con otra parte del nombre.'); return; }
    listEl.innerHTML = list.map((t) => `
      <article class="gw-card-row tenant-card" data-tenant-id="${esc(t.id)}">
        <button type="button" class="gw-tenant__head" data-action="toggle-tenant" aria-expanded="false" aria-controls="tenantBody${esc(t.id)}">
          <span>
            <span class="gw-card-row__title">${esc(t.name)} <span class="gw-tenant__code">#${esc(t.client_code)}</span>${t.archived ? ' <span class="gw-badge">Archivado</span>' : ''}</span>
            <span class="gw-card-row__meta">${esc(t.contact_name) || 'Sin contacto'}${t.contact_phone ? ' · ' + esc(t.contact_phone) : ''}</span>
          </span>
          <span class="gw-tenant__toggle">Ver eventos ${icon('chevron', 'gw-icon--sm')}</span>
        </button>
        ${canCreate && !t.archived ? `<a href="/clientes/${esc(t.id)}/nuevo-evento" class="gw-btn gw-btn--primary gw-btn--xl p-cli__new">${icon('plus')} Nuevo evento</a>` : ''}
        <div class="gw-tenant__body" id="tenantBody${esc(t.id)}" data-tenant-body hidden>
          ${tenantAdminHtml(t)}
          ${isSuper && !t.archived ? `<div class="gw-card-row__actions"><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-import-event data-tenant-id="${esc(t.id)}" data-tenant-name="${esc(t.name)}" title="Crear un evento nuevo de este cliente a partir de un paquete exportado de otro entorno">${icon('upload', 'gw-icon--sm')} Importar evento</button></div>` : ''}
          <div class="gw-field">
            <label class="gw-label" for="evSearch${esc(t.id)}">Buscar evento de este cliente/cuenta</label>
            <input type="search" class="gw-input" id="evSearch${esc(t.id)}" data-events-search placeholder="Buscar evento de este cliente/cuenta..." autocomplete="off">
          </div>
          ${isAdmin ? '<label class="gw-check"><input type="checkbox" data-show-archived-events> Ver eventos archivados</label>' : ''}
          <div data-events-container aria-live="polite"></div>
        </div>
      </article>`).join('');
  }

  // Datos del cliente (comercial+) y archivar / restaurar / borrar definitivo (admin+ / super_admin). Todo por delegación de eventos.
  function tenantAdminHtml(t) {
    const id = esc(t.id);
    const editForm = canEdit && !t.archived ? `<details class="gw-group"><summary class="gw-group__sum">${icon('edit', 'gw-icon--sm')} Editar datos del cliente</summary><div class="gw-group__body">
      <form class="gw-stack" data-edit-tenant="${id}">
        <div class="gw-field"><label class="gw-label" for="etName${id}">Nombre del cliente/cuenta</label><input class="gw-input" id="etName${id}" name="name" required value="${esc(t.name)}"></div>
        <div class="gw-fields-row gw-fields-row--3">
          <div class="gw-field gw-field--grow"><label class="gw-label" for="etCn${id}">Contacto - Nombre</label><input class="gw-input" id="etCn${id}" name="contact_name" value="${esc(t.contact_name)}"></div>
          <div class="gw-field gw-field--grow"><label class="gw-label" for="etCp${id}">Contacto - Teléfono</label><input class="gw-input" id="etCp${id}" name="contact_phone" inputmode="tel" value="${esc(t.contact_phone)}"></div>
          <div class="gw-field gw-field--grow"><label class="gw-label" for="etCe${id}">Contacto - Correo</label><input class="gw-input" id="etCe${id}" name="contact_email" type="email" value="${esc(t.contact_email)}"></div>
        </div>
        <div class="gw-actions"><button type="submit" class="gw-btn gw-btn--primary gw-btn--sm">Guardar cambios</button></div>
      </form></div></details>` : '';
    let actions = '';
    if (isAdmin) {
      actions = t.archived
        ? `<button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-restore-tenant="${id}" data-tenant-name="${esc(t.name)}">${icon('undo', 'gw-icon--sm')} Restaurar</button>`
        : `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-archive-tenant="${id}" data-tenant-name="${esc(t.name)}" title="Lo oculta de las listas; no borra nada y se puede restaurar">${icon('lock', 'gw-icon--sm')} Archivar cliente</button>`;
      if (isSuper && t.archived) actions += ` <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-purge-tenant="${id}" data-tenant-name="${esc(t.name)}">${icon('trash', 'gw-icon--sm')} Eliminar definitivamente</button>`;
    }
    return editForm + (actions ? `<div class="gw-card-row__actions">${actions}</div>` : '');
  }

  async function tenantCall(url, method, body) {
    const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    let detail = '';
    if (!res.ok) { try { detail = (await res.json()).detail || ''; } catch (e) { detail = ''; } }
    return { ok: res.ok, detail };
  }

  /* ---------------------------------------------------------------- Eventos de un cliente */
  async function loadEventsForTenant(tenantId, card) {
    const el = card.querySelector('[data-events-container]');
    if (!tenantEventsCache.has(card)) el.innerHTML = '<div class="gw-skeleton gw-adm-skeleton" aria-hidden="true"></div><span class="gw-sr-only">Cargando eventos…</span>';
    try {
      const withArchived = isAdmin && card.querySelector('[data-show-archived-events]')?.checked;          // «Ver eventos archivados» (admin+)
      const res = await fetch('/api/events?tenant_id=' + encodeURIComponent(tenantId) + (withArchived ? '&include_archived=true' : ''));
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
    // Escritorio: cada evento es una fila delgada con columnas alineadas; el encabezado va dentro de la misma rejilla (gw-clientes en p-clientes.css). En celular no se ve.
    const head = '<div class="p-cli__cols" aria-hidden="true"><span class="p-cli__c1">Evento</span><span class="p-cli__c2">Lugar</span><span class="p-cli__c3">Fecha</span><span class="p-cli__c4">Equipo</span><span class="p-cli__c5">Estado</span><span class="p-cli__c6">Acciones</span></div>';
    el.innerHTML = '<div class="gw-event-list">' + head + events.map((e) => `
      <div class="gw-card-row gw-event-card">
        <div class="gw-card-row__head">
          <span class="gw-card-row__title" title="${esc(e.name)}${e.event_code ? ' (' + esc(e.event_code) + ')' : ''}">${window.reportBulbHtml ? `<span class="p-cli__rep p-cli__rep--full">${reportBulbHtml(e)}</span><span class="p-cli__rep p-cli__rep--dot">${reportBulbHtml(e, true)}</span>` : ''} <span class="p-cli__nm"><span class="p-cli__name">${esc(e.name)}</span> ${e.event_code ? `<span class="gw-event-code"><span class="p-cli__paren">(</span><span class="p-cli__pfx">Código: </span>${esc(e.event_code)}<span class="p-cli__paren">)</span></span>` : ''}</span></span>
          <span class="gw-badge ${STATUS_BADGE[e.status] || ''}">${esc(STATUS_LABELS[e.status] || e.status)}</span>${e.archived ? ' <span class="gw-badge">Archivado</span>' : ''}
        </div>
        <p class="gw-card-row__meta p-cli__meta"><span class="p-cli__loc" title="${esc([e.location, e.city].filter(Boolean).join(' · '))}">${esc(e.location) || ''}${e.city ? ' · ' + esc(e.city) : ''}</span><span class="p-cli__sep"> · </span><span class="p-cli__date"><span class="p-cli__pfx">Fecha: </span>${fmtDate(e.start_date)}</span><span class="p-cli__sep"> · </span><span class="p-cli__coord" title="Comercial: ${esc(e.commercial_name) || '-'} · Coordinador: ${esc(e.coordinator_name) || '-'}"><span class="ev-who"><span class="p-cli__pfx">Comercial: </span>${esc(e.commercial_name) || '-'}</span><span class="ev-who"><span class="p-cli__pfx">Coordinador: </span>${esc(e.coordinator_name) || '-'}</span></span></p>
        <div class="gw-card-row__actions p-cli__acts">
          <a class="gw-btn gw-btn--primary gw-btn--sm p-cli__act" href="/kiosk/${esc(e.id)}">${icon('home', 'gw-icon--sm')} Ingresar</a>
          ${e.archived ? '' : `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm p-cli__act" data-edit-event="${esc(e.id)}">${icon('edit', 'gw-icon--sm')} Editar</button>
          <select class="gw-select gw-select--auto p-cli__status" data-status-select data-event-id="${esc(e.id)}" aria-label="Estado de ${esc(e.name)}">
            ${Object.entries(STATUS_LABELS).map(([value, label]) => `<option value="${value}" ${value === e.status ? 'selected' : ''}>${label}</option>`).join('')}
          </select>`}
          ${isAdmin ? `<div class="gw-menu p-cli__more">
            <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm p-cli__morebtn" data-menu-toggle aria-expanded="false" aria-haspopup="true" aria-label="Más acciones de ${esc(e.name)}" title="Más acciones">${icon('more')}<span class="p-cli__morelbl">Más acciones</span></button>
            <div class="gw-menu__panel" role="group" hidden>
              ${e.status === 'en_proceso' ? `<button type="button" class="gw-menu__item" data-revert-event="${esc(e.id)}" title="Devolver el evento a Creado (no se borra nada)">${icon('undo', 'gw-icon--sm')} Devolver a Creado</button>` : ''}
              ${isSuper ? `<button type="button" class="gw-menu__item" data-export-event="${esc(e.id)}" data-event-name="${esc(e.name)}" title="Exportar el evento completo (paquete .zip)">${icon('download', 'gw-icon--sm')} Exportar</button>` : ''}
              ${eventArchiveItems(e)}
            </div>
          </div>` : ''}
        </div>
      </div>`).join('') + '</div>';
  }

  // Archivar (finalizados, admin+) · Restaurar (admin+; si lo archivó el Job a los 90 días, solo super_admin) · Eliminar definitivamente (super_admin, solo archivados).
  function eventArchiveItems(e) {
    const name = esc(e.name);
    if (!e.archived) {
      return e.status === 'finalizado'
        ? `<hr class="gw-menu__sep"><button type="button" class="gw-menu__item" data-archive-event="${esc(e.id)}" data-event-name="${name}" title="Lo oculta de las listas; no borra nada y se puede restaurar">${icon('lock', 'gw-icon--sm')} Archivar evento</button>`
        : '';
    }
    let items = '<hr class="gw-menu__sep">';
    if (!e.archived_auto || isSuper) items += `<button type="button" class="gw-menu__item" data-restore-event="${esc(e.id)}" data-event-name="${name}">${icon('undo', 'gw-icon--sm')} Restaurar evento</button>`;
    if (isSuper) items += `<button type="button" class="gw-menu__item gw-menu__item--danger" data-delete-event="${esc(e.id)}" data-event-name="${name}" data-event-status="${esc(e.status)}">${icon('trash', 'gw-icon--sm')} Eliminar definitivamente</button>`;
    return items;
  }

  /* ---------------------------------------------------------------- Acciones */
  async function setEventStatus(eventId, status, card) {
    const res = await fetch('/api/events/' + encodeURIComponent(eventId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
    loadEventsForTenant(card.dataset.tenantId, card);
    showToast(res.ok ? `Evento pasó a "${STATUS_LABELS[status]}"` : 'No se pudo actualizar el evento', res.ok ? 'success' : 'error');
  }

  async function deleteEvent(eventId, name, status, btn) {
    const confirmed = await showConfirm(
      `¿Eliminar DEFINITIVAMENTE el evento archivado "${escapeHtml(name)}"?<br><br>` +
      'Se borran sus personas, registros, formularios y archivos. Esta acción es permanente, no se puede deshacer y queda registrada.',
      { confirmLabel: 'Eliminar definitivamente' }
    );
    if (!confirmed) return;
    const card = btn.closest('.tenant-card');
    await busy(btn, async () => {
      const res = await fetch('/api/events/' + encodeURIComponent(eventId), { method: 'DELETE' });
      loadEventsForTenant(card.dataset.tenantId, card);
      let detail = '';
      if (!res.ok) { try { detail = (await res.json()).detail || ''; } catch (err) { detail = ''; } }
      showToast(res.ok ? 'Evento eliminado' : (detail || 'No se pudo eliminar el evento'), res.ok ? 'success' : 'error');
    });
  }

  // Menú «Más acciones» de cada evento: un solo menú abierto; se cierra al elegir, al tocar fuera o con Escape.
  function closeMenus(except) {
    listEl.querySelectorAll('.p-cli__more').forEach((m) => {
      if (m === except) return;
      const panel = m.querySelector('.gw-menu__panel');
      if (panel) panel.hidden = true;
      const t = m.querySelector('[data-menu-toggle]');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  }
  document.addEventListener('click', (e) => { if (!e.target.closest || !e.target.closest('.p-cli__more')) closeMenus(null); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenus(null); });

  listEl.addEventListener('click', async (e) => {
    const menuBtn = e.target.closest('[data-menu-toggle]');
    if (menuBtn) {
      const wrap = menuBtn.closest('.p-cli__more');
      const panel = wrap.querySelector('.gw-menu__panel');
      const open = panel.hidden;
      closeMenus(wrap);
      panel.hidden = !open;
      menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {                                           // si no cabe hacia abajo, se abre hacia arriba
        wrap.classList.remove('gw-menu--up');
        const r = panel.getBoundingClientRect();
        if (r.bottom > window.innerHeight && menuBtn.getBoundingClientRect().top > panel.offsetHeight) wrap.classList.add('gw-menu--up');
      }
      return;
    }
    if (e.target.closest('.gw-menu__item')) closeMenus(null);
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
    const arch = e.target.closest('[data-archive-tenant]');
    if (arch) {
      if (!await showConfirm('¿Archivar al cliente "' + escapeHtml(arch.dataset.tenantName) + '"?<br><br>Se oculta de las listas y no se le podrán crear eventos. <strong>No se borra nada</strong>: un administrador puede restaurarlo cuando quiera.', { confirmLabel: 'Archivar' })) return;
      await busy(arch, async () => { const r = await tenantCall('/api/tenants/' + encodeURIComponent(arch.dataset.archiveTenant) + '/archive', 'POST'); showToast(r.ok ? 'Cliente archivado' : (r.detail || 'No se pudo archivar'), r.ok ? 'success' : 'error'); if (r.ok) loadTenants(); });
      return;
    }
    const rest = e.target.closest('[data-restore-tenant]');
    if (rest) {
      await busy(rest, async () => { const r = await tenantCall('/api/tenants/' + encodeURIComponent(rest.dataset.restoreTenant) + '/restore', 'POST'); showToast(r.ok ? 'Cliente restaurado' : (r.detail || 'No se pudo restaurar'), r.ok ? 'success' : 'error'); if (r.ok) loadTenants(); });
      return;
    }
    const purge = e.target.closest('[data-purge-tenant]');
    if (purge) {
      if (!await showConfirm('¿Eliminar DEFINITIVAMENTE al cliente "' + escapeHtml(purge.dataset.tenantName) + '"?<br><br>Solo se puede si no tiene eventos. Esta acción es permanente, no se puede deshacer y queda registrada.', { confirmLabel: 'Eliminar definitivamente' })) return;
      await busy(purge, async () => { const r = await tenantCall('/api/tenants/' + encodeURIComponent(purge.dataset.purgeTenant), 'DELETE'); showToast(r.ok ? 'Cliente eliminado' : (r.detail || 'No se pudo eliminar'), r.ok ? 'success' : 'error'); if (r.ok) loadTenants(); });
      return;
    }
    const archEv = e.target.closest('[data-archive-event]');
    if (archEv) {
      if (!await showConfirm('¿Archivar el evento "' + escapeHtml(archEv.dataset.eventName) + '"?<br><br>Se oculta de las listas, queda de solo lectura y sus formularios públicos dejan de recibir inscripciones. <strong>No se borra nada</strong>: un administrador puede restaurarlo.', { confirmLabel: 'Archivar' })) return;
      const card = archEv.closest('.tenant-card');
      await busy(archEv, async () => { const r = await tenantCall('/api/events/' + encodeURIComponent(archEv.dataset.archiveEvent) + '/archive', 'POST'); showToast(r.ok ? 'Evento archivado' : (r.detail || 'No se pudo archivar'), r.ok ? 'success' : 'error'); if (r.ok) loadEventsForTenant(card.dataset.tenantId, card); });
      return;
    }
    const restEv = e.target.closest('[data-restore-event]');
    if (restEv) {
      const card = restEv.closest('.tenant-card');
      await busy(restEv, async () => { const r = await tenantCall('/api/events/' + encodeURIComponent(restEv.dataset.restoreEvent) + '/restore', 'POST'); showToast(r.ok ? 'Evento restaurado' : (r.detail || 'No se pudo restaurar'), r.ok ? 'success' : 'error'); if (r.ok) loadEventsForTenant(card.dataset.tenantId, card); });
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

  listEl.addEventListener('submit', async (e) => {
    const form = e.target.closest('[data-edit-tenant]');
    if (!form) return;
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    await busy(form.querySelector('button[type="submit"]'), async () => {
      const r = await tenantCall('/api/tenants/' + encodeURIComponent(form.dataset.editTenant), 'PATCH', payload);
      showToast(r.ok ? 'Datos del cliente guardados' : (r.detail || 'No se pudo guardar'), r.ok ? 'success' : 'error');
      if (r.ok) loadTenants();
    });
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
    const showArch = e.target.closest('[data-show-archived-events]');
    if (showArch) { const card = showArch.closest('.tenant-card'); loadEventsForTenant(card.dataset.tenantId, card); return; }
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

  const archToggle = document.getElementById('showArchived');
  if (archToggle) archToggle.addEventListener('change', () => { showArchived = archToggle.checked; loadTenants(); });

  loadTenants();
})();
