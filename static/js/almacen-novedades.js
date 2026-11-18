/* Almacén (Inventario → pestaña «Novedades», Pieza 3): novedades (daños o problemas de un elemento). Reportar por código, foto del daño (con la cámara en el celular), lista con filtro y
   buscador, y «Resolver» (deja el equipo disponible de nuevo). API: /api/almacen/novelties (GET lista, POST reportar), /{id}/photo, /{id}/resolve. Todo se escapa; sin manejadores en línea. */
(function () {
  'use strict';
  const root = document.getElementById('invPanelNov');
  const card = document.getElementById('almNovCard');
  if (!root || !card) return;
  const tab = document.getElementById('invTabNov');
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  let items = [];
  let openCount = 0;
  let loaded = false;
  let photoFor = null;

  async function j(url, opts) {
    const r = await fetch(url, opts);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : (d.detail && d.detail.message) || 'Error');
    return d;
  }
  const send = (url, body) => j(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  const fail = (e) => showToast(e && e.message ? e.message : 'No se pudo completar la acción', 'error');
  const norm = (v) => String(v == null ? '' : v).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  function row(n) {
    const thumb = n.photo_url ? `<img class="gw-alm__thumb" src="${esc(n.photo_url)}" alt="Foto del daño de ${esc(n.title)}" width="64" height="64" loading="lazy">` : '';
    const state = n.resolved ? '<span class="gw-badge gw-badge--ok">Resuelta</span>' : '<span class="gw-badge gw-badge--warn">Abierta</span>';
    const meta = [n.code, n.serial ? 'Serial ' + n.serial : '', n.qty > 1 || !n.unit_id ? n.qty + ' pieza(s)' : '', n.event_name ? 'Evento: ' + n.event_name : '', n.created_at ? 'Reportada ' + n.created_at + (n.created_by ? ' por ' + n.created_by : '') : ''].filter(Boolean).join(' · ');
    const res = n.resolved ? `<p class="gw-card-row__meta">Resuelta ${esc(n.resolved_at || '')}${n.resolved_by ? ' por ' + esc(n.resolved_by) : ''}: ${esc(n.resolution || '')}</p>` : '';
    const btns = `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-nov-photo="${n.id}">${n.has_photo ? 'Cambiar foto' : 'Agregar foto'}</button>`
      + (n.resolved ? '' : ` <button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-nov-resolve="${n.id}" data-title="${esc(n.title)}">Resolver</button>`);
    return `<article class="gw-card-row"><div class="gw-alm__slot">${thumb}<div class="gw-alm__slotbody"><div class="gw-card-row__head"><span class="gw-card-row__title">${esc(n.title)}</span>${state}</div>
      <p class="gw-card-row__meta">${esc(meta)}</p><p>${esc(n.description)}</p>${res}<div class="gw-card-row__actions">${btns}</div></div></div></article>`;
  }
  function render() {
    const q = norm($('almNovSearch').value).trim();
    const shown = q ? items.filter((n) => norm([n.title, n.code, n.serial, n.description, n.event_name].join(' ')).includes(q)) : items;
    $('almNovList').innerHTML = !shown.length
      ? '<div class="gw-state" role="status"><p class="gw-state__title">' + (items.length ? 'Ninguna novedad coincide' : 'No hay novedades en este filtro') + '</p></div>'
      : '<div class="gw-cards">' + shown.map(row).join('') + '</div>';
    $('almNovInfo').textContent = q ? `${shown.length} de ${items.length} novedades` : '';
    $('almNovSummary').textContent = openCount ? `${openCount} abierta${openCount === 1 ? '' : 's'}` : 'Sin novedades abiertas';
  }
  async function load() {
    try {
      const d = await j('/api/almacen/novelties?state=' + encodeURIComponent($('almNovState').value));
      items = d.novelties || [];
      openCount = d.open_count || 0;
      render();
    } catch (e) { $('almNovList').innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(e.message)}</p></div>`; }
  }

  $('almNovSave').addEventListener('click', async () => {
    const btn = $('almNovSave');
    btn.disabled = true;
    try {
      const d = await send('/api/almacen/novelties', { code: $('almNovCode').value.trim(), description: $('almNovText').value, qty: Number($('almNovQty').value) || 1 });
      showToast(d.message, 'success');
      $('almNovCode').value = ''; $('almNovText').value = ''; $('almNovQty').value = '1';
      $('almNovFormBox').open = false;
      await load();
    } catch (e) { fail(e); }
    btn.disabled = false;
  });
  $('almNovCode').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('almNovText').focus(); } });
  $('almNovSearch').addEventListener('input', render);
  $('almNovState').addEventListener('change', load);

  const picker = document.createElement('input');          // un solo selector; en el celular abre la cámara
  picker.type = 'file';
  picker.accept = 'image/*';
  picker.setAttribute('capture', 'environment');
  picker.hidden = true;
  root.appendChild(picker);
  picker.addEventListener('change', async () => {
    const f = picker.files && picker.files[0];
    const id = photoFor;
    picker.value = '';
    if (!f || !id) return;
    const fd = new FormData();
    fd.append('file', f);
    try { await j('/api/almacen/novelties/' + id + '/photo', { method: 'POST', body: fd }); showToast('Foto guardada', 'success'); await load(); } catch (e) { fail(e); }
  });

  $('almNovList').addEventListener('click', async (e) => {
    const p = e.target.closest('button[data-nov-photo]');
    if (p) { photoFor = p.dataset.novPhoto; picker.click(); return; }
    const r = e.target.closest('button[data-nov-resolve]');
    if (!r) return;
    const note = await showPrompt(`¿Qué se hizo con «${esc(r.dataset.title)}»? (reparado, cambiado, revisado…)`, { title: 'Resolver novedad', confirmLabel: 'Dejar disponible' });
    if (!note) return;
    try { const d = await send('/api/almacen/novelties/' + r.dataset.novResolve + '/resolve', { note }); showToast(d.message, 'success'); await load(); } catch (err) { fail(err); }
  });
  document.addEventListener('gw:almacen-novelty', load);          // lo dispara almacen-moves.js cuando una entrada trae novedad

  if (tab) tab.addEventListener('gw:tabshow', () => { if (!loaded) { loaded = true; load(); } });
})();
