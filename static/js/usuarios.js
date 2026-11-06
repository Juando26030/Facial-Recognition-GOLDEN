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

    function setStatus(text, isErr) {
        statusEl.textContent = text || '';
        statusEl.classList.toggle('gw-msg--err', !!(text && isErr));
    }

    function cardHtml(u) {
        const rol = ROLES[u.role] || u.role;
        const nombre = u.full_name || 'Sin nombre';
        const estado = u.is_active ? '<span class="gw-badge gw-badge--ok">Activo</span>' : '<span class="gw-badge gw-badge--warn">Inactivo</span>';
        const reset = u.role === 'digitador'
            ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="reset" data-id="${esc(u.id)}" data-username="${esc(u.username)}">Restablecer contraseña</button>` : '';
        return `<article class="gw-card-row">
            <div class="gw-card-row__head">
                <span class="gw-card-row__title">${esc(u.username)}</span>
                <span class="gw-rowact"><span class="gw-badge gw-badge--info">${esc(rol)}</span>${estado}</span>
            </div>
            <p class="gw-card-row__meta">${esc(nombre)}</p>
            <div class="gw-card-row__actions">
                ${reset}
                <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="revoke" data-id="${esc(u.id)}">Quitar de este evento</button>
                <button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-act="delete" data-id="${esc(u.id)}" data-username="${esc(u.username)}">Borrar permanente</button>
            </div>
        </article>`;
    }

    async function loadTempUsers() {
        listEl.setAttribute('aria-busy', 'true');
        try {
            const res = await fetch(`/api/events/${eventId}/staff-users`);
            if (!res.ok) throw new Error('http ' + res.status);
            const list = await res.json();
            setStatus('');
            listEl.innerHTML = list.length
                ? list.map(cardHtml).join('')
                : '<div class="gw-empty" role="note"><p>Todavía no hay cuentas asignadas a este evento.</p><p class="gw-hint">Crea la primera con «Nueva cuenta para este evento».</p></div>';
        } catch (e) {
            listEl.innerHTML = '';
            setStatus('No se pudieron cargar las cuentas. Revisa la conexión y vuelve a intentar.', true);
            const retry = document.createElement('button');
            retry.type = 'button'; retry.className = 'gw-btn gw-btn--secondary gw-btn--sm'; retry.setAttribute('data-act', 'reload'); retry.textContent = 'Reintentar';
            listEl.appendChild(retry);
        } finally {
            listEl.removeAttribute('aria-busy');
        }
    }

    async function loadAssignableOptions() {
        if (!assignForm) return;
        const res = await fetch('/api/staff/assignable');
        const list = await res.json();
        document.getElementById('assignableSelect').innerHTML = list
            .map((s) => `<option value="${esc(s.id)}">${esc(s.username)}${s.full_name ? ' - ' + esc(s.full_name) : ''} (${esc(s.role)})</option>`).join('');
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
            const staffId = new FormData(ev.target).get('staff_id');
            return busy(btn, async () => {
                const res = await fetch(`/api/events/${eventId}/staff-users/assign-existing`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ staff_id: Number(staffId) }),
                });
                if (res.ok) { loadTempUsers(); showToast('Cuenta asignada al evento', 'success'); }
                else { const err = await res.json().catch(() => ({})); showToast(err.detail || 'No se pudo asignar', 'error'); }
            }).catch(() => showToast('No se pudo asignar. Revisa la conexión.', 'error'));
        });
    }

    async function revokeTempUser(btn, staffId) {
        if (!(await showConfirm('¿Quitar el acceso de este usuario a este evento?'))) return;
        await busy(btn, async () => {
            const res = await fetch(`/api/events/${eventId}/staff-users/${staffId}`, { method: 'DELETE' });
            loadTempUsers();
            showToast(res.ok ? 'Acceso revocado' : 'No se pudo revocar el acceso', res.ok ? 'success' : 'error');
        });
    }

    async function resetTempPassword(btn, staffId, username) {
        const pwd = await showPrompt(`Contraseña temporal para "${username}" (mínimo 10 caracteres, con letras y números). Al ingresar, tendrá que elegir la suya:`, { confirmLabel: 'Restablecer' });
        if (pwd === null) return;
        await busy(btn, async () => {
            const res = await fetch(`/api/staff/${staffId}/password`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_password: pwd, must_change: true }) });
            const data = await res.json().catch(() => ({}));
            showToast(res.ok ? (data.message || 'Contraseña restablecida') : (data.detail || 'No se pudo restablecer'), res.ok ? 'success' : 'error');
        });
    }

    async function deleteTempUser(btn, staffId, username) {
        if (!(await showConfirm(`¿Borrar PERMANENTEMENTE la cuenta de "${window.escapeHtml(username)}"? Esto no es quitarlo del evento — se elimina de la base de datos y no se puede deshacer.`))) return;
        await busy(btn, async () => {
            const res = await fetch(`/api/staff/${staffId}`, { method: 'DELETE' });
            if (res.ok) { loadTempUsers(); showToast('Cuenta eliminada', 'success'); }
            else { const err = await res.json().catch(() => ({})); showToast(err.detail || 'No se pudo borrar', 'error'); }
        });
    }

    listEl.addEventListener('click', (ev) => {
        const btn = ev.target.closest('button[data-act]');
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
