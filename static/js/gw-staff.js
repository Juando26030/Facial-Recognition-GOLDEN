/* Usuarios del personal (templates/staff.html). Mismas rutas /api/staff* y mismos permisos de siempre; el servidor valida todo. Tarjetas por cuenta, delegación de eventos (sin onclick en línea),
   GW.busy en cada botón que hace una petición y confirmación con showConfirm antes de desactivar, cambiar rol o borrar. */
(function () {
  'use strict';
  const root = document.getElementById('staffRoot');
  if (!root) return;
  const staffRole = root.dataset.staffRole || '';
  const staffUsername = root.dataset.staffUsername || '';
  const ICONS = root.dataset.icons || '';
  const listEl = document.getElementById('staffBody');
  const isAdminPlus = staffRole === 'admin' || staffRole === 'super_admin';
  let showArchived = false;          // «Ver archivados» (admin+): Fase 3, archivar en vez de borrar

  if (staffRole === 'super_admin') document.getElementById('roleSelect').insertAdjacentHTML('beforeend', '<option value="admin">Admin</option>');

  // Debe reflejar DELETABLE_ROLES_BY en app/routers/staff.py: solo para no mostrar un botón que el backend va a rechazar; el permiso real siempre lo valida el servidor.
  const DELETABLE_ROLES = {
    coordinador: ['digitador'],
    admin: ['comercial', 'coordinador', 'digitador', 'cliente'],
    super_admin: ['admin', 'comercial', 'coordinador', 'digitador', 'cliente'],
  }[staffRole] || [];
  // Doble rol coordinador+comercial (Sprint 2.4 Fase 15, 2026-09-17): lo hace el administrador. Solo admite este único par, en cualquier orden.
  const DUAL_ROLE_PAIR = { coordinador: 'comercial', comercial: 'coordinador' };
  const ROLE_LABELS = { coordinador: 'Coordinador', comercial: 'Comercial', admin: 'Admin', super_admin: 'Super admin', digitador: 'Digitador', cliente: 'Cliente' };
  const roleLabel = (r) => ROLE_LABELS[r] || r;

  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icon = (name, cls) => '<svg class="gw-icon ' + (cls || '') + '" aria-hidden="true"><use href="' + esc(ICONS) + '#i-' + name + '"/></svg>';
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));
  const apiError = async (res, fallback) => { const d = await res.json().catch(() => ({})); return typeof d.detail === 'string' ? d.detail : fallback; };

  /* ---------------------------------------------------------------- Lista */
  async function loadStaff() {
    listEl.setAttribute('aria-busy', 'true');
    try {
      const res = await fetch('/api/staff' + (showArchived && isAdminPlus ? '?include_archived=true' : ''));
      if (!res.ok) throw new Error('http');
      render(await res.json());
    } catch (e) {
      listEl.innerHTML = '<div class="gw-alert gw-alert--err" role="alert">' + icon('error') + '<div class="gw-alert__body">No se pudieron cargar las cuentas. Revisa la conexión e inténtalo de nuevo.</div>' +
        '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-staff-action="reload">Reintentar</button></div>';
    } finally { listEl.removeAttribute('aria-busy'); }
  }

  function actionsHtml(s) {
    if (s.archived) {
      if (!isAdminPlus || s.username === staffUsername) return '<p class="gw-hint">Cuenta archivada.</p>';
      const a = `data-id="${esc(s.id)}" data-username="${esc(s.username)}"`;
      let html = `<button type="button" class="gw-btn gw-btn--primary" data-staff-action="restore" ${a}>${icon('undo', 'gw-icon--sm')}<span>Restaurar</span></button>`;
      if (staffRole === 'super_admin' && s.role !== 'super_admin') html += ` <button type="button" class="gw-btn gw-btn--danger-outline" data-staff-action="delete" ${a}>${icon('trash', 'gw-icon--sm')}<span>Eliminar definitivamente</span></button>`;
      return html;
    }
    if (s.role === 'super_admin' || s.username === staffUsername) return '<p class="gw-hint">Sin acciones disponibles para esta cuenta.</p>';
    const otherRole = DUAL_ROLE_PAIR[s.role];
    const attrs = (action, extra) => `data-staff-action="${action}" data-id="${esc(s.id)}" data-username="${esc(s.username)}" ${extra || ''}`;
    const btn = (action, label, ico, cls, extra) => `<button type="button" class="gw-btn ${cls || 'gw-btn--secondary'}" ${attrs(action, extra)}>${ico ? icon(ico, 'gw-icon--sm') : ''}<span>${label}</span></button>`;
    const item = (action, label, ico, extra, danger) => `<button type="button" class="gw-menu__item${danger ? ' gw-menu__item--danger' : ''}" role="menuitem" ${attrs(action, extra)}>${icon(ico, 'gw-icon--sm')}<span>${label}</span></button>`;
    const parts = [];
    const more = [];
    // A la vista lo de todos los días (restablecer contraseña, desactivar/reactivar); lo poco usado y lo irreversible va en el menú «Más acciones».
    if (DELETABLE_ROLES.includes(s.role)) parts.push(btn('reset', 'Restablecer contraseña', 'lock'));
    parts.push(s.is_active ? btn('deactivate', 'Desactivar', 'eye-off', 'gw-btn--danger-outline') : btn('activate', 'Reactivar', 'check', 'gw-btn--ok'));
    if (isAdminPlus && otherRole) {
      more.push(s.secondary_role
        ? item('secondary', `Quitar «${esc(roleLabel(otherRole))}»`, 'close', 'data-value=""')
        : item('secondary', `También ${esc(roleLabel(otherRole))}`, 'plus', `data-value="${esc(otherRole)}"`));
    }
    if (isAdminPlus && ['coordinador', 'comercial', 'admin'].includes(s.role)) more.push(item('role', 'Cambiar rol', 'user-plus', `data-current="${esc(s.role)}"`));
    if (isAdminPlus && DELETABLE_ROLES.includes(s.role)) more.push(item('archive', 'Archivar cuenta', 'lock', ''));          // el borrado definitivo vive en «Ver archivados» (solo super_admin)
    if (more.length) parts.push(`<div class="gw-menu gw-staff__more"><button type="button" class="gw-btn gw-btn--secondary gw-menu__btn" data-staff-menu aria-haspopup="true" aria-expanded="false" aria-label="Más acciones de ${esc(s.username)}">${icon('more')}</button><div class="gw-menu__panel" role="menu" hidden>${more.join('')}</div></div>`);
    return parts.join('');
  }

  function render(list) {
    if (!list.length) {
      listEl.innerHTML = showArchived
        ? '<div class="gw-empty" role="status"><p><strong>No hay cuentas archivadas</strong></p><p>Cuando archives una, aparecerá aquí para poder restaurarla.</p></div>'
        : '<div class="gw-empty" role="status"><p><strong>Todavía no hay cuentas de staff</strong></p><p>Abre «Nueva cuenta» arriba para crear la primera.</p></div>';
      return;
    }
    listEl.innerHTML = '<div class="gw-rows__head gw-staff__colhead" aria-hidden="true"><span>Usuario</span><span>Nombre<span class="gw-rows__alt"> y correo</span></span><span class="gw-rows__wide">Correo</span><span>Rol<span class="gw-rows__alt"> y estado</span></span><span class="gw-rows__wide">Estado</span><span>Acciones</span></div>' + list.map((s) => {
      const roles = s.secondary_role ? `${roleLabel(s.role)} + ${roleLabel(s.secondary_role)}` : roleLabel(s.role);
      return `
      <article class="gw-card-row gw-staff__row">
        <div class="gw-card-row__head gw-staff__head">
          <h3 class="gw-card-row__title gw-staff__who gw-staff__c-user" title="${esc(s.username)}">${esc(s.username)}</h3>
          <span class="gw-staff__c-state gw-badge ${s.archived ? '' : (s.is_active ? 'gw-badge--ok' : 'gw-badge--err')}">${icon(s.is_active && !s.archived ? 'check' : 'error')}${s.archived ? 'Archivada' : (s.is_active ? 'Activo' : 'Inactivo')}</span>
        </div>
        <p class="gw-card-row__meta gw-staff__c-name" title="${esc(s.full_name || '')}">${esc(s.full_name || 'Sin nombre')}</p>
        <p class="gw-card-row__meta gw-staff__mail gw-staff__c-mail"><span class="gw-staff__who">${s.email ? esc(s.email) : 'Sin correo'}</span>
          <button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-staff-action="email" data-id="${esc(s.id)}" data-current="${esc(s.email || '')}" aria-label="Editar el correo de ${esc(s.username)}">${icon('edit', 'gw-icon--sm')}</button></p>
        <p class="gw-staff__c-role"><span class="gw-badge gw-badge--info">${esc(roles)}</span></p>
        <div class="gw-card-row__actions gw-staff__actions gw-staff__c-act">${actionsHtml(s)}</div>
      </article>`;
    }).join('');
  }

  /* ---------------------------------------------------------------- Acciones */
  async function editEmail(btn) {
    const email = await showPrompt('Correo de esta cuenta (vacío para quitarlo):', { defaultValue: btn.dataset.current, confirmLabel: 'Guardar' });
    if (email === null) return;
    await busy(btn, async () => {
      const res = await fetch(`/api/staff/${btn.dataset.id}/email`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) });
      if (res.ok) { showToast('Correo actualizado', 'success'); loadStaff(); } else showToast(await apiError(res, 'No se pudo actualizar el correo'), 'error');
    });
  }

  async function setSecondaryRole(btn) {
    const secondaryRole = btn.dataset.value || null;
    if (!secondaryRole && !(await showConfirm(`¿Quitarle el segundo rol a "${esc(btn.dataset.username)}"? Perderá los permisos que ese rol le daba.`, { confirmLabel: 'Quitar rol' }))) return;
    await busy(btn, async () => {
      const res = await fetch(`/api/staff/${btn.dataset.id}/secondary-role`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ secondary_role: secondaryRole }) });
      if (res.ok) { loadStaff(); showToast(secondaryRole ? `Ahora también es ${roleLabel(secondaryRole)}` : 'Rol secundario quitado', 'success'); }
      else showToast(await apiError(res, 'No se pudo actualizar'), 'error');
    });
  }

  // Cambio de rol: una lista con los roles permitidos (en vez de escribirlo) y un cuadro que dice a quién y de qué a qué.
  function changeRole(btn) {
    const allowed = staffRole === 'super_admin' ? ['coordinador', 'comercial', 'admin'] : ['coordinador', 'comercial'];
    const current = btn.dataset.current;
    const username = btn.dataset.username;
    const options = allowed.map((r) => `<option value="${r}" ${r === current ? 'selected' : ''}>${roleLabel(r)}</option>`).join('');
    const d = openGwDialog({
      title: 'Cambiar rol',
      bodyHtml: `<p class="gw-modal__text">Cuenta <strong>${esc(username)}</strong>: hoy es <strong>${esc(roleLabel(current))}</strong>. Elige el nuevo rol; sus permisos cambian en cuanto lo confirmes.</p>` +
        '<div class="gw-field"><label class="gw-label" for="staffNewRole">Nuevo rol</label><select class="gw-select" id="staffNewRole">' + options + '</select></div>',
      buttons: [{ id: 'staffRoleCancel', cls: 'gw-btn--secondary', label: 'Cancelar' }, { id: 'staffRoleOk', cls: 'gw-btn--primary', label: 'Cambiar rol' }],
      onEscape: () => d.close(),
    });
    d.dlg.querySelector('#staffRoleCancel').addEventListener('click', () => d.close());
    const ok = d.dlg.querySelector('#staffRoleOk');
    ok.addEventListener('click', () => {
      const role = d.dlg.querySelector('#staffNewRole').value;
      if (role === current) { d.close(); return; }
      d.close();
      showConfirm(`¿Cambiar el rol de "${esc(username)}" de ${esc(roleLabel(current))} a ${esc(roleLabel(role))}? Perderá de inmediato los permisos propios de ${esc(roleLabel(current))}.`, { confirmLabel: 'Sí, cambiar rol' }).then((yes) => { if (yes) applyRole(btn, role); });
    });
    d.dlg.querySelector('#staffNewRole').focus();
  }

  function applyRole(btn, role) {
      busy(btn, async () => {
        const res = await fetch(`/api/staff/${btn.dataset.id}/role`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }) });
        if (res.ok) { loadStaff(); showToast('Rol actualizado', 'success'); } else showToast(await apiError(res, 'No se pudo cambiar el rol'), 'error');
      });
  }

  async function resetPassword(btn) {
    const pwd = await showPrompt(`Contraseña temporal para "${esc(btn.dataset.username)}" (mínimo 10 caracteres, con letras y números). Al ingresar, tendrá que elegir la suya:`, { confirmLabel: 'Restablecer' });
    if (pwd === null) return;
    await busy(btn, async () => {
      const res = await fetch(`/api/staff/${btn.dataset.id}/password`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_password: pwd, must_change: true }) });
      const data = await res.json().catch(() => ({}));
      if (res.ok) showToast(data.message || 'Contraseña restablecida', 'success'); else showToast(typeof data.detail === 'string' ? data.detail : 'No se pudo restablecer', 'error');
    });
  }

  async function toggleStaff(btn, activate) {
    if (!activate && !(await showConfirm(`¿Desactivar la cuenta "${escapeHtml(btn.dataset.username)}"? No podrá iniciar sesión hasta que la reactives; no se borra nada.`, { confirmLabel: 'Desactivar' }))) return;
    await busy(btn, async () => {
      const res = await fetch(`/api/staff/${btn.dataset.id}/${activate ? 'activate' : 'deactivate'}`, { method: 'PATCH' });
      await loadStaff();
      showToast(res.ok ? (activate ? 'Cuenta reactivada' : 'Cuenta desactivada') : 'No se pudo actualizar', res.ok ? 'success' : 'error');
    });
  }

  async function archiveStaff(btn) {
    if (!(await showConfirm(`¿Archivar la cuenta "${escapeHtml(btn.dataset.username)}"?<br><br>No podrá iniciar sesión y dejará de aparecer en las listas. <strong>No se borra nada</strong>: un administrador puede restaurarla cuando quiera.`, { confirmLabel: 'Archivar' }))) return;
    await busy(btn, async () => {
      const res = await fetch(`/api/staff/${btn.dataset.id}/archive`, { method: 'POST' });
      if (res.ok) { loadStaff(); showToast('Cuenta archivada', 'success'); } else showToast(await apiError(res, 'No se pudo archivar'), 'error');
    });
  }

  async function restoreStaff(btn) {
    await busy(btn, async () => {
      const res = await fetch(`/api/staff/${btn.dataset.id}/restore`, { method: 'POST' });
      if (res.ok) { loadStaff(); showToast('Cuenta restaurada. Sigue desactivada: reactívala para que pueda ingresar.', 'success'); } else showToast(await apiError(res, 'No se pudo restaurar'), 'error');
    });
  }

  async function deleteStaff(btn) {
    if (!(await showConfirm(`¿Eliminar DEFINITIVAMENTE la cuenta de "${escapeHtml(btn.dataset.username)}"?<br><br>Solo se puede si no tiene eventos asignados. Esta acción es permanente, no se puede deshacer y queda registrada.`, { confirmLabel: 'Eliminar definitivamente' }))) return;
    await busy(btn, async () => {
      const res = await fetch(`/api/staff/${btn.dataset.id}`, { method: 'DELETE' });
      if (res.ok) { loadStaff(); showToast('Cuenta eliminada', 'success'); } else showToast(await apiError(res, 'No se pudo eliminar'), 'error');
    });
  }

  // Acción principal: «Crear usuario» abre el formulario y deja el cursor en el primer campo.
  document.addEventListener('click', (e) => {
    const go = e.target.closest('[data-open-group]');
    const grp = go && document.getElementById(go.getAttribute('data-open-group'));
    if (!grp) return;
    grp.open = true;
    grp.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const first = grp.querySelector('input:not([type="hidden"])');
    if (first) first.focus({ preventScroll: true });
  });

  // Menú «Más acciones»: se abre y cierra aquí (clic afuera, Escape o al elegir una acción).
  function closeMenus(except) {
    listEl.querySelectorAll('.gw-staff__more').forEach((m) => {
      if (m === except) return;
      const panel = m.querySelector('.gw-menu__panel'), tog = m.querySelector('[data-staff-menu]');
      if (panel) panel.hidden = true;
      if (tog) tog.setAttribute('aria-expanded', 'false');
    });
  }
  document.addEventListener('click', (e) => { if (!e.target.closest('.gw-staff__more')) closeMenus(null); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenus(null); });

  listEl.addEventListener('click', (e) => {
    const tog = e.target.closest('[data-staff-menu]');
    if (tog) {
      const wrap = tog.closest('.gw-staff__more'), panel = wrap.querySelector('.gw-menu__panel'), open = panel.hidden;
      closeMenus(wrap);
      panel.hidden = !open;
      tog.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open && panel.firstElementChild) panel.firstElementChild.focus();
      return;
    }
    const btn = e.target.closest('[data-staff-action]');
    if (!btn) return;
    if (btn.closest('.gw-staff__more')) closeMenus(null);
    const action = btn.dataset.staffAction;
    if (action === 'reload') loadStaff();
    else if (action === 'email') editEmail(btn);
    else if (action === 'secondary') setSecondaryRole(btn);
    else if (action === 'role') changeRole(btn);
    else if (action === 'reset') resetPassword(btn);
    else if (action === 'deactivate') toggleStaff(btn, false);
    else if (action === 'activate') toggleStaff(btn, true);
    else if (action === 'archive') archiveStaff(btn);
    else if (action === 'restore') restoreStaff(btn);
    else if (action === 'delete') deleteStaff(btn);
  });

  /* ---------------------------------------------------------------- Crear cuenta */
  document.getElementById('newStaffForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const payload = Object.fromEntries(new FormData(form).entries());
    await busy(document.getElementById('newStaffSubmit'), async () => {
      const res = await fetch('/api/staff', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (res.ok) {
        form.reset();
        const group = document.getElementById('newStaffGroup');
        if (group) group.open = false;
        loadStaff();
        showToast('Cuenta creada', 'success');
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(typeof err.detail === 'string' ? err.detail : 'Revisa los datos: falta algún campo o no es válido', 'error');
      }
    });
  });

  const archToggle = document.getElementById('showArchivedStaff');
  if (archToggle) archToggle.addEventListener('change', () => { showArchived = archToggle.checked; loadStaff(); });

  loadStaff();
})();
