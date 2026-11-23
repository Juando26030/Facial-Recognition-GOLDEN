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
    admin: ['comercial', 'coordinador', 'almacen', 'contabilidad', 'digitador', 'cliente'],
    super_admin: ['admin', 'comercial', 'coordinador', 'almacen', 'contabilidad', 'digitador', 'cliente'],
  }[staffRole] || [];
  // Doble rol coordinador+comercial (Sprint 2.4 Fase 15, 2026-09-17): lo hace el administrador. Solo admite este único par, en cualquier orden.
  const ROLE_LABELS = { coordinador: 'Coordinador', comercial: 'Comercial', admin: 'Admin', super_admin: 'Super admin', digitador: 'Digitador', cliente: 'Cliente', almacen: 'Almacén', contabilidad: 'Contabilidad', dir_coordinadores: 'Director de coordinadores' };
  const roleLabel = (r) => ROLE_LABELS[r] || r;

  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icon = (name, cls) => '<svg class="gw-icon ' + (cls || '') + '" aria-hidden="true"><use href="' + esc(ICONS) + '#i-' + name + '"/></svg>';
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));
  const apiError = async (res, fallback) => { const d = await res.json().catch(() => ({})); return typeof d.detail === 'string' ? d.detail : fallback; };

  let staffList = [];          // la última lista cargada (el diálogo «Editar» lee de aquí)
  const staffById = (id) => staffList.find((x) => String(x.id) === String(id));

  /* ---------------------------------------------------------------- Lista */
  async function loadStaff() {
    listEl.setAttribute('aria-busy', 'true');
    try {
      const res = await fetch('/api/staff' + (showArchived && isAdminPlus ? '?include_archived=true' : ''));
      if (!res.ok) throw new Error('http');
      staffList = await res.json();
      render(staffList);
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
      if (isAdminPlus && s.role !== 'super_admin') html += ` <button type="button" class="gw-btn gw-btn--danger-outline" data-staff-action="delete" ${a}>${icon('trash', 'gw-icon--sm')}<span>Eliminar definitivamente</span></button>`;
      return html;
    }
    if (s.role === 'super_admin' || s.username === staffUsername) return '<p class="gw-hint">Sin acciones disponibles para esta cuenta.</p>';
    const attrs = (action, extra) => `data-staff-action="${action}" data-id="${esc(s.id)}" data-username="${esc(s.username)}" ${extra || ''}`;
    const btn = (action, label, ico, cls, extra) => `<button type="button" class="gw-btn ${cls || 'gw-btn--secondary'}" ${attrs(action, extra)}>${ico ? icon(ico, 'gw-icon--sm') : ''}<span>${label}</span></button>`;
    const item = (action, label, ico, extra, danger) => `<button type="button" class="gw-menu__item${danger ? ' gw-menu__item--danger' : ''}" role="menuitem" ${attrs(action, extra)}>${icon(ico, 'gw-icon--sm')}<span>${label}</span></button>`;
    const parts = [];
    const more = [];
    // A la vista lo de todos los días (restablecer contraseña, desactivar/reactivar); lo poco usado y lo irreversible va en el menú «Más acciones».
    if (DELETABLE_ROLES.includes(s.role) && !(window.LOCAL_SERVER || document.querySelector('meta[name="gw-local-server"]'))) parts.push(btn('reset', 'Restablecer contraseña', 'lock'));          // servidor local: las contraseñas solo se cambian en la nube
    parts.push(s.is_active ? btn('deactivate', 'Desactivar', 'eye-off', 'gw-btn--danger-outline') : btn('activate', 'Reactivar', 'check', 'gw-btn--ok'));
    if (isAdminPlus && ['coordinador', 'comercial', 'almacen', 'contabilidad', 'admin'].includes(s.role)) more.push(item('role', 'Cambiar rol o añadir roles', 'user-plus', `data-current="${esc(s.role)}" data-extras="${esc((s.extra_roles || []).join(','))}"`));
    if (isAdminPlus && DELETABLE_ROLES.includes(s.role)) more.push(item('delete', 'Eliminar cuenta', 'trash', '', true));          // 8-nov-2026: se elimina de verdad (para dejar sin acceso está «Desactivar»); nunca un super_admin
    if (more.length) parts.push(`<div class="gw-menu gw-staff__more"><button type="button" class="gw-btn gw-btn--secondary gw-menu__btn" data-staff-menu aria-haspopup="true" aria-expanded="false" aria-label="Más acciones de ${esc(s.username)}">${icon('more')}</button><div class="gw-menu__panel" role="menu" hidden>${more.join('')}</div></div>`);
    return parts.join('');
  }

  /* Buscador: se filtra mientras se escribe (sin tildes ni mayúsculas) por usuario, nombre, correo y rol. */
  const norm = (t) => String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const searchEl = document.getElementById('staffSearch');
  let searchTerm = '';
  const matches = (s) => !searchTerm || norm([s.username, s.full_name, s.email, [s.role].concat(s.extra_roles || []).map(roleLabel).join(' ')].join(' ')).includes(searchTerm);
  if (searchEl) searchEl.addEventListener('input', () => { searchTerm = norm(searchEl.value.trim()); render(staffList); });

  function render(all) {
    const list = all.filter(matches);
    if (!list.length) setLayout(false);          // avisos de «sin resultados / sin cuentas»: con el contenedor de filas de siempre
    if (all.length && !list.length) {
      listEl.innerHTML = '<div class="gw-empty" role="status"><p><strong>Ninguna cuenta coincide con «' + esc(searchEl ? searchEl.value.trim() : '') + '»</strong></p><p>Prueba con otra parte del nombre, el usuario o el correo.</p></div>';
      return;
    }
    if (!list.length) {
      listEl.innerHTML = showArchived
        ? '<div class="gw-empty" role="status"><p><strong>No hay cuentas archivadas</strong></p><p>Cuando archives una, aparecerá aquí para poder restaurarla.</p></div>'
        : '<div class="gw-empty" role="status"><p><strong>Todavía no hay cuentas de staff</strong></p><p>Abre «Nueva cuenta» arriba para crear la primera.</p></div>';
      return;
    }
    if (searchTerm) { setLayout(false); listEl.innerHTML = COLHEAD + list.map(rowHtml).join(''); return; }          // buscando: lista plana, solo quien coincide
    // Sin búsqueda: un panel desplegable por rol; quien tiene doble rol sale en los dos (principal + extras).
    setLayout(true);
    const rolesOf = (s) => [s.role].concat(s.extra_roles || (s.secondary_role ? [s.secondary_role] : [])).filter(Boolean);
    const present = [];
    list.forEach((s) => rolesOf(s).forEach((r) => { if (present.indexOf(r) < 0) present.push(r); }));
    const ordered = GROUP_ORDER.filter((r) => present.indexOf(r) >= 0).concat(present.filter((r) => GROUP_ORDER.indexOf(r) < 0));
    listEl.innerHTML = ordered.map((r) => {
      const members = list.filter((s) => rolesOf(s).indexOf(r) >= 0);
      return `<details class="gw-group gw-staff__group" data-role="${esc(r)}"${openGroups.has(r) ? ' open' : ''}>
        <summary class="gw-group__sum"><span class="gw-group__title">${esc(GROUP_LABELS[r] || roleLabel(r))}</span><span class="gw-badge gw-badge--info">${members.length}</span></summary>
        <div class="gw-group__body"><div class="gw-cards gw-rows gw-staff__list">${COLHEAD}${members.map(rowHtml).join('')}</div></div>
      </details>`;
    }).join('');
  }

  const COLHEAD = '<div class="gw-rows__head gw-staff__colhead" aria-hidden="true"><span>Usuario</span><span>Nombre<span class="gw-rows__alt"> y correo</span></span><span class="gw-rows__wide">Correo</span><span>Rol<span class="gw-rows__alt"> y estado</span></span><span class="gw-rows__wide">Estado</span><span>Acciones</span></div>';
  const GROUP_ORDER = ['super_admin', 'admin', 'comercial', 'dir_coordinadores', 'coordinador', 'contabilidad', 'almacen', 'digitador', 'cliente'];
  const GROUP_LABELS = { super_admin: 'Super administradores', admin: 'Administradores', comercial: 'Comerciales', dir_coordinadores: 'Directores de coordinadores', coordinador: 'Coordinadores', contabilidad: 'Contabilidad', almacen: 'Almacén', digitador: 'Digitadores', cliente: 'Clientes' };
  const openGroups = new Set();          // paneles que la persona dejó abiertos (se conservan al recargar o al cambiar algo)
  listEl.addEventListener('toggle', (e) => { const d = e.target; if (d && d.matches && d.matches('details.gw-staff__group')) { if (d.open) openGroups.add(d.dataset.role); else openGroups.delete(d.dataset.role); } }, true);
  /* En vista agrupada el contenedor deja de ser la rejilla de filas (cada panel trae la suya); buscando, vuelve a serlo. */
  function setLayout(grouped) { ['gw-cards', 'gw-rows', 'gw-staff__list'].forEach((c) => listEl.classList.toggle(c, !grouped)); }

  function rowHtml(s) {
    const roles = [s.role].concat(s.extra_roles || (s.secondary_role ? [s.secondary_role] : [])).map(roleLabel).join(' + ');
    return `
      <article class="gw-card-row gw-staff__row">
        <div class="gw-card-row__head gw-staff__head">
          <h3 class="gw-card-row__title gw-staff__who gw-staff__c-user" title="${esc(s.username)}">${esc(s.username)}</h3>
          <span class="gw-staff__c-state gw-badge ${s.archived ? '' : (s.is_active ? 'gw-badge--ok' : 'gw-badge--err')}">${icon(s.is_active && !s.archived ? 'check' : 'error')}${s.archived ? 'Archivada' : (s.is_active ? 'Activo' : 'Inactivo')}</span>
        </div>
        <p class="gw-card-row__meta gw-staff__c-name" title="${esc(s.full_name || '')}">${esc(s.full_name || 'Sin nombre')}</p>
        <p class="gw-card-row__meta gw-staff__mail gw-staff__c-mail"><span class="gw-staff__who">${s.email ? esc(s.email) : 'Sin correo'}</span>
          <button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-staff-action="profile" data-id="${esc(s.id)}" aria-label="Editar el perfil de ${esc(s.username)}">${icon('edit', 'gw-icon--sm')}</button></p>
        <p class="gw-staff__c-role"><span class="gw-badge gw-badge--info">${esc(roles)}</span></p>
        <div class="gw-card-row__actions gw-staff__actions gw-staff__c-act">${actionsHtml(s)}</div>
      </article>`;
  }

  /* ---------------------------------------------------------------- Acciones */
  // «Editar»: usuario, nombre, correo y celular de la cuenta en un solo cuadro (8-nov-2026).
  function editProfile(btn) {
    const s = staffById(btn.dataset.id);
    if (!s) return;
    const own = s.username === staffUsername;
    const field = (id, label, value, extra) => `<div class="gw-field"><label class="gw-label" for="${id}">${label}</label><input class="gw-input" id="${id}" value="${esc(value || '')}" ${extra || ''}></div>`;
    const d = openGwDialog({
      title: 'Editar cuenta',
      bodyHtml: '<form id="staffProfileForm" novalidate>' +
        field('pfUser', 'Usuario', s.username, own ? 'disabled' : 'maxlength="64" autocomplete="off"') +
        (own ? '' : '<p class="gw-hint">Si cambias el usuario, a esa persona se le cierra la sesión y debe entrar con el nuevo.</p>') +
        field('pfName', 'Nombre completo', s.full_name, 'maxlength="120" autocomplete="off"') +
        field('pfMail', 'Correo', s.email, 'type="email" maxlength="120" autocomplete="off"') +
        field('pfPhone', 'Celular', s.phone, 'inputmode="tel" maxlength="30" autocomplete="off"') + '</form>',
      buttons: [{ id: 'pfCancel', cls: 'gw-btn--secondary', label: 'Cancelar' }, { id: 'pfOk', cls: 'gw-btn--primary', label: 'Guardar' }],
      onEscape: () => d.close(),
    });
    const q = (sel) => d.dlg.querySelector(sel);
    q('#pfCancel').addEventListener('click', () => d.close());
    q('#pfOk').addEventListener('click', () => busy(q('#pfOk'), async () => {
      const body = { full_name: q('#pfName').value, email: q('#pfMail').value, phone: q('#pfPhone').value };
      if (!own) body.username = q('#pfUser').value;
      const res = await fetch(`/api/staff/${s.id}/profile`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (res.ok) { d.close(); showToast('Cuenta actualizada', 'success'); loadStaff(); } else showToast(await apiError(res, 'No se pudo guardar'), 'error');
    }));
    q('#pfName').focus();
  }

  // Roles de la cuenta: el principal (lista) y debajo «Añadir roles» (casillas): una persona puede tener uno, dos o más; sus permisos son la suma. «Admin» como rol extra solo lo da el Super Admin.
  function changeRole(btn) {
    const allowed = staffRole === 'super_admin' ? ['coordinador', 'comercial', 'almacen', 'contabilidad', 'admin'] : ['coordinador', 'comercial', 'almacen', 'contabilidad'];
    const current = btn.dataset.current;
    const username = btn.dataset.username;
    const currentExtras = (btn.dataset.extras || '').split(',').filter(Boolean);
    const options = allowed.map((r) => `<option value="${r}" ${r === current ? 'selected' : ''}>${roleLabel(r)}</option>`).join('');
    const extraChoices = ['coordinador', 'comercial', 'almacen', 'contabilidad', 'dir_coordinadores'].concat(staffRole === 'super_admin' ? ['admin'] : []);          // Almacén y Contabilidad: rol principal o sumados (inventario)
    const d = openGwDialog({
      title: 'Roles de la cuenta',
      bodyHtml: `<p class="gw-modal__text">Cuenta <strong>${esc(username)}</strong>. Los permisos cambian en cuanto confirmes; si tiene varios roles, recibe la suma de todos.</p>` +
        '<div class="gw-field"><label class="gw-label" for="staffNewRole">Rol principal</label><select class="gw-select" id="staffNewRole">' + options + '</select></div>' +
        '<fieldset class="gw-field" id="staffExtraBox"><legend class="gw-label">Añadir roles</legend>' +
        extraChoices.map((r) => `<label class="gw-check" data-extra-row="${r}"><input type="checkbox" value="${r}" ${currentExtras.includes(r) ? 'checked' : ''}><span>${esc(roleLabel(r))}</span></label>`).join('') +
        '<p class="gw-hint">Director de coordinadores es un coordinador que además asigna coordinadores a los eventos y revisa las legalizaciones (requiere el rol Coordinador). Almacén puede ver y editar el inventario de los eventos; Contabilidad solo lo consulta. Ninguno de los dos administra cuentas ni ve datos de asistentes.</p></fieldset>',
      buttons: [{ id: 'staffRoleCancel', cls: 'gw-btn--secondary', label: 'Cancelar' }, { id: 'staffRoleOk', cls: 'gw-btn--primary', label: 'Guardar roles' }],
      onEscape: () => d.close(),
    });
    const sel = d.dlg.querySelector('#staffNewRole');
    const box = d.dlg.querySelector('#staffExtraBox');
    const syncBox = () => {          // el rol principal no se repite como extra; con «admin» como principal no hay extras
      box.hidden = sel.value === 'admin';
      const dirRow = box.querySelector('[data-extra-row="dir_coordinadores"]');          // el director es un coordinador: solo con ese rol (principal o sumado)
      const isCoord = sel.value === 'coordinador' || !!box.querySelector('[data-extra-row="coordinador"] input:checked');
      if (dirRow) { dirRow.hidden = !isCoord; if (!isCoord) dirRow.querySelector('input').checked = false; }
      box.querySelectorAll('[data-extra-row]').forEach((row) => {
        const same = row.dataset.extraRow === sel.value;
        row.hidden = same;
        if (same) row.querySelector('input').checked = false;
      });
    };
    sel.addEventListener('change', syncBox);
    box.addEventListener('change', syncBox);
    syncBox();
    d.dlg.querySelector('#staffRoleCancel').addEventListener('click', () => d.close());
    d.dlg.querySelector('#staffRoleOk').addEventListener('click', () => {
      const role = sel.value;
      const extras = role === 'admin' ? [] : Array.from(box.querySelectorAll('input:checked')).map((i) => i.value);
      if (role === current && extras.slice().sort().join() === currentExtras.slice().sort().join()) { d.close(); return; }
      d.close();
      const txt = role === current
        ? `¿Dejar a "${esc(username)}" como ${esc(roleLabel(current))}${extras.length ? ' + ' + extras.map(roleLabel).map(esc).join(' + ') : ' solamente'}?`
        : `¿Cambiar el rol principal de "${esc(username)}" de ${esc(roleLabel(current))} a ${esc(roleLabel(role))}${extras.length ? ', más ' + extras.map(roleLabel).map(esc).join(' + ') : ''}? Perderá de inmediato los permisos que ya no le correspondan.`;
      showConfirm(txt, { confirmLabel: 'Sí, guardar' }).then((yes) => { if (yes) applyRoles(btn, role, current, extras); });
    });
    sel.focus();
  }

  function applyRoles(btn, role, current, extras) {
    busy(btn, async () => {
      if (role !== current) {
        const res = await fetch(`/api/staff/${btn.dataset.id}/role`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }) });
        if (!res.ok) { showToast(await apiError(res, 'No se pudo cambiar el rol'), 'error'); return; }
      }
      const res2 = await fetch(`/api/staff/${btn.dataset.id}/roles`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ extra_roles: extras }) });
      loadStaff();
      if (res2.ok) showToast('Roles actualizados', 'success'); else showToast(await apiError(res2, 'No se pudieron guardar los roles extra'), 'error');
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
    if (!(await showConfirm(`¿Eliminar DEFINITIVAMENTE la cuenta de "${escapeHtml(btn.dataset.username)}"?<br><br>Se borra de verdad: no se puede deshacer y queda registrado. No se puede si es coordinador o comercial de un evento. Si solo quieres que no entre, usa «Desactivar».`, { confirmLabel: 'Eliminar cuenta' }))) return;
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
    else if (action === 'profile') editProfile(btn);
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
