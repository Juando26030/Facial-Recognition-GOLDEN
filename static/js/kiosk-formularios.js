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
  let canTransfer = false;          // exportar / importar: solo admin y super_admin (el servidor lo exige igual)
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());
  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.detail || 'Error'); return d; }

  function card(f) {
    const meta = [`Inscripciones: ${f.submissions}`];
    if (f.test_submissions) meta.push(`+${f.test_submissions} de prueba`);
    if (f.preregistered) meta.push(`+${f.preregistered} ya registradas desde la base`);
    const cupo = f.capacity == null ? 'sin límite' : f.capacity;
    return `<article class="gw-card-row" data-form="${f.id}">
      <div class="gw-card-row__head">
        <a class="gw-card-row__title" href="/kiosk/${EV}/formularios/${f.id}">${esc(f.name)}</a>
        <span class="gw-badge ${BADGE[f.public_state] || ''}">${esc(LABELS[f.public_state] || f.public_state)}</span>
      </div>
      <p class="gw-card-row__meta">/${esc(f.slug)}${f.use_schedule ? ' · por calendario' : ''}</p>
      <p class="gw-card-row__meta">${esc(meta.join(' · '))} · Cupo: ${esc(cupo)}</p>
      <div class="gw-card-row__actions">
        <a class="gw-btn gw-btn--secondary gw-btn--sm" href="/kiosk/${EV}/formularios/${f.id}">${icon('edit')} Editar</a>
        <a class="gw-btn gw-btn--secondary gw-btn--sm" href="/kiosk/${EV}/formularios/${f.id}/estadisticas">${icon('chart')} Estadísticas</a>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-copy="${esc(f.public_url)}">${icon('link')} Copiar enlace</button>
      </div>
      <div class="gw-card-row__actions">
        <a class="gw-btn gw-btn--ghost gw-btn--sm" href="${esc(f.test_url)}" target="_blank" rel="noopener">${icon('eye')} Probar</a>
        <button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-dup="${f.id}">Duplicar</button>
        ${canTransfer ? `<a class="gw-btn gw-btn--ghost gw-btn--sm" href="${api}/forms/${f.id}/export" data-export>${icon('download')} Exportar formulario</a>` : ''}
        <button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-del="${f.id}" data-name="${esc(f.name)}">${icon('trash')} Eliminar</button>
      </div>
    </article>`;
  }

  async function load() {
    const box = $('body');
    box.setAttribute('aria-busy', 'true');
    try {
      const forms = await j(`${api}/forms`);
      box.innerHTML = forms.map(card).join('') || `<div class="gw-empty" role="status"><p>Este evento todavía no tiene formularios.</p><p class="gw-hint">Crea el primero arriba con «Crear y editar»${canTransfer ? ' o impórtalo desde otro entorno' : ''}.</p></div>`;
    } catch (e) {
      box.innerHTML = `<div class="gw-alert gw-alert--err" role="alert"><div>No se pudo cargar la lista: ${esc(e.message)}. Recarga la página; si sigue igual, avisa a un administrador.</div></div>`;
    } finally { box.setAttribute('aria-busy', 'false'); }
  }

  $('body').addEventListener('click', async (e) => {
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
    const del = e.target.closest('[data-del]');
    if (del) {
      if (!(await showConfirm(`¿Eliminar el formulario «${window.escapeHtml(del.dataset.name)}» con TODAS sus inscripciones y archivos? No se puede deshacer.`, { confirmLabel: 'Eliminar' }))) return;
      try { await busy(del, () => j(`${api}/forms/${del.dataset.del}`, { method: 'DELETE' })); showToast('Formulario eliminado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    }
  });

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
