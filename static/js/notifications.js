/* Campana de notificaciones de la cuenta (Fase 5): botón flotante con el número de avisos sin leer y un panel con los últimos. Sin sondeo (Neon no se apaga si hay consultas frecuentes): se piden al abrir la
   página y al pulsar la campana. Delegación de eventos, todo texto escapado, sin alert/confirm. Los mismos avisos salen además por correo (app/notifications.py). */
(function () {
  'use strict';
  if (document.getElementById('gwBell')) return;
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const wrap = document.createElement('div');
  wrap.className = 'gw-bell'; wrap.id = 'gwBell';
  wrap.innerHTML = '<button type="button" class="gw-btn gw-btn--secondary gw-bell__btn" id="gwBellBtn" aria-haspopup="dialog" aria-expanded="false" aria-controls="gwBellPanel" aria-label="Notificaciones">' +
    '<svg class="gw-icon" aria-hidden="true"><use href="/static/img/icons.svg#i-bell"/></svg><span class="gw-bell__n" id="gwBellN" hidden>0</span></button>' +
    '<div class="gw-bell__panel" id="gwBellPanel" role="dialog" aria-label="Notificaciones" hidden><div class="gw-bell__head"><strong>Notificaciones</strong>' +
    '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" id="gwBellAll">Marcar todas como leídas</button></div><div id="gwBellList" aria-live="polite"></div></div>';
  document.body.appendChild(wrap);
  const btn = wrap.querySelector('#gwBellBtn'), panel = wrap.querySelector('#gwBellPanel'), badge = wrap.querySelector('#gwBellN'), list = wrap.querySelector('#gwBellList');

  function paintCount(n) { badge.textContent = n > 99 ? '99+' : String(n); badge.hidden = !n; btn.setAttribute('aria-label', n ? `Notificaciones: ${n} sin leer` : 'Notificaciones'); }
  async function load() {
    try {
      const res = await fetch('/api/notifications?limit=20');
      if (res.status === 401) { wrap.remove(); return; }
      if (!res.ok) throw new Error();
      const d = await res.json();
      paintCount(d.unread);
      list.innerHTML = d.items.length ? d.items.map((n) => `<div class="gw-bell__item${n.read ? '' : ' gw-bell__item--new'}" data-id="${n.id}" data-url="${esc(n.url || '')}" role="button" tabindex="0">` +
        `<strong>${esc(n.title)}</strong>${n.body ? `<p>${esc(n.body)}</p>` : ''}<span class="gw-hint">${esc(new Date(n.created_at).toLocaleString())}</span></div>`).join('') : '<p class="gw-hint">No tienes notificaciones.</p>';
    } catch (e) { list.innerHTML = '<p class="gw-hint">No se pudieron cargar las notificaciones.</p>'; }
  }
  async function open(o) { panel.hidden = !o; btn.setAttribute('aria-expanded', o ? 'true' : 'false'); if (o) await load(); }
  async function readItem(el) {
    const id = el.dataset.id;
    try { const res = await fetch(`/api/notifications/${id}/read`, { method: 'POST' }); if (res.ok) { const d = await res.json(); paintCount(d.unread); el.classList.remove('gw-bell__item--new'); } } catch (e) { /* sin conexión: se queda sin leer */ }
    if (/^\/(?![\/\\])/.test(el.dataset.url || '')) window.location.href = el.dataset.url;          // solo rutas internas («//otro-sitio» o «/\otro» no)
  }
  btn.addEventListener('click', () => open(panel.hidden));
  wrap.querySelector('#gwBellAll').addEventListener('click', async () => { try { await fetch('/api/notifications/read-all', { method: 'POST' }); } catch (e) { /* nada */ } paintCount(0); list.querySelectorAll('.gw-bell__item--new').forEach((x) => x.classList.remove('gw-bell__item--new')); });
  list.addEventListener('click', (e) => { const it = e.target.closest('[data-id]'); if (it) readItem(it); });
  list.addEventListener('keydown', (e) => { if (e.key === 'Enter') { const it = e.target.closest('[data-id]'); if (it) readItem(it); } });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) { open(false); btn.focus(); } });
  document.addEventListener('click', (e) => { if (!panel.hidden && !wrap.contains(e.target)) open(false); });
  fetch('/api/notifications?unread=1&limit=1').then((r) => (r.ok ? r.json() : null)).then((d) => { if (d) paintCount(d.unread); }).catch(() => {});
})();
