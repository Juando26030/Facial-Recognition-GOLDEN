/* Tipos de evento (Configuración → «Tipos de evento», solo super_admin): agregar, renombrar, color opcional, archivar y restaurar. API: /api/event-types (app/routers/event_types.py).
   Archivar no toca los eventos que ya tienen el tipo. Las reglas del servidor llegan como mensaje y se muestran con showToast. */
(function () {
  'use strict';
  const root = document.getElementById('tipos');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const ICONS = root.dataset.icons || '/static/img/icons.svg';
  const icon = (n) => `<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${ICONS}#i-${n}"/></svg>`;
  const HEX = /^#[0-9a-fA-F]{6}$/;
  if ($('typeColor')) $('typeColor').value = '#D4AF37';
  let showArchived = false;

  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error'); return d; }
  const send = (url, method, body) => j(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());

  function row(t) {
    const using = t.events_using ? `${t.events_using} ${t.events_using === 1 ? 'evento' : 'eventos'}` : 'Sin eventos';
    const btns = [];
    if (!t.archived) {
      btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-rename="${t.id}" data-name="${esc(t.name)}" aria-label="Renombrar ${esc(t.name)}">${icon('edit')} Renombrar</button>`);
      btns.push(`<label class="gw-check gw-check--inline"><input type="color" class="gw-config__swatch" data-color-of="${t.id}" value="${HEX.test(t.color) ? esc(t.color) : '#D4AF37'}" aria-label="Color de ${esc(t.name)}"></label>`);
      if (t.color) btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-nocolor="${t.id}" aria-label="Quitar el color de ${esc(t.name)}">Quitar color</button>`);
      btns.push(`<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-archive="${t.id}" data-name="${esc(t.name)}" aria-label="Archivar ${esc(t.name)}">${icon('trash')} Archivar</button>`);
    } else {
      btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-restore="${t.id}" aria-label="Restaurar ${esc(t.name)}">${icon('undo')} Restaurar</button>`);
    }
    return `<article class="gw-card-row" data-type="${t.id}">
      <div class="gw-card-row__head"><span class="gw-card-row__title"><span class="gw-estado__dot" data-color="${esc(t.color || '')}" aria-hidden="true"></span> ${esc(t.name)}</span></div>
      <p class="gw-card-row__meta">${using}${t.archived ? ' · Archivado' : ''}</p>
      <div class="gw-card-row__actions">${btns.join('')}</div>
    </article>`;
  }
  function paintDots() { root.querySelectorAll('.gw-estado__dot').forEach((d) => { const c = d.dataset.color; if (HEX.test(c)) d.style.setProperty('--gw-estado-color', c); else d.hidden = true; }); }

  async function load() {
    const box = $('tiposList');
    box.setAttribute('aria-busy', 'true');
    try {
      const d = await j(`/api/event-types?include_archived=true`, { cache: 'no-store' });
      const list = d.types.filter((t) => t.archived === showArchived);
      box.innerHTML = list.map(row).join('') || (showArchived
        ? '<div class="gw-state" role="status"><p class="gw-state__title">No hay tipos archivados</p><p class="gw-state__text">Cuando archives uno, aparecerá aquí para poder restaurarlo.</p></div>'
        : '<div class="gw-state" role="status"><p class="gw-state__title">Todavía no hay tipos de evento</p><p class="gw-state__text">Agrega el primero con el formulario de arriba.</p></div>');
      paintDots();
    } catch (e) {
      box.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudieron cargar los tipos de evento</p><p class="gw-state__text">${esc(e.message)}. Inténtalo de nuevo.</p><button type="button" class="gw-btn gw-btn--secondary" data-retry>Reintentar</button></div>`;
    } finally { box.setAttribute('aria-busy', 'false'); }
  }

  $('typeForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('typeName').value.trim();
    if (!name) { showToast('Escribe el nombre del tipo de evento', 'error'); return; }
    try {
      await busy($('typeCreateBtn'), () => send('/api/event-types', 'POST', { name, color: $('typeUseColor').checked ? $('typeColor').value : null }));
      $('typeName').value = '';
      showToast(`Tipo «${name}» agregado`, 'success');
      load();
    } catch (err) { showToast(err.message, 'error'); }
  });
  const archToggle = $('showArchivedTypes');
  if (archToggle) archToggle.addEventListener('change', () => { showArchived = archToggle.checked; load(); });

  $('tiposList').addEventListener('change', async (e) => {
    const c = e.target.closest('[data-color-of]');
    if (!c) return;
    try { await send(`/api/event-types/${c.dataset.colorOf}`, 'PATCH', { color: c.value }); showToast('Color guardado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
  });
  $('tiposList').addEventListener('click', async (e) => {
    if (e.target.closest('[data-retry]')) { load(); return; }
    const ren = e.target.closest('[data-rename]');
    if (ren) {
      const name = await showPrompt('Nuevo nombre del tipo de evento:', { title: 'Renombrar tipo', defaultValue: ren.dataset.name, confirmLabel: 'Guardar' });
      if (!name || name === ren.dataset.name) return;
      try { await busy(ren, () => send(`/api/event-types/${ren.dataset.rename}`, 'PATCH', { name })); showToast('Tipo renombrado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    const nc = e.target.closest('[data-nocolor]');
    if (nc) { try { await busy(nc, () => send(`/api/event-types/${nc.dataset.nocolor}`, 'PATCH', { color: '' })); load(); } catch (err) { showToast(err.message, 'error'); } return; }
    const arch = e.target.closest('[data-archive]');
    if (arch) {
      if (!(await showConfirm(`¿Archivar el tipo «${esc(arch.dataset.name)}»? Deja de ofrecerse al crear o editar eventos; los eventos que ya lo tienen lo conservan. Se puede restaurar.`, { confirmLabel: 'Archivar' }))) return;
      try { await busy(arch, () => send(`/api/event-types/${arch.dataset.archive}/archive`, 'POST')); showToast('Tipo archivado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    const rest = e.target.closest('[data-restore]');
    if (rest) { try { await busy(rest, () => send(`/api/event-types/${rest.dataset.restore}/restore`, 'POST')); showToast('Tipo restaurado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); } }
  });

  let loaded = false;
  const start = () => { if (!loaded) { loaded = true; load(); } };
  const tab = $('tab_tipos');
  if (tab) { tab.addEventListener('click', start); tab.addEventListener('gw:tabshow', start); }
  if (!root.hidden) start();
})();
