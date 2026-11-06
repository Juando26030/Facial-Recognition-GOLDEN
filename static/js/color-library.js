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
      <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm cl-del" title="Quitar de la librería" aria-label="Quitar de la librería"><svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="/static/img/icons.svg#i-trash"/></svg></button>`;
    // Va debajo de la fila que contiene el color y el nombre.
    const row = colorInput.closest('.badge-input-row, .ee-row') || colorInput.parentElement.parentElement;
    row.insertAdjacentElement('afterend', box);
    const select = box.querySelector('.cl-select');
    let colors = [];

    async function reload(selectId) {
      try {
        const res = await fetch('/api/colors');
        colors = res.ok ? await res.json() : [];
      } catch (e) { colors = []; }
      select.innerHTML = '<option value="">Colores guardados…</option>' +
        colors.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.hex)})</option>`).join('');
      if (selectId) select.value = String(selectId);
    }

    select.addEventListener('change', () => {
      const c = colors.find((x) => String(x.id) === select.value);
      if (!c) return;
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
      if (!confirm(`¿Quitar «${c ? c.name : 'este color'}» de la librería? Los eventos que ya lo usan no cambian.`)) return;
      const res = await fetch(`/api/colors/${select.value}`, { method: 'DELETE' });
      if (!res.ok) { showToast((await res.json().catch(() => ({}))).detail || 'No se pudo quitar', 'error'); return; }
      await reload();
    });
    reload();
  }

  window.ColorLibrary = { attach };
})();
