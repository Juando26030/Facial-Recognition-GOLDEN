/* Estados de evento (Configuración → «Estados de evento», admin+). Lista, crear, renombrar, archivar/restaurar y eliminar definitivamente (super_admin).
   API: /api/event-states (app/routers/event_states.py). Las reglas del servidor (no archivar uno en uso ni el último de su estado base) llegan como mensaje y se muestran con showToast. */
(function () {
  'use strict';
  const root = document.getElementById('estados');
  if (!root) return;
  const R = window.GWArchiveRules;
  const ROLE = root.dataset.role || '';
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const ICONS = root.dataset.icons || '/static/img/icons.svg';
  const icon = (n) => `<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${ICONS}#i-${n}"/></svg>`;
  const BASE = { creado: 'Creado', en_proceso: 'En proceso', finalizado: 'Finalizado' };
  const HEX = /^#[0-9a-fA-F]{6}$/;
  const perms = R.actions(ROLE, 'event_state', false);
  let showArchived = false;

  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error'); return d; }
  const send = (url, method, body) => j(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());

  function row(s) {
    const a = R.actions(ROLE, 'event_state', s.archived);
    const using = s.events_using ? `${s.events_using} ${s.events_using === 1 ? 'evento' : 'eventos'}` : 'Sin eventos';
    const btns = [];
    if (!s.archived) btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-rename="${s.id}" data-name="${esc(s.name)}" aria-label="Renombrar ${esc(s.name)}">${icon('edit')} Renombrar</button>`);
    if (a.archive) btns.push(`<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-archive="${s.id}" data-name="${esc(s.name)}" aria-label="Archivar ${esc(s.name)}">${icon('trash')} Archivar</button>`);
    if (a.restore) btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-restore="${s.id}" data-name="${esc(s.name)}" aria-label="Restaurar ${esc(s.name)}">${icon('undo')} Restaurar</button>`);
    if (a.del) btns.push(`<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-del="${s.id}" data-name="${esc(s.name)}" aria-label="Eliminar definitivamente ${esc(s.name)}">${icon('trash')} Eliminar definitivamente</button>`);
    return `<article class="gw-card-row" data-state="${s.id}">
      <div class="gw-card-row__head">
        <span class="gw-card-row__title"><span class="gw-estado__dot" data-color="${esc(s.color || '')}" aria-hidden="true"></span> ${esc(s.name)}</span>
        <span class="gw-badge">${esc(BASE[s.base_status] || s.base_status)}</span>
      </div>
      <p class="gw-card-row__meta">${using}${s.archived ? ' · Archivado' : (s.is_active ? '' : ' · Inactivo')}</p>
      ${btns.length ? `<div class="gw-card-row__actions">${btns.join('')}</div>` : ''}
    </article>`;
  }

  function paintDots() {
    root.querySelectorAll('.gw-estado__dot').forEach((d) => { const c = d.dataset.color; if (HEX.test(c)) d.style.setProperty('--gw-estado-color', c); });
  }

  async function load() {
    const box = $('estadosList');
    box.setAttribute('aria-busy', 'true');
    box.innerHTML = '<div class="gw-skeleton gw-estado__skeleton" role="status" aria-label="Cargando estados"></div>';
    try {
      const d = await j(`/api/event-states${showArchived && perms.canViewArchived ? '?include_archived=true' : ''}`, { cache: 'no-store' });
      const list = showArchived ? d.states.filter((s) => s.archived) : d.states;
      box.innerHTML = list.map(row).join('') || (showArchived
        ? '<div class="gw-state" role="status"><p class="gw-state__title">No hay estados archivados</p><p class="gw-state__text">Cuando archives uno, aparecerá aquí para poder restaurarlo.</p></div>'
        : '<div class="gw-state" role="status"><p class="gw-state__title">Todavía no hay estados de evento</p><p class="gw-state__text">Crea el primero con el formulario de arriba.</p></div>');
      const sel = $('stateBase');
      if (sel && !sel.options.length) sel.innerHTML = d.base_statuses.map((b) => `<option value="${esc(b)}">${esc(BASE[b] || b)}</option>`).join('');
      paintDots();
    } catch (e) {
      box.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudieron cargar los estados</p><p class="gw-state__text">${esc(e.message)}. Inténtalo de nuevo; si sigue igual, avisa a un administrador.</p><button type="button" class="gw-btn gw-btn--secondary" data-retry>Reintentar</button></div>`;
    } finally { box.setAttribute('aria-busy', 'false'); }
  }

  $('stateForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('stateName').value.trim();
    if (!name) { showToast('Escribe el nombre del estado', 'error'); return; }
    try {
      await busy($('stateCreateBtn'), () => send('/api/event-states', 'POST', { name, base_status: $('stateBase').value, color: $('stateColor').value }));
      $('stateName').value = '';
      showToast(`Estado «${name}» creado`, 'success');
      load();
    } catch (err) { showToast(err.message, 'error'); }
  });

  const archToggle = $('showArchivedStates');
  if (archToggle) archToggle.addEventListener('change', () => { showArchived = archToggle.checked; load(); });

  $('estadosList').addEventListener('click', async (e) => {
    if (e.target.closest('[data-retry]')) { load(); return; }
    const ren = e.target.closest('[data-rename]');
    if (ren) {
      const name = await showPrompt('Nuevo nombre del estado:', { title: 'Renombrar estado', defaultValue: ren.dataset.name, confirmLabel: 'Guardar' });
      if (!name || name === ren.dataset.name) return;
      try { await busy(ren, () => send(`/api/event-states/${ren.dataset.rename}`, 'PATCH', { name })); showToast('Estado renombrado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    const arch = e.target.closest('[data-archive]');
    if (arch) {
      if (!(await showConfirm(`¿Archivar el estado «${esc(arch.dataset.name)}»? Deja de ofrecerse en los menús. No se puede si algún evento lo usa o si es el último activo de su estado base. Un administrador puede restaurarlo.`, { confirmLabel: 'Archivar' }))) return;
      try { await busy(arch, () => send(`/api/event-states/${arch.dataset.archive}/archive`, 'POST')); showToast('Estado archivado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    const rest = e.target.closest('[data-restore]');
    if (rest) {
      try { await busy(rest, () => send(`/api/event-states/${rest.dataset.restore}/restore`, 'POST')); showToast('Estado restaurado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    const del = e.target.closest('[data-del]');
    if (del) {
      if (!(await showConfirm(`¿Eliminar DEFINITIVAMENTE el estado «${esc(del.dataset.name)}»? No se puede deshacer y queda registrado.`, { confirmLabel: 'Eliminar definitivamente' }))) return;
      try { await busy(del, () => send(`/api/event-states/${del.dataset.del}`, 'DELETE')); showToast('Estado eliminado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    }
  });

  // se carga al abrir la pestaña (no antes: no pega al servidor si nadie la mira)
  let loaded = false;
  const start = () => { if (!loaded) { loaded = true; load(); } };
  const tab = $('tab_estados');
  if (tab) tab.addEventListener('click', start);
  if (!root.hidden) start();
})();
