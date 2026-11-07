/* Formularios web (lista) — Fase 1.5. Tarjetas .gw-cards con delegación de eventos (sin onclick en línea). Misma lógica y rutas de siempre. */
(function () {
  'use strict';
  const EV = window.EVENT_ID, api = `/api/events/${EV}`;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const LABELS = { pruebas: 'En pruebas', activo: 'Activo', cerrado: 'Cerrado', cupo_lleno: 'Cupo lleno', finalizado: 'Finalizado' };
  const BADGE = { pruebas: 'gw-badge--warn', activo: 'gw-badge--ok', cerrado: '', cupo_lleno: 'gw-badge--err', finalizado: '' };
  const ICONS = ($('formsRoot') && $('formsRoot').dataset.icons) || '/static/img/icons.svg';
  const icon = (n) => `<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${ICONS}#i-${n}"/></svg>`;
  const ROLE = window.STAFF_ROLE || '', isAdmin = ROLE === 'admin' || ROLE === 'super_admin', isSuper = ROLE === 'super_admin';
  let showArchived = false;          // «Ver archivados» (admin+)
  let canTransfer = false;          // exportar / importar: solo admin y super_admin (el servidor lo exige igual)
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());
  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.detail || 'Error'); return d; }

  function card(f) {
    const extra = [];
    if (f.test_submissions) extra.push(`+${f.test_submissions} de prueba`);
    if (f.preregistered) extra.push(`+${f.preregistered} ya registradas desde la base`);
    const cupo = f.capacity == null ? 'Sin límite' : f.capacity;
    return `<article class="gw-card-row" data-form="${f.id}">
      <div class="gw-card-row__head">
        <a class="gw-card-row__title" href="/kiosk/${EV}/formularios/${f.id}">${esc(f.name)}</a>
        <span class="gw-badge ${BADGE[f.public_state] || ''}">${esc(LABELS[f.public_state] || f.public_state)}${f.use_schedule ? ' · calendario' : ''}</span>
      </div>
      <p class="gw-card-row__meta">/${esc(f.slug)}${f.use_schedule ? ' · por calendario' : ''}</p>
      <div class="gw-stats-row gw-stats-row--2">
        <div class="gw-stat"><span class="gw-stat__value">${esc(f.submissions)}</span><span class="gw-stat__label">Inscripciones</span>${extra.length ? `<span class="gw-stat__hint" title="${esc(extra.join(' · '))}">${esc(extra.join(' · '))}</span>` : ''}</div>
        <div class="gw-stat"><span class="gw-stat__value">${esc(cupo)}</span><span class="gw-stat__label">Cupo</span></div>
      </div>
      <div class="gw-card-row__actions">
        <a class="gw-btn gw-btn--secondary gw-btn--sm" href="/kiosk/${EV}/formularios/${f.id}">${icon('edit')} Editar</a>
        <a class="gw-btn gw-btn--secondary gw-btn--sm" href="/kiosk/${EV}/formularios/${f.id}/estadisticas" title="Estadísticas">${icon('chart')} <span class="gw-forms-lbl">Estadísticas</span></a>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-copy="${esc(f.public_url)}" title="Copiar enlace">${icon('link')} <span class="gw-forms-lbl">Copiar enlace</span></button>
        ${f.archived
    ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-restore="${f.id}" data-name="${esc(f.name)}">Restaurar</button>${isSuper ? `<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-del="${f.id}" data-name="${esc(f.name)}" title="Eliminar definitivamente" aria-label="Eliminar definitivamente ${esc(f.name)}">${icon('trash')} <span class="gw-forms-lbl">Eliminar definitivamente</span></button>` : ''}`
    : (isAdmin ? `<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-archive="${f.id}" data-name="${esc(f.name)}" title="Archivar" aria-label="Archivar ${esc(f.name)}">${icon('trash')} <span class="gw-forms-lbl">Archivar</span></button>` : '')}
        <div class="gw-menu gw-forms-kebab">
          <button type="button" class="gw-btn gw-btn--secondary gw-forms-kebab__btn" data-menu aria-haspopup="true" aria-expanded="false" aria-label="Más acciones de ${esc(f.name)}" title="Más acciones">${icon('more')}</button>
          <div class="gw-menu__panel" role="group" hidden>
            <a class="gw-menu__item" href="${esc(f.test_url)}" target="_blank" rel="noopener">${icon('eye')} Probar</a>
            <button type="button" class="gw-menu__item" data-dup="${f.id}">${icon('form')} Duplicar</button>
            ${canTransfer ? `<a class="gw-menu__item" href="${api}/forms/${f.id}/export" data-export>${icon('download')} Exportar formulario</a>` : ''}
          </div>
        </div>
      </div>
    </article>`;
  }

  async function load() {
    const box = $('body');
    box.setAttribute('aria-busy', 'true');
    try {
      const forms = await j(`${api}/forms${showArchived && isAdmin ? '?include_archived=true' : ''}`);
      box.innerHTML = forms.map(card).join('') || (showArchived ? '<div class="gw-state" role="status"><p class="gw-state__title">No hay formularios archivados</p><p class="gw-state__text">Cuando archives uno, aparecerá aquí para poder restaurarlo.</p></div>' : `<div class="gw-state" role="status"><p class="gw-state__title">Este evento todavía no tiene formularios</p><p class="gw-state__text">Crea el primero arriba con «Crear formulario»${canTransfer ? ' o impórtalo desde otro entorno' : ''}.</p></div>`);
    } catch (e) {
      box.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudo cargar la lista</p><p class="gw-state__text">${esc(e.message)}. Inténtalo de nuevo; si sigue igual, avisa a un administrador.</p><button type="button" class="gw-btn gw-btn--secondary" data-retry>Reintentar</button></div>`;
    } finally { box.setAttribute('aria-busy', 'false'); }
  }

  // Menú «tres puntos» de cada tarjeta (Probar · Duplicar · Exportar · Eliminar)
  let openMenu = null;
  function closeMenu() { if (!openMenu) return; openMenu.panel.hidden = true; openMenu.btn.setAttribute('aria-expanded', 'false'); openMenu = null; }
  document.addEventListener('click', (e) => { if (openMenu && !e.target.closest('.gw-menu')) closeMenu(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && openMenu) { const b = openMenu.btn; closeMenu(); b.focus(); } });
  function toggleMenu(btn) {
    const wrap = btn.closest('.gw-menu'), panel = wrap.querySelector('.gw-menu__panel');
    const was = openMenu && openMenu.panel === panel; closeMenu();
    if (was) return;
    panel.hidden = false; btn.setAttribute('aria-expanded', 'true'); openMenu = { panel, btn };
    const r = btn.getBoundingClientRect();
    wrap.classList.toggle('gw-menu--up', r.bottom + panel.offsetHeight > window.innerHeight && r.top > panel.offsetHeight);
    const first = panel.querySelector('.gw-menu__item'); if (first) first.focus();
  }

  $('body').addEventListener('click', async (e) => {
    const kebab = e.target.closest('[data-menu]');
    if (kebab) { toggleMenu(kebab); return; }
    if (e.target.closest('.gw-menu__item')) closeMenu();
    if (e.target.closest('[data-retry]')) { load(); return; }
    const copy = e.target.closest('[data-copy]');
    if (copy) {
      try { await navigator.clipboard.writeText(copy.dataset.copy); } catch (err) { /* sin portapapeles: se avisa igual */ }
      showToast('Enlace copiado (el formulario público solo abre cuando está en estado Activo)', 'success');
      return;
    }
    const dup = e.target.closest('[data-dup]');
    if (dup) {
      try { await busy(dup, () => j(`${api}/forms/${dup.dataset.dup}/duplicate`, { method: 'POST' })); showToast('Formulario duplicado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    const arch = e.target.closest('[data-archive]');
    if (arch) {
      if (!(await showConfirm(`¿Archivar el formulario «${window.escapeHtml(arch.dataset.name)}»? Deja de recibir envíos y se oculta de la lista; las respuestas y los pagos se conservan y un administrador puede restaurarlo desde «Ver archivados».`, { confirmLabel: 'Archivar' }))) return;
      try { await busy(arch, () => j(`${api}/forms/${arch.dataset.archive}/archive`, { method: 'POST' })); showToast('Formulario archivado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    const rest = e.target.closest('[data-restore]');
    if (rest) {
      try { await busy(rest, () => j(`${api}/forms/${rest.dataset.restore}/restore`, { method: 'POST' })); showToast('Formulario restaurado (queda cerrado)', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    const del = e.target.closest('[data-del]');
    if (del) {
      if (!(await showConfirm(`¿Eliminar DEFINITIVAMENTE el formulario «${window.escapeHtml(del.dataset.name)}»? Solo se puede si no tiene inscripciones ni pagos. No se puede deshacer y queda registrado.`, { confirmLabel: 'Eliminar definitivamente' }))) return;
      try { await busy(del, () => j(`${api}/forms/${del.dataset.del}`, { method: 'DELETE' })); showToast('Formulario eliminado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    }
  });

  const archToggle = $('showArchivedForms');
  if (archToggle) archToggle.addEventListener('change', () => { showArchived = archToggle.checked; load(); });

  $('importBtn').addEventListener('click', async () => {
    const file = $('importFile').files[0];
    if (!file) { showToast('Elige el archivo .zip del formulario exportado', 'error'); return; }
    const send = async (url) => { const fd = new FormData(); fd.append('file', file); return j(url, { method: 'POST', body: fd }); };
    try {
      await busy($('importBtn'), async () => {
        const p = await send(`${api}/forms-import/preview`);
        const extra = [
          p.optional_created.length ? `Campos opcionales que se CREARÁN en este evento: ${p.optional_created.map(esc).join(', ')}.` : '',
          p.optional_reused.length ? `Campos opcionales que ya existen y se usarán: ${p.optional_reused.map(esc).join(', ')}.` : '',
          p.notes.length ? `Avisos: ${p.notes.map(esc).join(' ')}` : '',
        ].filter(Boolean).join('<br><br>');
        if (!(await showConfirm(`${esc(p.summary)}${extra ? '<br><br>' + extra : ''}<br><br>¿Crear el formulario?`, { confirmLabel: 'Sí, importar', variant: 'warning' }))) return;
        const out = await send(`${api}/forms-import`);
        showToast(`Formulario importado: «${out.name}» (en pruebas)` + (out.optional_created.length ? ` · campos opcionales creados: ${out.optional_created.join(', ')}` : ''), 'success');
        $('importFile').value = '';
        load();
      });
    } catch (err) { showToast(err.message, 'error'); }
  });

  $('newForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await busy($('newBtn'), async () => {
        const body = { name: $('newName').value, template_id: $('newTemplate').value ? +$('newTemplate').value : undefined };
        const f = await j(`${api}/forms`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        location.href = `/kiosk/${EV}/formularios/${f.id}`;
        return new Promise(() => {});   // la página se va: el botón sigue girando hasta entonces
      });
    } catch (err) { showToast(err.message, 'error'); }
  });

  (async () => {
    try { canTransfer = (await j(`${api}/forms-transfer/allowed`)).allowed; } catch (e) { canTransfer = false; }
    $('importCard').hidden = !canTransfer;
    try {
      const tpls = await j(`${api}/form-templates`);
      $('newTemplate').insertAdjacentHTML('beforeend', tpls.map((t) => `<option value="${t.id}">Plantilla: ${esc(t.name)} (${t.fields} elementos)</option>`).join(''));
    } catch (e) { /* sin plantillas: queda «Formulario nuevo» */ }
    load();
  })();
})();
