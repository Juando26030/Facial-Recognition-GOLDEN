/* «Llamado de asistencia» (Usuarios del evento, 28-nov-2026): lista compacta del personal del evento con tres casillas por persona (llegó a tiempo / llegó tarde / no llegó; una sola a la vez).
   Se guarda AL INSTANTE (PUT /api/events/{id}/staff-attendance/{staff_id}); pulsar la casilla ya marcada quita la marca. Delegación de eventos; sin onclick en línea. Requiere conexión. */
(function () {
  'use strict';
  const root = document.getElementById('attRoot');
  if (!root) return;
  const eventId = root.dataset.event;
  const body = document.getElementById('attBody'), counts = document.getElementById('attCounts'), wrap = document.getElementById('attWrap');
  const search = document.getElementById('attSearch'), filter = document.getElementById('attFilter'), tabSum = document.getElementById('attTabSum');
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const OPTS = [['on_time', 'Llegó a tiempo'], ['late', 'Llegó tarde'], ['absent', 'No llegó']];
  const norm = (t) => String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  let rows = [];
  const toast = (m, k) => { if (window.showToast) window.showToast(m, k); };

  function tally() {
    const c = { on_time: 0, late: 0, absent: 0, none: 0 };
    rows.forEach((r) => { c[r.status || 'none'] += 1; });
    return c;
  }
  function renderCounts() {
    const c = tally();
    counts.innerHTML = `<span class="gw-badge gw-badge--ok">Llegaron a tiempo: ${c.on_time}</span><span class="gw-badge gw-badge--warn">Tarde: ${c.late}</span><span class="gw-badge gw-badge--err">No llegaron: ${c.absent}</span><span class="gw-badge">Sin marcar: ${c.none}</span>`;
    if (tabSum) tabSum.textContent = rows.length ? `${rows.length - c.none} de ${rows.length} marcados` : 'Quién llegó y quién no';
  }
  function visible() {
    const q = norm(search.value.trim()), f = filter.value;
    return rows.filter((r) => (!f || (f === 'none' ? !r.status : r.status === f)) && (!q || norm(r.name).includes(q) || norm(r.username).includes(q)));
  }
  function rowHtml(r, n) {
    const radios = OPTS.map(([v, label]) => `<td class="gw-att__opt"><label class="gw-att__pick"><input type="radio" name="att_${esc(r.staff_id)}" value="${v}" data-id="${esc(r.staff_id)}" data-was="${r.status === v ? '1' : '0'}" ${r.status === v ? 'checked' : ''} aria-label="${esc(label)}: ${esc(r.name || r.username)}"></label></td>`).join('');
    return `<tr data-id="${esc(r.staff_id)}" data-status="${esc(r.status || '')}"><td class="gw-att__n">${n}</td><td class="gw-att__name">${esc(r.name || 'Sin nombre')}<span class="gw-att__sub">${esc(r.username)}</span></td><td class="gw-att__ced">${esc(r.username)}</td><td class="gw-att__org"><span class="gw-badge ${r.origin === 'form' ? 'gw-badge--info' : ''}">${r.origin === 'form' ? 'Formulario' : 'Creado a mano'}</span></td>${radios}</tr>`;
  }
  function render() {
    const list = visible();
    body.innerHTML = list.length ? list.map((r, i) => rowHtml(r, i + 1)).join('') : `<tr><td colspan="7" class="gw-att__empty">${rows.length ? 'Nadie coincide con ese filtro.' : 'Todavía no hay personal en este evento. Crea o asigna cuentas en «Cuentas del evento».'}</td></tr>`;
    renderCounts();
  }
  async function load() {
    wrap.setAttribute('aria-busy', 'true');
    try {
      const res = await fetch(`/api/events/${eventId}/staff-attendance`, { cache: 'no-store' });
      if (!res.ok) throw new Error('http');
      rows = (await res.json()).rows || [];
      render();
    } catch (e) {
      body.innerHTML = '<tr><td colspan="7" class="gw-att__empty">No se pudo cargar el personal. Revisa la conexión y vuelve a abrir esta pestaña.</td></tr>';
    } finally { wrap.removeAttribute('aria-busy'); }
  }
  async function mark(id, status) {
    const r = rows.find((x) => String(x.staff_id) === String(id));
    if (!r) return;
    const before = r.status;
    r.status = status; render();
    try {
      const res = await fetch(`/api/events/${eventId}/staff-attendance/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
      if (!res.ok) { let d = ''; try { d = (await res.json()).detail; } catch (e) { /* sin detalle */ } throw new Error(d || 'No se pudo guardar'); }
    } catch (e) {
      r.status = before; render();
      toast(`${e.message || 'No se pudo guardar'}. La marca no cambió.`, 'error');
    }
  }
  body.addEventListener('click', (e) => {
    const inp = e.target.closest('input[type="radio"][data-id]');
    if (!inp) return;
    const id = inp.dataset.id;
    if (inp.dataset.was === '1') { inp.checked = false; mark(id, null); } else mark(id, inp.value);          // misma casilla otra vez = quitar la marca
  });
  search.addEventListener('input', render);
  filter.addEventListener('change', render);
  document.addEventListener('gw:tabshow', (e) => { if (e.target && e.target.id === 'tab_asistencia') load(); });
  document.addEventListener('click', (e) => { if (e.target.closest('[data-open-group]')) { const t = document.getElementById('tab_cuentas'); if (t) t.click(); } }, true);          // «Crear usuario» (arriba) vuelve a la pestaña de cuentas
})();
