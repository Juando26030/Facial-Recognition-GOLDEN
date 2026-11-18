/* Compromiso digital del digitador en «Usuarios temporales» (Fase 4). Panel del enlace + insignias por persona.
   El formulario público es el del motor de formularios web (/f/<evento>/<enlace>); aquí solo se administra. Delegación de eventos, sin onclick. */
(function () {
    'use strict';
    const eventId = window.EVENT_ID;
    const panel = document.getElementById('pledgePanel');
    if (!panel || !eventId) return;
    const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const $ = (sel) => panel.querySelector(sel);
    const api = `/api/events/${eventId}/pledge`;
    let info = null, byStaff = {};
    let pending = null;                 // valor de «Exigir el compromiso» editado y aún sin guardar (null = nada pendiente)

    async function call(url, method, body) {
        const res = await fetch(url, { method, cache: 'no-store', headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
        let data = null;
        try { data = await res.json(); } catch (e) { /* sin cuerpo */ }
        if (!res.ok) throw new Error((data && data.detail) || 'No se pudo completar la acción');
        return data;
    }

    function paint() {
        if (!info) return;
        panel.hidden = false;
        $('[data-pl-enabled]').checked = pending == null ? !!info.enabled : pending;
        const url = $('[data-pl-url]');
        url.value = info.link || '';
        $('[data-pl-copy]').disabled = !info.link;
        $('[data-pl-qr]').disabled = !info.link;
        $('[data-pl-revoke]').hidden = !info.link;
        $('[data-pl-make]').textContent = info.link ? 'Cambiar el enlace' : 'Generar el enlace';
        $('[data-pl-make]').dataset.plRegen = info.link ? '1' : '';
        $('[data-pl-draft]').hidden = !(info.draft && info.text_available);
        $('[data-pl-unavailable]').hidden = info.text_available;
        $('[data-pl-note]').textContent = info.enabled
            ? 'Los digitadores de este evento deben firmar antes de que puedas autorizar su ingreso.'
            : 'Hoy no se exige: los digitadores ingresan sin firmar.';
    }

    async function loadInfo() {
        try { info = await call(api, 'GET'); paint(); } catch (e) { /* comercial u otro sin permiso: el panel sigue oculto */ }
    }

    async function loadState() {
        if (!info) return;
        try {
            const d = await call(api + '/state', 'GET');
            const map = {};
            (d.accounts || []).forEach((a) => { map[a.id] = a; });
            const key = JSON.stringify(d);
            const changed = key !== JSON.stringify(byStaff);
            byStaff = map;
            if (changed) document.dispatchEvent(new CustomEvent('compromiso:cambio'));
        } catch (e) { /* se intenta en el siguiente turno */ }
    }

    const fmt = (iso) => { try { return new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' }); } catch (e) { return ''; } };

    // Alertas en amarillo por cada respuesta que merece atención (solo cuáles; el detalle sensible se abre aparte y queda auditado).
    const alertIcon = () => { const el = document.querySelector('script[data-icons]'); return `<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${esc((el && el.dataset.icons) || '/static/img/icons.svg')}#i-alert"/></svg>`; };
    const HEALTH_LABEL = { med: 'Respondió Sí a: condición médica especial', drug: 'Respondió Sí a: toma medicamento', support: 'Respondió Sí a: requiere apoyo' };
    function alerts(a) {
        const out = [];
        const flags = a.health_flags || [];
        flags.forEach((k) => { if (HEALTH_LABEL[k]) out.push(HEALTH_LABEL[k]); });
        if (a.has_health_info && !flags.length) out.push('Respondió Sí en preguntas de salud');          // firmas anteriores a la alerta detallada
        if (a.understands_terms === false) out.push('Respondió No a: tiene claras las condiciones del contrato');
        if (a.attendance_confirmed === false) out.push('Respondió No a: confirma su asistencia');
        return out;
    }

    // Lo que usuarios.js pega en cada tarjeta de digitador. Solo banderas: lo sensible se abre aparte y queda auditado.
    window.UsuariosCompromiso = {
        active: () => !!(info && (info.enabled || Object.values(byStaff).some((a) => a.signed))),
        blocked: (id) => !!(byStaff[id] && byStaff[id].blocked),
        badges(id) {
            const a = byStaff[id];
            if (!a || !info) return '';
            if (!a.signed) return info.enabled ? ' <span class="gw-badge gw-badge--warn">Sin compromiso firmado</span>' : '';
            let h = ` <span class="gw-badge gw-badge--ok" title="${esc(fmt(a.signed_at))}">Compromiso firmado</span>`;
            return h + alerts(a).map((t) => ` <span class="gw-badge gw-badge--warn">${alertIcon()}${esc(t)}</span>`).join('');
        },
        hasAlert: (id) => !!(byStaff[id] && byStaff[id].signed && alerts(byStaff[id]).length),
        actions(id) {
            const a = byStaff[id];
            if (!a || !a.signed) return '';
            const b = (act, label) => `<button type="button" class="gw-btn gw-btn--secondary" data-pledge-act="${act}" data-pledge-id="${esc(a.pledge_id)}"><span>${label}</span></button>`;
            return b('doc', 'Ver compromiso') + (a.has_health_info ? b('health', 'Ver datos de salud') : '') + (a.resign_allowed ? '' : b('resign', 'Permitir nueva firma'));
        },
    };

    panel.addEventListener('click', async (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        try {
            if (btn.hasAttribute('data-pl-copy')) {
                if (await window.copyText(info.link)) showToast('Enlace copiado', 'success');
                else { const box = $('input[readonly], input'); if (box) { box.focus(); box.select(); } showToast('No se pudo copiar solo: el enlace quedó seleccionado, cópialo con Ctrl+C', 'info'); }
            } else if (btn.hasAttribute('data-pl-make')) {
                if (btn.dataset.plRegen && !(await showConfirm('Al cambiar el enlace, el anterior deja de funcionar. ¿Continuar?'))) return;
                info = await call(api + '/link', 'POST', { regenerate: !!btn.dataset.plRegen });
                paint();
                showToast('Enlace listo', 'success');
            } else if (btn.hasAttribute('data-pl-revoke')) {
                if (!(await showConfirm('El enlace dejará de funcionar. El compromiso se sigue exigiendo al ingresar. ¿Revocarlo?'))) return;
                info = await call(api + '/link', 'DELETE');
                paint();
            }
        } catch (err) { showToast(err.message, 'error'); }
    });
    // «Exigir el compromiso» queda pendiente hasta «Guardar cambios» (barra única de la pantalla).
    panel.addEventListener('change', (e) => { if (e.target.matches('[data-pl-enabled]')) pending = e.target.checked; });
    GWParams.register({ key: 'pledge', label: 'Compromiso digital', order: 20, save: async () => {
        if (pending == null) return;
        info = await call(api + '/enabled', 'PUT', { enabled: pending });
        pending = null;
        paint();
        await loadState();
    } });

    document.addEventListener('click', async (e) => {
        const btn = e.target.closest && e.target.closest('button[data-pledge-act]');
        if (!btn) return;
        const act = btn.dataset.pledgeAct, pid = btn.dataset.pledgeId;
        try {
            if (act === 'doc') {
                window.open(`${api}/${encodeURIComponent(pid)}/document`, '_blank', 'noopener');
            } else if (act === 'health') {
                const d = await call(`${api}/${encodeURIComponent(pid)}/health`, 'GET');
                const rows = (d.items || []).map((i) => `<li><strong>${esc(i.label)}</strong>: ${esc(i.value)}</li>`).join('');
                await showConfirm(`<p>Información sensible: úsala solo para cuidar a la persona. Quedó registrado que la abriste.</p><ul>${rows}</ul>${d.phone ? `<p>Celular: ${esc(d.phone)}</p>` : ''}`, { confirmLabel: 'Entendido' });
            } else if (act === 'resign') {
                if (!(await showConfirm('Esa persona podrá firmar de nuevo con el enlace. La firma actual queda como historial. ¿Permitirlo?'))) return;
                const d = await call(`${api}/${encodeURIComponent(pid)}/allow-resign`, 'POST');
                showToast(d.message, 'success');
                await loadState();
            }
        } catch (err) { showToast(err.message, 'error'); }
    });

    loadInfo().then(loadState);
    const tick = () => { if (document.visibilityState === 'visible') loadState(); };
    if (window.GW && window.GW.poll) window.GW.poll(tick, 20000); else setInterval(tick, 20000);
})();
