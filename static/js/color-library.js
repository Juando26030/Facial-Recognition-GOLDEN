/* Librería de colores de pañoleta (2026-09-23): junto al selector de color de un evento agrega una lista
   "Colores guardados" (elegir uno rellena el color y su nombre) y botones para guardar el color actual
   con su nombre o quitar el elegido de la librería. Un color se define una sola vez y sirve en todos los
   eventos; el evento igual guarda su propia copia. Uso: ColorLibrary.attach(colorInput, nameInput). */
(function () {
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function attach(colorInput, nameInput) {
    const box = document.createElement('div');
    box.className = 'gw-actions';
    box.innerHTML = `
      <select class="gw-select cl-select" aria-label="Colores guardados"></select>
      <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm cl-save">Guardar este color</button>
      <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm cl-del" title="Archivar (quitar de la librería)" aria-label="Archivar el color elegido"><svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="/static/img/icons.svg#i-trash"/></svg></button>
      <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm cl-restore" hidden>Restaurar</button>
      <button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm cl-hard" hidden>Eliminar definitivamente</button>
      <label class="gw-check cl-arch-wrap" hidden><input type="checkbox" class="cl-arch"> Ver archivados</label>`;
    // Va debajo de la fila que contiene el color y el nombre.
    const row = colorInput.closest('.badge-input-row, .ee-row') || colorInput.parentElement.parentElement;
    row.insertAdjacentElement('afterend', box);
    const select = box.querySelector('.cl-select');
    const canArchive = !window.STAFF_ROLE || ['coordinador', 'comercial', 'admin', 'super_admin'].includes(window.STAFF_ROLE);          // archivar / restaurar / «Ver archivados» = coordinador+ (cambio 7-nov)
    if (!canArchive) box.querySelector('.cl-del').hidden = true;
    const isSuper = window.STAFF_ROLE === 'super_admin';
    const archBox = box.querySelector('.cl-arch');
    if (window.STAFF_ROLE && canArchive) box.querySelector('.cl-arch-wrap').hidden = false;          // «Ver archivados»: coordinador+
    let colors = [];
    const archived = () => archBox.checked;
    function syncButtons() {          // en «Ver archivados» el elegido se restaura (coordinador+) o se borra del todo (super_admin); si no, se archiva
      box.querySelector('.cl-del').hidden = !canArchive || archived();
      box.querySelector('.cl-save').hidden = archived();
      box.querySelector('.cl-restore').hidden = !archived();
      box.querySelector('.cl-hard').hidden = !(archived() && isSuper);
    }

    async function reload(selectId) {
      try {
        const res = await fetch('/api/colors' + (archived() ? '?include_archived=true' : ''));
        colors = res.ok ? await res.json() : [];
        if (archived()) colors = colors.filter((c) => c.archived);
      } catch (e) { colors = []; }
      select.innerHTML = `<option value="">${archived() ? 'Colores archivados…' : 'Colores guardados…'}</option>` +
        colors.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.hex)})</option>`).join('');
      if (selectId) select.value = String(selectId);
    }

    select.addEventListener('change', () => {
      const c = colors.find((x) => String(x.id) === select.value);
      if (!c || archived()) return;
      colorInput.value = c.hex;
      nameInput.value = c.name;
    });
    box.querySelector('.cl-save').addEventListener('click', async () => {
      const name = nameInput.value.trim();
      if (!name) { showToast('Escribe el nombre del color (ej. Rojo Golden) para guardarlo', 'error'); return; }
      const res = await fetch('/api/colors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, hex: colorInput.value }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showToast(data.detail || 'No se pudo guardar el color', 'error'); return; }
      await reload(data.id);
      showToast(`Color «${data.name}» guardado — ya lo puedes elegir en cualquier evento`, 'success');
    });
    box.querySelector('.cl-del').addEventListener('click', async () => {
      if (!select.value) { showToast('Elige primero un color de la lista', 'error'); return; }
      const c = colors.find((x) => String(x.id) === select.value);
      if (!(await showConfirm(`¿Archivar «${c ? c.name : 'este color'}»? Se quita de la lista de colores guardados; los eventos que ya lo usan no cambian y un coordinador o superior puede restaurarlo.`, { variant: 'warning', confirmLabel: 'Sí, archivar' }))) return;
      const res = await fetch(`/api/colors/${select.value}/archive`, { method: 'POST' });
      if (!res.ok) { showToast((await res.json().catch(() => ({}))).detail || 'No se pudo archivar', 'error'); return; }
      showToast('Color archivado', 'success');
      await reload();
    });
    archBox.addEventListener('change', () => { syncButtons(); reload(); });
    box.querySelector('.cl-restore').addEventListener('click', async () => {
      if (!select.value) { showToast('Elige primero un color archivado', 'error'); return; }
      const res = await fetch(`/api/colors/${select.value}/restore`, { method: 'POST' });
      if (!res.ok) { showToast((await res.json().catch(() => ({}))).detail || 'No se pudo restaurar', 'error'); return; }
      showToast('Color restaurado: ya está en la lista de colores guardados', 'success');
      await reload();
    });
    box.querySelector('.cl-hard').addEventListener('click', async () => {
      if (!select.value) { showToast('Elige primero un color archivado', 'error'); return; }
      const c = colors.find((x) => String(x.id) === select.value);
      if (!(await showConfirm(`¿Eliminar DEFINITIVAMENTE «${c ? c.name : 'este color'}» de la librería? No se puede deshacer (los eventos que ya lo usan guardan su propia copia) y queda registrado.`, { variant: 'danger', confirmLabel: 'Eliminar definitivamente' }))) return;
      const res = await fetch(`/api/colors/${select.value}`, { method: 'DELETE' });
      if (!res.ok) { showToast((await res.json().catch(() => ({}))).detail || 'No se pudo eliminar', 'error'); return; }
      showToast('Color eliminado de la librería', 'success');
      await reload();
    });
    syncButtons();
    reload();
  }

  window.ColorLibrary = { attach };
})();
