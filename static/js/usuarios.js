/* Usuarios del evento (/kiosk/{id}/usuarios): carga y acciones sobre las cuentas del evento. Delegación de eventos (sin onclick en línea).
   Las rutas, los permisos y los textos de confirmación son los de siempre; GW.busy da la rueda a los botones que hacen una petición. */
(function () {
    'use strict';
    const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const ROLES = { digitador: 'Digitador', cliente: 'Cliente', coordinador: 'Coordinador', comercial: 'Comercial', admin: 'Administrador', super_admin: 'Superadministrador' };
    const busy = (btn, work) => (window.GW && window.GW.busy ? window.GW.busy(btn, work) : Promise.resolve(work()));
    const tempForm = document.getElementById('tempUserForm');
    const assignForm = document.getElementById('assignExistingForm');
    const listEl = document.getElementById('tempUsersList');
    const statusEl = document.getElementById('tempUsersStatus');
    const eventId = window.EVENT_ID;
    const iconsScript = document.querySelector('script[data-icons]');
    const ICONS = (iconsScript && iconsScript.dataset.icons) || '/static/img/icons.svg';

    function setStatus(text, isErr) {
        statusEl.textContent = text || '';
        statusEl.classList.toggle('gw-msg--err', !!(text && isErr));
    }

    function cardHtml(u) {
        const rol = ROLES[u.role] || u.role;
        const nombre = u.full_name || 'Sin nombre';
        const estado = u.is_active ? '<span class="gw-badge gw-badge--ok">Activo</span>' : '<span class="gw-badge gw-badge--warn">Inactivo</span>';
        const reset = u.role === 'digitador'
            ? `<button type="button" class="gw-btn gw-btn--secondary" data-act="reset" data-id="${esc(u.id)}" data-username="${esc(u.username)}"><svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${esc(ICONS)}#i-lock"/></svg><span>Restablecer contraseña</span></button>` : '';
        return `<article class="gw-card-row gw-usr__row">
            <div class="gw-card-row__head gw-usr__head">
                <span class="gw-card-row__title gw-usr__c-user" title="${esc(u.username)}">${esc(u.username)}</span>
                <span class="gw-rowact gw-usr__badges"><span class="gw-badge gw-badge--info gw-usr__c-role">${esc(rol)}</span><span class="gw-usr__c-state">${estado}</span></span>
            </div>
            <p class="gw-card-row__meta gw-usr__c-name" title="${esc(u.full_name || '')}">${esc(nombre)}</p>
            <div class="gw-card-row__actions gw-usr__actions gw-usr__c-act">
                ${reset}
                <button type="button" class="gw-btn gw-btn--danger-outline" data-act="revoke" data-id="${esc(u.id)}"><svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${esc(ICONS)}#i-close"/></svg><span>Quitar de este evento</span></button>
                <div class="gw-menu gw-usr__more"><button type="button" class="gw-btn gw-btn--secondary gw-menu__btn" data-menu aria-haspopup="true" aria-expanded="false" aria-label="Más acciones de ${esc(u.username)}"><svg class="gw-icon" aria-hidden="true"><use href="${esc(ICONS)}#i-more"/></svg></button>
                    <div class="gw-menu__panel" role="menu" hidden><button type="button" class="gw-menu__item gw-menu__item--danger" role="menuitem" data-act="delete" data-id="${esc(u.id)}" data-username="${esc(u.username)}"><svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${esc(ICONS)}#i-trash"/></svg><span>Borrar permanente</span></button></div></div>
            </div>
        </article>`;
    }

    let allUsers = [], pageIdx = 0;
    const PAGER_KEY = 'usuarios';
    const pagerEl = document.getElementById('tempUsersPager');
    const purgeBtn = document.getElementById('purgeTempBtn');

    function drawUsers() {
        if (!allUsers.length) {
            listEl.innerHTML = '<div class="gw-empty" role="note"><p>Todavía no hay cuentas asignadas a este evento.</p><p class="gw-hint">Crea la primera con «Nueva cuenta para este evento» o sube un Excel.</p></div>';
            if (pagerEl) pagerEl.replaceChildren();
            if (purgeBtn) purgeBtn.hidden = true;
            return;
        }
        const pg = window.GW && window.GW.pageSlice ? window.GW.pageSlice(PAGER_KEY, allUsers, pageIdx) : { items: allUsers, page: 0 };
        pageIdx = pg.page;
        listEl.innerHTML = '<div class="gw-rows__head gw-usr__colhead" aria-hidden="true"><span>Usuario</span><span>Nombre</span><span>Rol</span><span>Estado</span><span>Acciones</span></div>' + pg.items.map(cardHtml).join('');
        if (pagerEl && window.GW && window.GW.pagerBar) {
            pagerEl.replaceChildren(window.GW.pagerBar({ key: PAGER_KEY, total: allUsers.length, page: pageIdx, onPage: (i) => { pageIdx = i; drawUsers(); }, onSize: () => { pageIdx = 0; drawUsers(); } }));
        }
        if (purgeBtn) purgeBtn.hidden = !allUsers.some((u) => u.role === 'digitador');
    }

    async function loadTempUsers() {
        listEl.setAttribute('aria-busy', 'true');
        try {
            const res = await fetch(`/api/events/${eventId}/staff-users`);
            if (!res.ok) throw new Error('http ' + res.status);
            allUsers = await res.json();
            setStatus('');
            drawUsers();
        } catch (e) {
            listEl.innerHTML = '';
            if (pagerEl) pagerEl.replaceChildren();
            setStatus('No se pudieron cargar las cuentas. Revisa la conexión y vuelve a intentar.', true);
            const retry = document.createElement('button');
            retry.type = 'button'; retry.className = 'gw-btn gw-btn--secondary gw-btn--sm'; retry.setAttribute('data-act', 'reload'); retry.textContent = 'Reintentar';
            listEl.appendChild(retry);
        } finally {
            listEl.removeAttribute('aria-busy');
        }
    }

    /* Combobox «Asignar cuenta ya existente»: escribir filtra por usuario, nombre y rol; el id elegido va en #assignableValue (lo que lee el envío). */
    const combo = { items: [], shown: [], active: -1 };
    const cInput = document.getElementById('assignableSelect');
    const cList = document.getElementById('assignableList');
    const cValue = document.getElementById('assignableValue');
    const norm = (v) => String(v == null ? '' : v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const comboLabel = (s) => `${s.username}${s.full_name ? ' - ' + s.full_name : ''} (${s.role})`;

    function comboOpen(open) {
        cList.hidden = !open;
        cInput.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (!open) { combo.active = -1; cInput.removeAttribute('aria-activedescendant'); }
    }
    function comboSetActive(i) {
        const opts = cList.querySelectorAll('[role="option"]');
        opts.forEach((o, k) => o.setAttribute('aria-selected', k === i ? 'true' : 'false'));
        combo.active = i;
        if (i >= 0 && opts[i]) { cInput.setAttribute('aria-activedescendant', opts[i].id); opts[i].scrollIntoView({ block: 'nearest' }); }
        else cInput.removeAttribute('aria-activedescendant');
    }
    function comboRender() {
        const q = norm(cInput.value).trim();
        combo.shown = combo.items.filter((s) => !q || norm(`${s.username} ${s.full_name || ''} ${s.role} ${ROLES[s.role] || ''}`).includes(q));
        cList.innerHTML = combo.shown.length
            ? combo.shown.map((s, i) => `<li role="option" id="assignableOpt${i}" class="gw-combo__opt" data-i="${i}" aria-selected="false">${esc(comboLabel(s))}</li>`).join('')
            : '<li class="gw-combo__empty" role="presentation">No hay usuarios que coincidan.</li>';
        comboSetActive(-1);
    }
    function comboPick(i) {
        const s = combo.shown[i];
        if (!s) return;
        cValue.value = s.id;
        cInput.value = comboLabel(s);
        comboOpen(false);
    }
    function comboInit() {
        cInput.addEventListener('input', () => { cValue.value = ''; comboRender(); comboOpen(true); });
        cInput.addEventListener('focus', () => { comboRender(); comboOpen(true); });
        cInput.addEventListener('keydown', (ev) => {
            const n = combo.shown.length;
            if (ev.key === 'ArrowDown') { ev.preventDefault(); if (cList.hidden) { comboRender(); comboOpen(true); } if (n) comboSetActive((combo.active + 1) % n); }
            else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (cList.hidden) { comboRender(); comboOpen(true); } if (n) comboSetActive(combo.active <= 0 ? n - 1 : combo.active - 1); }
            else if (ev.key === 'Enter') { if (!cList.hidden && combo.active >= 0) { ev.preventDefault(); comboPick(combo.active); } else if (!cList.hidden && n === 1 && cInput.value.trim()) { ev.preventDefault(); comboPick(0); } }
            else if (ev.key === 'Escape') { if (!cList.hidden) { ev.preventDefault(); comboOpen(false); } }
        });
        cList.addEventListener('mousedown', (ev) => ev.preventDefault());      // el clic no le quita el foco al campo
        cList.addEventListener('click', (ev) => { const o = ev.target.closest('[data-i]'); if (o) comboPick(Number(o.getAttribute('data-i'))); });
        document.addEventListener('click', (ev) => { if (!ev.target.closest('#assignableCombo')) comboOpen(false); });
        cInput.addEventListener('blur', () => comboOpen(false));
    }

    async function loadAssignableOptions() {
        if (!assignForm) return;
        const res = await fetch('/api/staff/assignable');
        const list = await res.json();
        combo.items = list.filter((s) => s.role !== 'cliente');          // las cuentas cliente de evento ya no se asignan: para eso están los enlaces con vencimiento
        comboInit();
    }

    async function errDetail(res, fallback) {
        const err = await res.json().catch(() => ({}));
        return typeof err.detail === 'string' ? err.detail : fallback;
    }

    tempForm.addEventListener('submit', (ev) => {
        ev.preventDefault();
        const form = ev.target;
        const btn = form.querySelector('[data-gw-submit]');
        const payload = Object.fromEntries(new FormData(form).entries());
        return busy(btn, async () => {
            const res = await fetch(`/api/events/${eventId}/staff-users`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
            });
            if (res.ok) { form.reset(); loadTempUsers(); showToast('Cuenta creada y asignada al evento', 'success'); }
            else showToast(await errDetail(res, 'Revisa los datos: falta algún campo o no es válido'), 'error');
        }).catch(() => showToast('No se pudo crear la cuenta. Revisa la conexión.', 'error'));
    });

    if (assignForm) {
        assignForm.addEventListener('submit', (ev) => {
            ev.preventDefault();
            const btn = assignForm.querySelector('button[type="submit"]');
            const staffId = cValue.value;
            if (!staffId) { showToast('Elige un usuario de la lista', 'error'); cInput.focus(); return null; }
            return busy(btn, async () => {
                const res = await fetch(`/api/events/${eventId}/staff-users/assign-existing`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ staff_id: Number(staffId) }),
                });
                if (res.ok) { cValue.value = ''; cInput.value = ''; loadTempUsers(); showToast('Cuenta asignada al evento', 'success'); }
                else { const err = await res.json().catch(() => ({})); showToast(err.detail || 'No se pudo asignar', 'error'); }
            }).catch(() => showToast('No se pudo asignar. Revisa la conexión.', 'error'));
        });
    }

    async function revokeTempUser(btn, staffId) {
        if (!(await showConfirm('¿Quitar a esta persona de este evento? Perderá el acceso aquí de inmediato; la cuenta sigue existiendo y se puede volver a asignar.', { confirmLabel: 'Quitar del evento' }))) return;
        await busy(btn, async () => {
            const res = await fetch(`/api/events/${eventId}/staff-users/${staffId}`, { method: 'DELETE' });
            loadTempUsers();
            showToast(res.ok ? 'Acceso revocado' : 'No se pudo revocar el acceso', res.ok ? 'success' : 'error');
        });
    }

    async function resetTempPassword(btn, staffId, username) {
        if (!(await showConfirm(`La contraseña de "${window.escapeHtml(username)}" volverá a ser su cédula (el mismo usuario). ¿Restablecer?`, { confirmLabel: 'Restablecer' }))) return;
        await busy(btn, async () => {
            const res = await fetch(`/api/staff/${staffId}/password`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ use_username: true }) });
            const data = await res.json().catch(() => ({}));
            showToast(res.ok ? (data.message || 'Contraseña restablecida') : (data.detail || 'No se pudo restablecer'), res.ok ? 'success' : 'error');
        });
    }

    async function deleteTempUser(btn, staffId, username) {
        if (!(await showConfirm(`¿Borrar PERMANENTEMENTE la cuenta de "${window.escapeHtml(username)}"? Se perderán su acceso a este y a todos los eventos y su contraseña. Esto no es quitarlo del evento: se elimina de la base de datos y no se puede deshacer.`, { confirmLabel: 'Borrar cuenta' }))) return;
        await busy(btn, async () => {
            const res = await fetch(`/api/staff/${staffId}`, { method: 'DELETE' });
            if (res.ok) { loadTempUsers(); showToast('Cuenta eliminada', 'success'); }
            else { const err = await res.json().catch(() => ({})); showToast(err.detail || 'No se pudo borrar', 'error'); }
        });
    }

    // Eliminar de una vez todos los usuarios temporales (digitadores) de este evento: es «Borrar permanente» para todos, así que pide confirmar con el número exacto.
    if (purgeBtn) {
        purgeBtn.addEventListener('click', () => {
            const n = allUsers.filter((u) => u.role === 'digitador').length;
            return busy(purgeBtn, async () => {
                const ok = await showConfirm(`Se van a eliminar PERMANENTEMENTE las ${n} cuentas de digitador de este evento (no solo quitarlas del evento). Pierden el acceso aquí y se borran del sistema; no se puede deshacer. Si alguna también está en otro evento, a esa solo se le quita este evento. ¿Seguro?`, { confirmLabel: `Eliminar ${n} cuenta(s)` });
                if (!ok) return;
                const res = await fetch(`/api/events/${eventId}/staff-users/purge-temporary`, { method: 'POST' });
                const d = await res.json().catch(() => ({}));
                if (res.ok) {
                    pageIdx = 0;
                    loadTempUsers();
                    showToast(`${d.deleted} cuenta(s) eliminada(s)` + (d.only_unassigned ? ` · ${d.only_unassigned} solo se quitaron de este evento (están en otros)` : ''), 'success');
                } else showToast(d.detail || 'No se pudieron eliminar las cuentas', 'error');
            }).catch(() => showToast('No se pudo completar la acción. Revisa la conexión.', 'error'));
        });
    }

    // Asignar por Excel (Identificación, Nombres, Apellidos): crea las que no existen (usuario y contraseña = cédula) y asigna todas a este evento.
    const importForm = document.getElementById('importStaffForm');
    if (importForm) {
        importForm.addEventListener('submit', (ev) => {
            ev.preventDefault();
            const fileInput = document.getElementById('importStaffFile');
            const out = document.getElementById('importStaffResult');
            const btn = importForm.querySelector('button[type="submit"]');
            if (!fileInput.files.length) { showToast('Elige el archivo de Excel', 'error'); return null; }
            const fd = new FormData();
            fd.append('file', fileInput.files[0]);
            return busy(btn, async () => {
                const res = await fetch(`/api/events/${eventId}/staff-users/import`, { method: 'POST', body: fd });
                const d = await res.json().catch(() => ({}));
                if (!res.ok) { out.textContent = typeof d.detail === 'string' ? d.detail : 'No se pudo cargar el archivo'; out.classList.add('gw-msg--err'); showToast(out.textContent, 'error'); return; }
                out.classList.remove('gw-msg--err');
                const lines = [`Creadas y asignadas: ${d.created} · Ya existían y se asignaron: ${d.assigned_existing} · Ya estaban en este evento: ${d.already}` + (d.problems_total ? ` · Con problema: ${d.problems_total}` : '')];
                (d.problems || []).slice(0, 5).forEach((p) => lines.push(`Fila ${p.row}: ${p.detail}`));
                if (d.problems_total > 5) lines.push(`… y ${d.problems_total - 5} más.`);
                out.textContent = lines.join('\n');
                out.classList.add('gw-msg--lines');
                fileInput.value = '';
                pageIdx = 0;
                loadTempUsers();
                showToast(`${d.created + d.assigned_existing} cuenta(s) asignadas a este evento`, d.problems_total ? 'info' : 'success');
            }).catch(() => showToast('No se pudo cargar el archivo. Revisa la conexión.', 'error'));
        });
    }

    // Acción principal de la pantalla: «Crear usuario» lleva al formulario (abierto) y deja el cursor en el primer campo.
    document.addEventListener('click', (ev) => {
        const go = ev.target.closest('[data-open-group]');
        if (!go) return;
        const grp = document.getElementById(go.getAttribute('data-open-group'));
        if (!grp) return;
        grp.open = true;
        grp.scrollIntoView({ behavior: 'smooth', block: 'start' });
        const first = grp.querySelector('input:not([type="hidden"])');
        if (first) first.focus({ preventScroll: true });
    });

    // Menú «Más acciones» (Borrar permanente): se abre aquí y se cierra con clic afuera, Escape o al elegir.
    function closeMenus(except) {
        listEl.querySelectorAll('.gw-usr__more').forEach((m) => {
            if (m === except) return;
            m.querySelector('.gw-menu__panel').hidden = true;
            m.querySelector('[data-menu]').setAttribute('aria-expanded', 'false');
        });
    }
    document.addEventListener('click', (ev) => { if (!ev.target.closest('.gw-usr__more')) closeMenus(null); });
    document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') closeMenus(null); });

    listEl.addEventListener('click', (ev) => {
        const tog = ev.target.closest('[data-menu]');
        if (tog && listEl.contains(tog)) {
            const wrap = tog.closest('.gw-usr__more'), panel = wrap.querySelector('.gw-menu__panel'), open = panel.hidden;
            closeMenus(wrap);
            panel.hidden = !open;
            tog.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (open && panel.firstElementChild) panel.firstElementChild.focus();
            return;
        }
        const btn = ev.target.closest('button[data-act]');
        if (btn && btn.closest('.gw-usr__more')) closeMenus(null);
        if (!btn || !listEl.contains(btn)) return;
        const act = btn.getAttribute('data-act'), id = btn.getAttribute('data-id'), user = btn.getAttribute('data-username') || '';
        const run = act === 'reload' ? loadTempUsers()
            : act === 'revoke' ? revokeTempUser(btn, id)
            : act === 'reset' ? resetTempPassword(btn, id, user)
            : act === 'delete' ? deleteTempUser(btn, id, user) : null;
        if (run && run.catch) run.catch(() => showToast('No se pudo completar la acción. Revisa la conexión.', 'error'));
    });

    loadTempUsers();
    loadAssignableOptions();
})();
