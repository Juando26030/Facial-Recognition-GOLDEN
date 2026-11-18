/* Opciones de «Categoría (tipo de evento)» dentro del diseñador de la plantilla de evento (panel de propiedades del campo, debajo de «Obligatorio»).
   Es la MISMA lista que Configuración › Tipos de evento (tabla event_types, /api/event-types): lo que se cambie aquí se ve de inmediato en el selector de
   Nuevo evento / Editar evento y en los chips del calendario. Agregar, renombrar (ventana propia), archivar y restaurar actúan al instante; el COLOR queda pendiente hasta el «Guardar cambios» de la barra única (GWParams, clave «tipos_color»).
   Agregar, renombrar, cambiar color, archivar y restaurar: solo super_admin; los demás administradores ven la lista. */
(function (root) {
  'use strict';
  const esc = (t) => (root.escapeHtml ? root.escapeHtml(String(t == null ? '' : t)) : String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
  const HEX = /^#[0-9a-fA-F]{6}$/;
  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error'); return d; }
  const send = (url, method, body) => j(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const pending = {};            // id -> color elegido y sin guardar (vive aquí porque el panel de propiedades se vuelve a pintar al cambiar de campo)
  const colorOf = (t) => (Object.prototype.hasOwnProperty.call(pending, t.id) ? pending[t.id] : (t.color || ''));
  let registered = false, reloadCurrent = null;
  const toast = (m, k) => { if (root.showToast) root.showToast(m, k || 'info'); };

  function mount(box, opts) {
    const canEdit = !!(opts && opts.canEdit), icons = (opts && opts.icons) || '';
    const icon = (n) => '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="' + esc(icons) + '#i-' + n + '"/></svg>';
    let showArchived = false;
    box.setAttribute('data-pnodirty', '');          // lo escrito aquí no marca pendiente la plantilla; el color tiene su propio bloque
    if (!registered && root.GWParams && canEdit) {
      registered = true;
      root.GWParams.register({ key: 'tipos_color', label: 'Colores de las categorías de evento', order: 5, save: async () => {
        for (const id of Object.keys(pending)) { await send('/api/event-types/' + id, 'PATCH', { color: pending[id] }); delete pending[id]; }
        if (reloadCurrent) await reloadCurrent();
      } });
    }
    box.innerHTML = '<p class="gw-hint">Es la misma lista de «Configuración › Tipos de evento». ' + (canEdit ? 'Agregar, renombrar y archivar actúan al instante; el color se guarda con «Guardar cambios». Se ven en el selector de eventos y en los chips del calendario.' : 'Solo un super administrador puede cambiarla.') + '</p>' +
      (canEdit ? '<form class="gw-tpl-evt__add" data-evt-form><input class="gw-input" type="text" maxlength="80" placeholder="Nueva opción (ej. Feria)" aria-label="Nombre de la nueva opción" data-evt-name autocomplete="off" required>' +
        '<button type="submit" class="gw-btn gw-btn--secondary gw-btn--sm">' + icon('plus') + ' Agregar</button></form>' +
        '<label class="gw-check"><input type="checkbox" data-evt-arch> Ver archivadas</label>' : '') +
      '<ul class="gw-tpl-evt__list" data-evt-list aria-live="polite"><li class="gw-hint">Cargando…</li></ul>';
    const list = box.querySelector('[data-evt-list]');
    function row(t) {
      const using = t.events_using ? t.events_using + (t.events_using === 1 ? ' evento' : ' eventos') : 'Sin eventos';
      const tools = !canEdit ? '' : t.archived
        ? '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-evt-restore="' + t.id + '" aria-label="Restaurar ' + esc(t.name) + '">Restaurar</button>'
        : '<input type="color" class="gw-config__swatch" data-evt-color="' + t.id + '" value="' + (HEX.test(colorOf(t)) ? esc(colorOf(t)) : '#D4AF37') + '" aria-label="Color de ' + esc(t.name) + '">' +
          '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-evt-rename="' + t.id + '" data-name="' + esc(t.name) + '" aria-label="Renombrar ' + esc(t.name) + '">' + icon('edit') + '</button>' +
          '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-evt-archive="' + t.id + '" data-name="' + esc(t.name) + '" aria-label="Archivar ' + esc(t.name) + '">' + icon('trash') + '</button>';
      return '<li class="gw-tpl-evt__row"><span class="gw-tpl-evt__name">' + esc(t.name) + (t.archived ? ' <small class="gw-hint">(archivada)</small>' : '') + ' <small class="gw-hint">' + using + '</small></span><span class="gw-tpl-evt__tools">' + tools + '</span></li>';
    }
    async function load() {
      try {
        const d = await j('/api/event-types' + (canEdit ? '?include_archived=true' : ''), { cache: 'no-store' });
        const rows = d.types.filter((t) => t.archived === showArchived);
        list.innerHTML = rows.map(row).join('') || '<li class="gw-hint">' + (showArchived ? 'No hay opciones archivadas.' : 'Todavía no hay opciones: eventos sin categoría salen como «Sin categoría».') + '</li>';
      } catch (e) { list.innerHTML = '<li class="gw-hint" role="alert">No se pudo cargar la lista (' + esc(e.message) + ').</li>'; }
    }
    async function run(fn, okMsg) { try { await fn(); if (okMsg) toast(okMsg, 'success'); await load(); } catch (err) { toast(err.message, 'error'); } }
    box.addEventListener('submit', (e) => {
      const f = e.target.closest('[data-evt-form]'); if (!f) return;
      e.preventDefault();
      const inp = f.querySelector('[data-evt-name]'), name = inp.value.trim();
      if (!name) { toast('Escribe el nombre de la opción', 'error'); return; }
      run(async () => { await send('/api/event-types', 'POST', { name }); inp.value = ''; }, 'Opción «' + name + '» agregada');
    });
    box.addEventListener('change', (e) => {
      const a = e.target.closest('[data-evt-arch]'); if (a) { showArchived = a.checked; load(); return; }
      const c = e.target.closest('[data-evt-color]'); if (c) { pending[c.dataset.evtColor] = c.value; if (root.GWParams) root.GWParams.markDirty('tipos_color'); }
    });
    box.addEventListener('click', async (e) => {
      const ren = e.target.closest('[data-evt-rename]');
      if (ren) {
        const name = await root.showPrompt('Nuevo nombre de la opción:', { title: 'Renombrar opción', defaultValue: ren.dataset.name, confirmLabel: 'Guardar' });
        if (name && name !== ren.dataset.name) run(() => send('/api/event-types/' + ren.dataset.evtRename, 'PATCH', { name }), 'Opción renombrada');
        return;
      }
      const arc = e.target.closest('[data-evt-archive]');
      if (arc) {
        if (await root.showConfirm('¿Archivar «' + esc(arc.dataset.name) + '»? Deja de ofrecerse al crear o editar eventos; los eventos que ya la tienen la conservan. Se puede restaurar.', { confirmLabel: 'Archivar' })) run(() => send('/api/event-types/' + arc.dataset.evtArchive + '/archive', 'POST'), 'Opción archivada');
        return;
      }
      const res = e.target.closest('[data-evt-restore]');
      if (res) run(() => send('/api/event-types/' + res.dataset.evtRestore + '/restore', 'POST'), 'Opción restaurada');
    });
    reloadCurrent = load;
    load();
  }
  root.EventTypeOptions = { mount: mount };
})(typeof window !== 'undefined' ? window : globalThis);
