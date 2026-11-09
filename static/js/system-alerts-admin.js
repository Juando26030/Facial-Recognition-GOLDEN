/* Alertas del sistema (Configuración → «Alertas del sistema», admin): umbral del aviso de borrado masivo, destinatarios y prueba.
   API: /api/system-alerts/* (app/routers/system_alerts.py). Todo se escapa; sin manejadores en línea (delegación); mensajes con showToast / showConfirm. */
(function () {
  'use strict';
  const root = document.getElementById('alertas');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const ICONS = root.dataset.icons || '/static/img/icons.svg';
  const icon = (n) => `<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${ICONS}#i-${n}"/></svg>`;
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());
  let state = null;
  let loaded = false;

  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo completar la acción'); return d; }
  const send = (url, method, body) => j(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const fail = (e) => showToast(e.message || 'No se pudo completar la acción', 'error');
  const when = (iso) => { try { return new Date(iso).toLocaleString('es-CO', { timeZone: 'America/Bogota', dateStyle: 'short', timeStyle: 'short' }); } catch (e) { return ''; } };

  function recipientRow(r) {
    const name = r.kind === 'staff' ? (r.label || 'Cuenta') + (r.role ? ' · ' + r.role : '') : (r.email || '');
    const meta = r.kind === 'staff' ? (r.email ? 'Cuenta de la plataforma · campana y correo ' + esc(r.email) : 'Cuenta de la plataforma · solo campana (sin correo registrado)') : 'Correo externo';
    return `<article class="gw-card-row"><div class="gw-card-row__head"><span class="gw-card-row__title">${esc(name)}</span>${r.active ? '<span class="gw-badge gw-badge--ok">Activo</span>' : '<span class="gw-badge">Pausado</span>'}</div>
      <p class="gw-card-row__meta">${meta}</p><div class="gw-card-row__actions">
      <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-al-toggle="${r.id}" data-active="${r.active ? '1' : '0'}">${r.active ? 'Desactivar' : 'Activar'}</button>
      <button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-al-del="${r.id}" data-name="${esc(name)}" aria-label="Quitar ${esc(name)}">${icon('trash')} Quitar</button></div></article>`;
  }

  const empty = (title, text) => `<div class="gw-state" role="status"><p class="gw-state__title">${title}</p><p class="gw-state__text">${text}</p></div>`;

  function paint() {
    const s = state.settings;
    $('alEnabled').checked = !!s.enabled;
    $('alPerAction').value = s.per_action;
    $('alWindowCount').value = s.window_count;
    $('alWindowMinutes').value = s.window_minutes;
    $('alList').innerHTML = state.recipients.length ? state.recipients.map(recipientRow).join('') : empty('Nadie recibe las alertas', 'Agrega al menos un correo para enterarte de un borrado masivo.');
    const opts = state.staff_options;
    $('alStaff').innerHTML = opts.length ? opts.map((o) => `<option value="${o.id}">${esc(o.label)} · ${esc(o.role)}${o.has_email ? '' : ' (sin correo)'}</option>`).join('') : '<option value="">No hay más cuentas para agregar</option>';
    $('alStaffBtn').disabled = !opts.length;
    $('alRecent').innerHTML = state.recent.length
      ? state.recent.map((a) => `<article class="gw-card-row"><div class="gw-card-row__head"><span class="gw-card-row__title">${esc(a.title)}</span></div><p class="gw-card-row__meta">${esc(when(a.created_at))}${a.actor ? ' · ' + esc(a.actor) : ''}</p><p>${esc(a.body)}</p></article>`).join('')
      : empty('Sin alertas todavía', 'Aquí aparecerán las alertas que se hayan enviado.');
  }

  async function load() {
    try { state = await j('/api/system-alerts'); paint(); loaded = true; } catch (e) {
      fail(e);
      if (!loaded && window.GW && GW.skeleton) { GW.skeleton.error($('alList'), { title: 'No se pudieron cargar las alertas', text: e.message || 'Inténtalo de nuevo.' }); $('alRecent').innerHTML = ''; }
    }
  }

  $('alSettingsForm').addEventListener('submit', (ev) => {
    ev.preventDefault();
    busy($('alSettingsBtn'), async () => {
      try {
        const d = await send('/api/system-alerts/settings', 'PUT', { enabled: $('alEnabled').checked, per_action: +$('alPerAction').value || 0, window_count: +$('alWindowCount').value || 0, window_minutes: +$('alWindowMinutes').value || 0 });
        state.settings = d.settings; paint(); showToast('Umbral guardado', 'success');
      } catch (e) { fail(e); }
    });
  });

  $('alEmailForm').addEventListener('submit', (ev) => {
    ev.preventDefault();
    busy($('alEmailBtn'), async () => {
      try { await send('/api/system-alerts/recipients', 'POST', { email: $('alEmail').value.trim() }); $('alEmail').value = ''; await load(); showToast('Correo agregado', 'success'); } catch (e) { fail(e); }
    });
  });

  $('alStaffForm').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const id = +$('alStaff').value;
    if (!id) return;
    busy($('alStaffBtn'), async () => {
      try { await send('/api/system-alerts/recipients', 'POST', { staff_user_id: id }); await load(); showToast('Cuenta agregada', 'success'); } catch (e) { fail(e); }
    });
  });

  $('alTestBtn').addEventListener('click', () => {
    busy($('alTestBtn'), async () => {
      try { const d = await send('/api/system-alerts/test', 'POST'); showToast('Prueba enviada a ' + d.sent_to + (d.sent_to === 1 ? ' destinatario' : ' destinatarios'), 'success'); await load(); } catch (e) { fail(e); }
    });
  });

  root.addEventListener('click', async (ev) => {
    const tog = ev.target.closest('[data-al-toggle]');
    const del = ev.target.closest('[data-al-del]');
    try {
      if (tog) {
        await send('/api/system-alerts/recipients/' + tog.dataset.alToggle, 'PATCH', { active: tog.dataset.active !== '1' });
        await load();
      } else if (del) {
        const ok = await showConfirm('¿Quitar a ' + esc(del.dataset.name) + ' de las alertas? Dejará de recibir los avisos de borrado masivo.', { confirmLabel: 'Quitar' });
        if (!ok) return;
        await send('/api/system-alerts/recipients/' + del.dataset.alDel, 'DELETE');
        await load();
        showToast('Destinatario quitado', 'success');
      }
    } catch (e) { fail(e); }
  });

  /* La pestaña carga sus datos la primera vez que se abre (no antes: la página de Configuración no hace consultas de más). */
  const tab = $('tab_alertas');
  if (tab) tab.addEventListener('click', () => { if (!loaded) load(); });
  if (location.hash === '#alertas') load();
})();
