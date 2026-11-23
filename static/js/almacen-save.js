/* Almacén (Inventario → pestañas «Almacén» y «Administrar catálogo»): el botón grande «Guardar cambios» es el ÚNICO medio para guardar lo que se edita en línea (seriales de los objetos,
   casillas y observaciones del checklist), igual que en Parámetros del evento. Las acciones (agregar, archivar, anular, resolver una novedad…) siguen siendo inmediatas con su confirmación.
   Uso: GWAlmSave.mark(clave, 'Nombre del cambio', async () => { …llama a la API y lanza Error si falla… }); GWAlmSave.clean(clave); GWAlmSave.saveAll(); GWAlmSave.hasDirty().
   Barra: #almSaveBar (misma .gw-savebar del sistema), pegajosa abajo; Ctrl/Cmd+S guarda; avisa al salir con cambios pendientes. Sin DOM de barra, el módulo no hace nada. */
(function (root) {
  'use strict';
  const doc = root.document;
  const bar = doc.getElementById('almSaveBar');
  if (!bar) return;
  const btn = doc.getElementById('almSaveBtn');
  const statusEl = doc.getElementById('almSaveStatus');
  const failEl = doc.getElementById('almSaveFail');
  const ICONS = (bar.dataset.icons || '').replace(/"/g, '');
  const mods = new Map();          // clave -> { label, save, rev }
  const dirty = new Set();
  let busy = false;
  let state = 'idle';          // idle | dirty | saving | saved | error
  let failed = [];
  const icon = (n) => `<svg class="gw-icon" aria-hidden="true"><use href="${ICONS}#i-${n}"></use></svg>`;

  function render() {
    bar.dataset.state = state;
    btn.disabled = busy || (state !== 'dirty' && state !== 'error');
    if (busy) btn.setAttribute('aria-busy', 'true'); else btn.removeAttribute('aria-busy');
    if (state === 'dirty') {
      const labels = Array.from(dirty).map((k) => (mods.get(k) || {}).label).filter(Boolean);
      statusEl.innerHTML = `<span class="gw-savebar__alert">${icon('alert')}Cambios sin guardar</span>`
        + (labels.length ? `<span class="gw-text-sm gw-muted">En: ${root.escapeHtml(labels.slice(0, 4).join(', '))}${labels.length > 4 ? ' y ' + (labels.length - 4) + ' más' : ''}</span>` : '');
    } else {
      const cls = { saved: ' gw-badge--ok', error: ' gw-badge--err', saving: ' gw-badge--info' }[state] || '';
      const ico = { saved: 'check', error: 'error' }[state];
      const txt = { saving: 'Guardando…', saved: 'Guardado', error: 'No todo se guardó' }[state] || 'Sin cambios pendientes';
      statusEl.innerHTML = `<span class="gw-badge${cls}">${ico ? icon(ico) : ''}${txt}</span>`;
    }
    failEl.replaceChildren();
    if (state === 'error') {
      failed.forEach((f) => { const li = doc.createElement('li'); li.textContent = f.label + ': ' + f.error; failEl.appendChild(li); });
      const li = doc.createElement('li'); li.textContent = 'Lo demás sí se guardó. Corrige lo anterior y pulsa «Guardar cambios» otra vez.'; failEl.appendChild(li);
      failEl.hidden = false;
    } else failEl.hidden = true;
  }
  function mark(key, label, save) {
    const m = mods.get(key) || { rev: 0 };
    m.label = label; m.save = save; m.rev += 1;
    mods.set(key, m);
    dirty.add(key);
    if (!busy) { state = 'dirty'; failed = []; }
    render();
  }
  function clean(key) {
    dirty.delete(key); mods.delete(key);
    if (!busy && !dirty.size && (state === 'dirty' || state === 'error')) state = 'idle';
    render();
  }
  async function saveAll() {
    if (busy || !dirty.size) return { saved: [], failed: [] };
    busy = true; state = 'saving'; failed = []; render();
    const done = [];
    for (const key of Array.from(dirty)) {
      const m = mods.get(key);
      if (!m) { dirty.delete(key); continue; }
      const before = m.rev;
      try {
        await m.save();
        if (m.rev === before) { dirty.delete(key); mods.delete(key); }          // si lo editaron mientras se guardaba, sigue pendiente
        done.push(key);
      } catch (e) { failed.push({ key, label: m.label, error: (e && e.message) || 'error' }); }
    }
    busy = false;
    state = failed.length ? 'error' : (dirty.size ? 'dirty' : 'saved');
    render();
    if (typeof root.showToast === 'function') {
      if (failed.length) root.showToast('No se guardó: ' + failed.map((f) => f.label).join(', ') + '. Lo demás sí.', 'error');
      else if (done.length) root.showToast('Cambios guardados', 'success');
    }
    doc.dispatchEvent(new CustomEvent('gw:almacen-saved', { detail: { saved: done, failed: failed.map((f) => f.key) } }));
    return { saved: done, failed: failed.map((f) => f.key) };
  }
  btn.addEventListener('click', saveAll);
  doc.addEventListener('keydown', (e) => {          // Ctrl o Cmd + S guarda (igual que el botón); sin pendientes no hace nada pero tampoco abre «Guardar página como…»
    if (!(e.ctrlKey || e.metaKey) || e.altKey || String(e.key).toLowerCase() !== 's' || bar.hidden) return;
    e.preventDefault();
    if (!btn.disabled) btn.click();
  });
  root.addEventListener('beforeunload', (e) => { if (!dirty.size) return undefined; e.preventDefault(); e.returnValue = ''; return ''; });
  root.GWAlmSave = { mark, clean, saveAll, hasDirty: () => dirty.size > 0 };
  render();
})(window);
