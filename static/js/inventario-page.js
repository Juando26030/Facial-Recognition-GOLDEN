/* Pantalla /inventario (Fase 5): para las cuentas solo de almacén o contabilidad (sin listado de eventos). Lista los eventos y monta el bloque de inventario de GWInvPlan; lo que cada rol puede
   editar lo decide el servidor (el propio bloque trae su botón Guardar). Delegación de eventos, texto escapado, mensajes con showToast. */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const STATUS = { creado: 'Creado', en_proceso: 'En proceso', finalizado: 'Finalizado' };
  const list = document.getElementById('invEvents');
  const panel = document.getElementById('invPanel');
  const box = document.getElementById('invPlanBox');
  const search = document.getElementById('invSearch');
  const icons = (document.currentScript && document.currentScript.dataset.icons) || '/static/img/icons.svg';
  let ctrl = null, currentId = null, timer = null;

  async function loadEvents() {
    list.setAttribute('aria-busy', 'true');
    try {
      const res = await fetch('/api/inventory/events?q=' + encodeURIComponent(search.value.trim()));
      if (!res.ok) throw new Error('No se pudo cargar la lista de eventos');
      const d = await res.json();
      if (!d.events.length) { list.innerHTML = '<div class="gw-state" role="status"><p class="gw-state__title">No hay eventos para mostrar</p></div>'; return; }
      list.innerHTML = '<ul class="gw-list">' + d.events.map((e) => `<li class="gw-list__item"><div><strong>${esc(e.name)}</strong> <span class="gw-hint">${esc(e.code)} · ${esc(STATUS[e.status] || e.status)}${e.start_date ? ' · ' + esc(e.start_date) : ''}</span></div>` +
        `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-open="${e.id}" data-name="${esc(e.name)}">Abrir inventario</button></li>`).join('') + '</ul>';
    } catch (err) {
      list.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`;
    } finally { list.setAttribute('aria-busy', 'false'); }
  }

  async function openEvent(id, name) {
    if (ctrl && ctrl.dirty() && !(await showConfirm('Hay cambios sin guardar en el inventario abierto. ¿Descartarlos y abrir otro evento?', { variant: 'warning', confirmLabel: 'Descartar' }))) return;
    currentId = id;
    document.getElementById('invPanelTitle').textContent = name;
    panel.hidden = false;
    ctrl = await window.GWInvPlan.mount(box, { eventId: id, icons, onChange: () => {} });
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  list.addEventListener('click', (e) => { const b = e.target.closest('[data-open]'); if (b) openEvent(Number(b.dataset.open), b.dataset.name); });
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(loadEvents, 300); });
  loadEvents();
})();
