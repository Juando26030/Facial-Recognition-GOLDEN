/* Pantalla /servidor-local (Fase 6, solo en un servidor local): lista de TODOS los eventos de la nube (solo metadatos) agrupados por cliente o por calendario, y «Descargar a local» en un paso.
   Delegación de eventos, texto escapado, mensajes con showToast / showConfirm. */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const STATUS = { creado: 'Creado', en_proceso: 'En proceso', finalizado: 'Finalizado' };
  const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const list = document.getElementById('slEvents');
  const search = document.getElementById('slSearch');
  const alertBox = document.getElementById('slAlert');
  let events = [], group = 'client', timer = null;

  const norm = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  function say(kind, text) {
    alertBox.hidden = !text;
    alertBox.className = 'gw-alert gw-alert--' + (kind || 'warn');
    alertBox.textContent = text || '';
  }
  function badge(e) {
    if (e.leased_here || e.downloaded) return '<span class="gw-badge gw-badge--ok">Ya está en este servidor</span>';
    if (e.leased_elsewhere) return `<span class="gw-badge gw-badge--warn">En el servidor local «${esc((e.local || {}).node_name)}»</span>`;
    return '';
  }
  function row(e) {
    const dates = e.start_date ? ' · ' + esc(e.start_date) + (e.end_date && e.end_date !== e.start_date ? ' a ' + esc(e.end_date) : '') : '';
    const can = !e.downloaded && !e.leased_here && !e.leased_elsewhere;
    const action = can
      ? `<button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-download="${e.id}" data-name="${esc(e.name)}">Descargar a local</button>`
      : (e.local_event_id ? `<a class="gw-btn gw-btn--secondary gw-btn--sm" href="/kiosk/${e.local_event_id}/registro">Abrir</a>` : '');
    return `<li class="gw-list__item"><div><strong>${esc(e.name)}</strong> <span class="gw-hint">${esc(e.event_code)} · ${esc(STATUS[e.status] || e.status)}${dates}</span> ${badge(e)}</div>${action}</li>`;
  }
  function keyOf(e) {
    if (group === 'client') return e.tenant_name || e.tenant_id || 'Sin cliente';
    if (!e.start_date) return 'Sin fecha';
    const [y, m] = e.start_date.split('-');
    return MONTHS[Number(m) - 1] + ' ' + y;
  }
  function draw() {
    const q = norm(search.value.trim());
    const shown = events.filter((e) => !q || norm(e.name + ' ' + e.event_code + ' ' + (e.tenant_name || '')).includes(q));
    if (!shown.length) { list.innerHTML = '<div class="gw-state" role="status"><p class="gw-state__title">No hay eventos para mostrar</p></div>'; return; }
    const groups = new Map();
    shown.forEach((e) => { const k = keyOf(e); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(e); });
    let keys = [...groups.keys()];
    if (group === 'client') keys.sort((a, b) => a.localeCompare(b, 'es'));
    else keys = keys.sort((a, b) => (groups.get(b)[0].start_date || '').localeCompare(groups.get(a)[0].start_date || ''));
    list.innerHTML = keys.map((k) => `<section class="gw-stack"><h2 class="gw-section-title">${esc(k)}</h2><ul class="gw-list">${groups.get(k).map(row).join('')}</ul></section>`).join('');
  }
  async function load() {
    list.setAttribute('aria-busy', 'true');
    try {
      const res = await fetch('/api/local/cloud-events');
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo cargar la lista');
      document.getElementById('slNode').textContent = d.node_name || '—';
      events = d.events || [];
      if (!d.configured) say('warn', 'Este servidor todavía no está conectado a la nube (faltan la dirección y el token del servidor). Pídele a quien lo instaló que lo configure.');
      else if (d.offline) say('warn', (d.error || 'No hay conexión con la nube') + ' Revisa el internet: la lista se carga sola al reconectar con «Actualizar lista».');
      else say('', '');
      draw();
    } catch (err) {
      list.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`;
    } finally { list.setAttribute('aria-busy', 'false'); }
  }
  async function download(btn) {
    const id = btn.dataset.download;
    if (!(await showConfirm(`Se llevará «${esc(btn.dataset.name)}» a este servidor. Desde ese momento en la nube solo se podrá ver (se libera con «Pasar a internet»). ¿Descargar a local?`, { variant: 'warning', confirmLabel: 'Sí, descargar' }))) return;
    btn.disabled = true; const old = btn.textContent; btn.textContent = 'Descargando…';
    try {
      const res = await fetch(`/api/local/cloud-events/${encodeURIComponent(id)}/download`, { method: 'POST' });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { showToast(typeof d.detail === 'string' ? d.detail : 'No se pudo descargar el evento', 'error'); return; }
      showToast(d.message || 'Evento descargado', 'success');
      await load();
    } catch (err) {
      showToast('No se pudo descargar el evento. Revisa la conexión.', 'error');
    } finally { btn.disabled = false; btn.textContent = old; }
  }

  list.addEventListener('click', (e) => { const b = e.target.closest('[data-download]'); if (b) download(b); });
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(draw, 200); });
  document.addEventListener('click', (e) => {
    const g = e.target.closest('[data-group]');
    if (g) { group = g.dataset.group; document.querySelectorAll('[data-group]').forEach((x) => x.setAttribute('aria-pressed', String(x === g))); draw(); }
    if (e.target.closest('#slReload')) load();
  });
  load();
})();
