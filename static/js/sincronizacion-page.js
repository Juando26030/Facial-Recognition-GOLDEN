/* Pantalla /sincronizacion (Fase 6). En el servidor LOCAL: estado de la subida (último paquete, última subida, pendientes), «Subir ahora» y «Pasar a internet» por evento.
   En la NUBE (admin): crear/revocar servidores locales; el token se muestra una sola vez. Delegación de eventos, texto escapado, mensajes con showToast/showConfirm. */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const box = document.getElementById('syncBox');
  const mode = box.dataset.mode;
  const when = (iso) => (iso ? new Date(iso + 'Z').toLocaleString() : '—');
  async function api(path, opts) {
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo completar la acción');
    return data;
  }
  const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

  /* ---- servidor local ---- */
  async function loadLocal() {
    try {
      const d = await api('/api/node-sync/status');
      const v = d.version || {};
      const warn = !d.configured ? '<div class="gw-alert gw-alert--warn" role="status">Este servidor todavía no tiene el código de acceso ni la dirección de producción: no puede subir. Pídele a un administrador que lo configure.</div>' : '';
      const ver = v.configured && v.status && v.status !== 'igual' && v.status !== 'desconocida' ? `<div class="gw-alert gw-alert--warn" role="status">${esc(v.message)}</div>` : '';
      const rows = d.events.map((e) => `<li class="gw-list__item"><div><strong>${esc(e.name)}</strong> <span class="gw-hint">${esc(e.code)}</span><br>
        <span class="gw-hint">Bajado: ${esc(when(e.package_at))} · Última subida: ${esc(when(e.last_upload_at))} · Pendientes: ${e.pending.total} (${e.pending.persons} altas, ${e.pending.logs} ingresos)</span>
        ${e.error ? `<br><span class="gw-text-danger">${esc(e.error)}</span>` : ''}
        ${e.local_only && Object.keys(e.local_only).length ? `<br><span class="gw-text-danger">Hecho aquí que todavía no sube a la nube: ${esc(Object.entries(e.local_only).map(([k, n]) => `${n} ${k}`).join(', '))}. Mientras exista, no se puede pasar a internet.</span>` : ''}</div>
        <button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-release="${e.id}">Pasar a internet</button></li>`).join('');
      box.innerHTML = warn + ver + `<div class="gw-toolbar"><button type="button" class="gw-btn gw-btn--secondary" data-run>Subir ahora</button><span class="gw-hint">Pendientes en total: ${d.pending_total}. Se sube solo cada ${d.interval_minutes} min.</span></div>` +
        (rows ? `<ul class="gw-list">${rows}</ul>` : '<div class="gw-state" role="status"><p class="gw-state__title">No hay eventos bajados de la nube en este servidor</p></div>');
    } catch (err) { box.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`; }
    finally { box.setAttribute('aria-busy', 'false'); }
  }

  /* ---- nube (admin) ---- */
  async function loadCloud() {
    try {
      const d = await api('/api/nodes');
      const rows = d.nodes.map((n) => `<li class="gw-list__item"><div><strong>${esc(n.name)}</strong> ${n.revoked ? '<span class="gw-badge">Revocado</span>' : ''}<br>
        <span class="gw-hint">Creado ${esc(when(n.created_at))}${n.created_by_name ? ' por ' + esc(n.created_by_name) : ''} · Última conexión: ${esc(when(n.last_seen_at))}${n.last_version ? ' · Versión ' + esc(n.last_version) : ''}</span></div>
        ${n.revoked ? '' : `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-revoke="${n.id}" data-name="${esc(n.name)}">Revocar</button>`}</li>`).join('');
      box.innerHTML = '<div class="gw-toolbar"><button type="button" class="gw-btn gw-btn--primary" data-create>Crear servidor local</button></div>' +
        (rows ? `<ul class="gw-list">${rows}</ul>` : '<div class="gw-state" role="status"><p class="gw-state__title">Todavía no hay servidores locales</p></div>');
    } catch (err) { box.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`; }
    finally { box.setAttribute('aria-busy', 'false'); }
  }

  box.addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    try {
      if (b.hasAttribute('data-run')) {
        b.disabled = true;
        const r = await post('/api/node-sync/run');
        showToast(r.failed ? 'Algunos eventos no se pudieron subir: revisa el motivo en cada uno' : 'Subida terminada', r.failed ? 'error' : 'success');
        await loadLocal();
      } else if (b.dataset.release) {
        if (!(await showConfirm('Se sube todo lo pendiente y el evento vuelve a editarse en la nube; este servidor deja de ser el dueño del evento. ¿Pasarlo a internet?', { variant: 'warning', confirmLabel: 'Sí, pasar a internet' }))) return;
        b.disabled = true;
        await post(`/api/node-sync/events/${b.dataset.release}/release`);
        showToast('El evento volvió a internet', 'success');
        await loadLocal();
      } else if (b.hasAttribute('data-create')) {
        const name = await showPrompt('Nombre del servidor local (por ejemplo «Portátil bodega 1»):', { title: 'Crear servidor local', confirmLabel: 'Crear' });
        if (!name) return;
        const d = await post('/api/nodes', { name });
        await showConfirm(`Servidor «${esc(d.name)}» creado. Copia este código y pégalo en la configuración del servidor local (NODE_TOKEN). <b>No se vuelve a mostrar.</b><br><br><code>${esc(d.token)}</code>`, { variant: 'warning', confirmLabel: 'Ya lo copié' });
        await loadCloud();
      } else if (b.dataset.revoke) {
        if (!(await showConfirm(`¿Revocar «${esc(b.dataset.name)}»? Ese servidor ya no podrá subir datos.`, { variant: 'warning', confirmLabel: 'Sí, revocar' }))) return;
        await post(`/api/nodes/${b.dataset.revoke}/revoke`);
        showToast('Servidor revocado', 'success');
        await loadCloud();
      }
    } catch (err) { showToast(err.message, 'error'); b.disabled = false; }
  });
  (mode === 'local' ? loadLocal : loadCloud)();
})();
