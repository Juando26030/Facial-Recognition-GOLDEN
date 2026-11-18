/* Supereventos de un cliente (Fase 3): ventana «Administrar supereventos» con Editar (nombre), Archivar, Restaurar, «Ver archivados» y «Eliminar definitivamente» (solo super_admin).
   Se abre desde «Editar evento» (_event_edit_modal.html) y desde «Nuevo evento». API: GWSuper.manage({ tenantId, role, onChange }). Requiere toast.js (showConfirm/showPrompt/showToast).
   Archivar no toca los eventos del superevento; borrar solo si está archivado y sin eventos. Delegación de eventos, sin onclick en línea. */
(function () {
  'use strict';
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));
  let overlay = null;

  function build() {
    const el = document.createElement('div');
    el.className = 'gw-modal-backdrop gw-modal-backdrop--top';
    el.innerHTML = '<div class="gw-modal" role="dialog" aria-modal="true" aria-labelledby="gwSupTitle">' +
      '<div class="gw-modal__head"><h2 class="gw-modal__title" id="gwSupTitle">Administrar supereventos</h2></div>' +
      '<div class="gw-modal__body"><label class="gw-check"><input type="checkbox" data-sup-archived> Ver archivados</label>' +
      '<p class="gw-modal__text">Archivar un superevento lo saca de las listas; <strong>sus eventos no se tocan</strong>.</p>' +
      '<div data-sup-list aria-live="polite"></div></div>' +
      '<div class="gw-modal__foot"><button type="button" class="gw-btn gw-btn--secondary" data-sup-close>Cerrar</button></div></div>';
    document.body.appendChild(el);
    return el;
  }

  function manage(opts) {
    const tenantId = opts.tenantId, role = opts.role || '', onChange = opts.onChange || function () {};
    const isSuper = role === 'super_admin';
    if (!tenantId) { if (window.showToast) showToast('Primero elige el cliente.', 'error'); return; }
    if (overlay) overlay.remove();
    overlay = build();
    const listEl = overlay.querySelector('[data-sup-list]');
    const chk = overlay.querySelector('[data-sup-archived]');
    const opener = document.activeElement;

    const close = () => { overlay.remove(); overlay = null; if (opener && opener.focus) opener.focus(); };
    async function api(path, method, body) {
      const res = await fetch('/api/super-events' + path, { method: method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showToast(data.detail || 'No se pudo completar la acción', 'error'); return null; }
      return data;
    }
    async function load() {
      const res = await fetch('/api/super-events?tenant_id=' + encodeURIComponent(tenantId) + (chk.checked ? '&include_archived=true' : ''));
      if (!res.ok) { listEl.innerHTML = '<div class="gw-alert gw-alert--err" role="alert">No se pudieron cargar los supereventos.</div>'; return; }
      const rows = await res.json();
      if (!rows.length) { listEl.innerHTML = '<div class="gw-empty" role="status"><p>' + (chk.checked ? 'No hay supereventos.' : 'Este cliente no tiene supereventos activos.') + '</p></div>'; return; }
      listEl.innerHTML = rows.map((s) => {
        const btns = s.archived
          ? '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="restore" data-id="' + esc(s.id) + '">Restaurar</button>' +
            (isSuper ? '<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-act="purge" data-id="' + esc(s.id) + '" data-name="' + esc(s.name) + '">Eliminar definitivamente</button>' : '')
          : '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="edit" data-id="' + esc(s.id) + '" data-name="' + esc(s.name) + '">Editar</button>' +
            '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="archive" data-id="' + esc(s.id) + '" data-name="' + esc(s.name) + '">Archivar</button>';
        return '<div class="gw-card-row"><div class="gw-card-row__head">' +
          '<span class="gw-card-row__title">' + esc(s.name) + ' <span class="gw-card-row__meta">(' + esc(s.events) + ' eventos)</span></span>' + (s.archived ? '<span class="gw-badge gw-badge--warn">Archivado</span>' : '') + '</div>' +
          '<div class="gw-card-row__actions">' + btns + '</div></div>';
      }).join('');
    }

    overlay.addEventListener('click', async (e) => {
      if (e.target.closest('[data-sup-close]')) { close(); return; }
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const id = b.dataset.id, name = b.dataset.name || '';
      if (b.dataset.act === 'edit') {
        const nv = await showPrompt('Nuevo nombre del superevento:', { defaultValue: name, confirmLabel: 'Guardar' });
        if (!nv || nv === name) return;
        await busy(b, async () => { if (await api('/' + id, 'PATCH', { name: nv })) { showToast('Superevento actualizado', 'success'); await load(); onChange(); } });
      } else if (b.dataset.act === 'archive') {
        if (!await showConfirm('¿Archivar el superevento "' + esc(name) + '"?<br><br>Sale de las listas y selectores. <strong>Sus eventos no se tocan</strong> y se puede restaurar.', { confirmLabel: 'Archivar' })) return;
        await busy(b, async () => { if (await api('/' + id + '/archive', 'POST')) { showToast('Superevento archivado', 'success'); await load(); onChange(); } });
      } else if (b.dataset.act === 'restore') {
        await busy(b, async () => { if (await api('/' + id + '/restore', 'POST')) { showToast('Superevento restaurado', 'success'); await load(); onChange(); } });
      } else if (b.dataset.act === 'purge') {
        if (!await showConfirm('¿Eliminar DEFINITIVAMENTE el superevento "' + esc(name) + '"?<br><br>Solo se puede si no tiene eventos. Es permanente y queda registrado.', { confirmLabel: 'Eliminar definitivamente' })) return;
        await busy(b, async () => { if (await api('/' + id, 'DELETE')) { showToast('Superevento eliminado', 'success'); await load(); onChange(); } });
      }
    });
    chk.addEventListener('change', load);
    overlay.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !document.querySelector('.gw-modal-backdrop--top ~ .gw-modal-backdrop--top')) close(); });
    overlay.dataset.open = 'true';
    load();
    overlay.querySelector('[data-sup-close]').focus();
  }

  window.GWSuper = { manage: manage };
})();
