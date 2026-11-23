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
      // La misma tarjeta de evento que en Eventos (nombre, datos, estado), pero con UNA sola acción: «Pasar a internet» en lugar de «Ingresar».
      const rows = d.events.map((e) => {
        const bad = e.local_only && Object.keys(e.local_only).length;
        const badge = e.pending.total ? `<span class="gw-badge gw-badge--warn">${e.pending.total} por subir</span>` : '<span class="gw-badge gw-badge--ok">Todo subido</span>';
        return `<div class="gw-card-row gw-event-card sync-card"><div class="sync-card__info">
          <div class="gw-card-row__head"><span class="gw-card-row__title">${esc(e.name)} ${e.code ? `<span class="gw-event-code">(${esc(e.code)})</span>` : ''}</span>${badge}</div>
          <p class="gw-card-row__meta">Bajado: ${esc(when(e.package_at))} · Última subida: ${esc(when(e.last_upload_at))}</p>${e.shared ? `<p class="gw-card-row__meta"><span class="gw-badge gw-badge--info">Compartido</span> Lo de los otros servidores, bajado por última vez: ${esc(when(e.last_pull_at))} (cada pocos segundos mientras el evento esté «En proceso» y haya internet)</p>` : ''}
          <p class="gw-card-row__meta">Pendientes: ${e.pending.total} (${e.pending.persons} altas, ${e.pending.logs} ingresos, ${e.pending.prints || 0} impresiones, ${e.pending.changes || 0} ediciones)</p>
          ${e.error ? `<p class="gw-text-danger">${esc(e.error)}</p>` : ''}
          ${bad ? `<p class="gw-text-danger">Registrado solo en este servidor (la sincronización todavía no lo envía a la nube): ${esc(Object.entries(e.local_only).map(([k, n]) => `${n} ${k}`).join(', '))}. Por eso «Pasar a internet» está protegido: se perdería. Avisa a soporte antes de liberar.</p>` : ''}</div>
          <div class="gw-card-row__actions"><button type="button" class="gw-btn gw-btn--secondary" data-sync="${e.id}" title="Sube ahora lo pendiente de este evento, sin esperar los 30 minutos">Sincronizar</button><button type="button" class="gw-btn gw-btn--primary" data-release="${e.id}">Pasar a internet</button></div></div>`;
      }).join('');
      box.innerHTML = warn + ver + `<div class="gw-toolbar"><button type="button" class="gw-btn gw-btn--secondary" data-run>Subir ahora</button><span class="gw-hint">Pendientes en total: ${d.pending_total}. Se sube solo cada ${d.interval_minutes} min.</span></div>` +
        (rows ? `<div class="ev-list sync-list">${rows}</div>` : '<div class="gw-state" role="status"><p class="gw-state__title">No hay eventos bajados de la nube en este servidor</p></div>');
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
      } else if (b.dataset.sync) {
        b.disabled = true;
        const old = b.textContent; b.textContent = 'Sincronizando…';
        try { const r = await post(`/api/node-sync/events/${b.dataset.sync}/run`); showToast(r.pending ? `Sincronizado; quedan ${r.pending} por subir` : 'Sincronizado: todo subido', r.pending ? 'warning' : 'success'); }
        finally { b.disabled = false; b.textContent = old; }
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
