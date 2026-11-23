/* Tarjeta «Inventario» del quiosco (18-nov-2026): lo alistado para el evento según el checklist de inventario. Solo lectura.
   En la nube lee la base; en un servidor local lee la foto guardada al descargar el evento y, con internet, se puede actualizar. Texto siempre escapado. */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (id) => document.getElementById(id);

  function paint(d) {
    const list = $('alList'), notice = $('alNotice'), stamp = $('alStamp'), refresh = $('alRefresh');
    list.setAttribute('aria-busy', 'false');
    if (refresh) refresh.hidden = d.source !== 'local';
    notice.hidden = !d.warning;
    if (d.warning) notice.textContent = d.warning;
    if (!d.available) {
      list.innerHTML = '<p class="gw-muted">Este servidor todavía no tiene el inventario de este evento. Conéctate a internet y pulsa «Actualizar desde internet».</p>';
      $('alCount').textContent = '';
      return;
    }
    const lines = d.lines || [];
    $('alCount').textContent = lines.length ? '(' + lines.length + ')' : '';
    if (!lines.length) { list.innerHTML = '<p class="gw-muted">No hay elementos asignados a este evento en el checklist de inventario.</p>'; }
    else {
      const groups = new Map();
      lines.forEach((l) => { const k = l.category || 'Sin categoría'; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(l); });
      let html = '';
      groups.forEach((rows, cat) => {
        html += '<h3 class="gw-card__title">' + esc(cat) + '</h3><div class="gw-table-wrap"><table class="gw-table"><thead><tr><th scope="col">Elemento</th><th scope="col">Pedido</th><th scope="col">Salió</th><th scope="col">Volvió</th><th scope="col">Consumido</th><th scope="col">Estado</th></tr></thead><tbody>';
        rows.forEach((l) => {
          const listo = l.assigned > 0 && l.out >= l.assigned;
          html += '<tr><th scope="row">' + esc(l.name) + (l.notes ? '<br><span class="gw-text-sm gw-muted">' + esc(l.notes) + '</span>' : '') + '</th><td>' + esc(l.assigned) + ' <span class="gw-muted">' + esc(l.unit) + '</span></td><td>' + esc(l.out) + '</td><td>' + esc(l.returned) + '</td><td>' + esc(l.consumed) + '</td>'
            + '<td><span class="gw-badge ' + (listo ? 'gw-badge--ok' : 'gw-badge--warn') + '">' + (listo ? 'Alistado' : (l.out > 0 ? 'Parcial' : 'Por alistar')) + '</span></td></tr>';
        });
        html += '</tbody></table></div>';
      });
      list.innerHTML = html;
    }
    if (d.fetched_at) { const f = new Date(d.fetched_at + (/[zZ]|[+-]\d\d:?\d\d$/.test(d.fetched_at) ? '' : 'Z')); stamp.textContent = 'Foto guardada el ' + f.toLocaleString('es-CO') + '.'; stamp.hidden = false; }
    else stamp.hidden = true;
  }

  async function load(refresh, auto) {
    const btn = $('alRefresh');
    if (btn) btn.disabled = true;
    try {
      const r = await fetch('/api/events/' + document.querySelector('main[data-event-id]').dataset.eventId + '/inventory-checklist' + (refresh ? '?refresh=1' : ''), { cache: 'no-store' });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || 'No se pudo cargar el inventario');
      paint(d);
      if (refresh && !d.warning && !auto && window.showToast) window.showToast('Inventario actualizado', 'success');
      /* Servidor local: al abrir, si no hay foto del inventario o tiene más de 5 minutos, se intenta ponerla al día sola (si no hay internet, se deja la que haya, sin molestar). */
      if (!refresh && d.source === 'local') {
        const age = d.fetched_at ? Date.now() - new Date(d.fetched_at + (/[zZ]|[+-]\d\d:?\d\d$/.test(d.fetched_at) ? '' : 'Z')).getTime() : Infinity;
        if (!d.available || age > 5 * 60 * 1000) { load(true, true); }
      }
    } catch (e) {
      if (auto) return;
      $('alList').setAttribute('aria-busy', 'false');
      $('alList').innerHTML = '<p class="gw-alert gw-alert--err" role="alert">' + esc(e.message) + '</p>';
    } finally { if (btn) btn.disabled = false; }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const btn = $('alRefresh');
    if (btn) btn.addEventListener('click', () => load(true));
    load(false);
  });
})();
