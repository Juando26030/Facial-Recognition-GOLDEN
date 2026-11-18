/* Almacén (Inventario → pestaña «Novedades», Pieza 3): novedades (daños o problemas de un elemento). Reportar por código CON archivos obligatorios (fotos, PDF o video; varios a la vez),
   lista con filtro y buscador, y «Resolver» (nota + archivos obligatorios de cómo quedó; deja el equipo disponible de nuevo). API (multipart): /api/almacen/novelties (GET lista, POST reportar),
   /{id}/resolve, y /{id}/files/{fileId} para ver cada archivo. Todo se escapa; sin manejadores en línea. */
(function () {
  'use strict';
  const root = document.getElementById('invPanelNov');
  const card = document.getElementById('almNovCard');
  if (!root || !card) return;
  const tab = document.getElementById('invTabNov');
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const MAX_FILES = 8;
  const MAX_FILE = 10 * 1000 * 1000;
  const MAX_TOTAL = 25 * 1000 * 1000;
  let items = [];
  let openCount = 0;
  let loaded = false;
  const reportFiles = [];          // archivos elegidos para reportar (se pueden ir sumando y quitando)
  const resolveFiles = new Map();          // id de novedad -> archivos elegidos para resolverla

  async function j(url, opts) {
    const r = await fetch(url, opts);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : (d.detail && d.detail.message) || 'Error');
    return d;
  }
  const fail = (e) => showToast(e && e.message ? e.message : 'No se pudo completar la acción', 'error');
  const norm = (v) => String(v == null ? '' : v).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const mb = (n) => (n / 1000000).toFixed(1).replace('.', ',') + ' MB';

  /* ---- archivos elegidos: se suman, se pueden quitar y se validan antes de enviar */
  function addFiles(list, picked) {
    for (const f of picked) {
      if (list.length >= MAX_FILES) { showToast(`Hasta ${MAX_FILES} archivos a la vez`, 'error'); break; }
      if (f.size > MAX_FILE) { showToast(`«${f.name}» pesa más de ${MAX_FILE / 1000000} MB`, 'error'); continue; }
      if (list.reduce((a, x) => a + x.size, f.size) > MAX_TOTAL) { showToast(`Máximo ${MAX_TOTAL / 1000000} MB en total por envío`, 'error'); break; }
      list.push(f);
    }
  }
  function fileList(list, attr) {
    return list.map((f, i) => `<li class="gw-alm__file"><span>${esc(f.name)} <span class="gw-hint">${mb(f.size)}</span></span>
      <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" ${attr}="${i}" aria-label="Quitar ${esc(f.name)}">Quitar</button></li>`).join('');
  }
  /* La foto de la cámara del celular llega siempre con el mismo nombre («image.jpg»): se le pone uno propio para distinguirlas en la lista. */
  const CAM_ICON = '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="/static/img/icons.svg#i-camera"/></svg>';
  function shots(files) { return Array.from(files || []).map((f, i) => new File([f], `foto-${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')}-${i + 1}.${(f.type.split('/')[1] || 'jpg').replace('jpeg', 'jpg')}`, { type: f.type, lastModified: Date.now() })); }
  const paintReport = () => { $('almNovFilesList').innerHTML = fileList(reportFiles, 'data-nov-rm'); };

  /* ---- lista */
  function attachments(files) {
    if (!files.length) return '';
    const label = { reporte: 'Al reportar', resolucion: 'Al resolver' };
    return '<ul class="gw-alm__attach">' + files.map((f) => f.is_image
      ? `<li><a href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(label[f.kind] || '')}: ${esc(f.name)}"><img class="gw-alm__thumb" src="${esc(f.url)}" alt="${esc(label[f.kind] || '')}: ${esc(f.name)}" width="64" height="64" loading="lazy"></a></li>`
      : `<li><a class="gw-btn gw-btn--secondary gw-btn--sm" href="${esc(f.url)}" target="_blank" rel="noopener">${esc(label[f.kind] || '')}: ${esc(f.name)}</a></li>`).join('') + '</ul>';
  }
  function resolveForm(n) {
    const sel = resolveFiles.get(n.id) || [];
    return `<div class="gw-alm__resolve gw-stack" data-nov-form="${n.id}" hidden>
      <div class="gw-field"><label class="gw-label" for="almNovNote${n.id}">Qué se hizo <span class="gw-hint">(reparado, cambiado, revisado…)</span></label>
        <textarea class="gw-input" id="almNovNote${n.id}" rows="2" maxlength="500" data-nov-note="${n.id}"></textarea></div>
      <div class="gw-field"><label class="gw-label" for="almNovRf${n.id}">Foto o archivo de cómo quedó <span class="gw-hint">(obligatorio; puedes adjuntar varios)</span></label>
        <input class="gw-input" type="file" id="almNovRf${n.id}" multiple accept="image/*,application/pdf,video/mp4,video/quicktime" data-nov-rf="${n.id}">
        <div class="gw-row"><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-nov-cam="${n.id}">${CAM_ICON} Tomar foto con la cámara</button></div>
        <input type="file" accept="image/*" capture="environment" hidden data-nov-camin="${n.id}">
        <ul class="gw-alm__files" data-nov-rflist="${n.id}">${fileList(sel, 'data-nov-rrm')}</ul></div>
      <div class="gw-row"><button type="button" class="gw-btn gw-btn--primary" data-nov-resolve-go="${n.id}">Resolver y dejar disponible</button>
        <button type="button" class="gw-btn gw-btn--secondary" data-nov-resolve-cancel="${n.id}">Cancelar</button></div></div>`;
  }
  function row(n) {
    const state = n.resolved ? '<span class="gw-badge gw-badge--ok">Resuelta</span>' : '<span class="gw-badge gw-badge--warn">Abierta</span>';
    const meta = [n.code, n.qty > 1 || !n.unit_id ? n.qty + ' pieza(s)' : '', n.event_name ? 'Evento: ' + n.event_name : '', n.created_at ? 'Reportada ' + n.created_at + (n.created_by ? ' por ' + n.created_by : '') : ''].filter(Boolean).join(' · ');
    const res = n.resolved ? `<p class="gw-card-row__meta">Resuelta ${esc(n.resolved_at || '')}${n.resolved_by ? ' por ' + esc(n.resolved_by) : ''}: ${esc(n.resolution || '')}</p>` : '';
    const btn = n.resolved ? '' : `<div class="gw-card-row__actions"><button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-nov-resolve="${n.id}">Resolver</button></div>${resolveForm(n)}`;
    return `<article class="gw-card-row" data-nov="${n.id}"><div class="gw-card-row__head"><span class="gw-card-row__title">${esc(n.title)}</span>${state}</div>
      <p class="gw-card-row__meta">${esc(meta)}</p><p>${esc(n.description)}</p>${attachments(n.files || [])}${res}${btn}</article>`;
  }
  function render() {
    const q = norm($('almNovSearch').value).trim();
    const shown = q ? items.filter((n) => norm([n.title, n.code, n.description, n.event_name].join(' ')).includes(q)) : items;
    const open = new Set(Array.from(card.querySelectorAll('[data-nov-form]:not([hidden])')).map((e) => e.dataset.novForm));          // formularios de resolver abiertos: no se cierran al repintar
    $('almNovList').innerHTML = !shown.length
      ? '<div class="gw-state" role="status"><p class="gw-state__title">' + (items.length ? 'Ninguna novedad coincide' : 'No hay novedades en este filtro') + '</p></div>'
      : '<div class="gw-cards">' + shown.map(row).join('') + '</div>';
    open.forEach((id) => { const f = card.querySelector(`[data-nov-form="${id}"]`); if (f) f.hidden = false; });
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

  /* ---- reportar */
  $('almNovFiles').addEventListener('change', () => { addFiles(reportFiles, Array.from($('almNovFiles').files)); $('almNovFiles').value = ''; paintReport(); });
  $('almNovCam').addEventListener('click', () => $('almNovCamIn').click());          // abre la cámara (celular); en computador abre el selector de imágenes
  $('almNovCamIn').addEventListener('change', () => { addFiles(reportFiles, shots($('almNovCamIn').files)); $('almNovCamIn').value = ''; paintReport(); });
  $('almNovFilesList').addEventListener('click', (e) => { const b = e.target.closest('[data-nov-rm]'); if (b) { reportFiles.splice(Number(b.dataset.novRm), 1); paintReport(); } });
  $('almNovSave').addEventListener('click', async () => {
    const btn = $('almNovSave');
    if (!reportFiles.length) { showToast('Adjunta al menos una foto o archivo del daño', 'error'); $('almNovFiles').focus(); return; }
    const fd = new FormData();
    fd.append('code', $('almNovCode').value.trim());
    fd.append('description', $('almNovText').value);
    fd.append('qty', String(Number($('almNovQty').value) || 1));
    reportFiles.forEach((f) => fd.append('files', f, f.name));
    btn.disabled = true;
    try {
      const d = await j('/api/almacen/novelties', { method: 'POST', body: fd });
      showToast(d.message, 'success');
      $('almNovCode').value = ''; $('almNovText').value = ''; $('almNovQty').value = '1'; reportFiles.length = 0; paintReport();
      $('almNovFormBox').open = false;
      await load();
    } catch (e) { fail(e); }
    btn.disabled = false;
  });
  $('almNovCode').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('almNovText').focus(); } });
  $('almNovSearch').addEventListener('input', render);
  $('almNovState').addEventListener('change', load);

  /* ---- resolver (formulario dentro de la tarjeta de cada novedad) */
  $('almNovList').addEventListener('change', (e) => {
    const inp = e.target.closest('[data-nov-rf]');
    if (!inp) return;
    const id = Number(inp.dataset.novRf);
    const list = resolveFiles.get(id) || [];
    addFiles(list, Array.from(inp.files));
    resolveFiles.set(id, list);
    inp.value = '';
    inp.closest('[data-nov]').querySelector(`[data-nov-rflist="${id}"]`).innerHTML = fileList(list, 'data-nov-rrm');
  });
  $('almNovList').addEventListener('change', (e) => {          // foto tomada con la cámara al resolver
    const cam = e.target.closest('[data-nov-camin]');
    if (!cam) return;
    const id = Number(cam.dataset.novCamin);
    const list = resolveFiles.get(id) || [];
    addFiles(list, shots(cam.files));
    resolveFiles.set(id, list);
    cam.value = '';
    cam.closest('[data-nov]').querySelector(`[data-nov-rflist="${id}"]`).innerHTML = fileList(list, 'data-nov-rrm');
  });
  $('almNovList').addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    const art = t.closest('[data-nov]');
    const id = art ? Number(art.dataset.nov) : 0;
    if (t.dataset.novResolve) { const f = art.querySelector('[data-nov-form]'); f.hidden = !f.hidden; if (!f.hidden) f.querySelector('textarea').focus(); return; }
    if (t.dataset.novCam) { art.querySelector(`[data-nov-camin="${t.dataset.novCam}"]`).click(); return; }
    if (t.dataset.novResolveCancel) { art.querySelector('[data-nov-form]').hidden = true; return; }
    if (t.dataset.novRrm !== undefined) {
      const list = resolveFiles.get(id) || [];
      list.splice(Number(t.dataset.novRrm), 1);
      art.querySelector(`[data-nov-rflist="${id}"]`).innerHTML = fileList(list, 'data-nov-rrm');
      return;
    }
    if (!t.dataset.novResolveGo) return;
    const list = resolveFiles.get(id) || [];
    if (!list.length) { showToast('Adjunta al menos una foto o archivo de cómo quedó', 'error'); art.querySelector('[data-nov-rf]').focus(); return; }
    const fd = new FormData();
    fd.append('note', art.querySelector('[data-nov-note]').value);
    list.forEach((f) => fd.append('files', f, f.name));
    t.disabled = true;
    try {
      const d = await j('/api/almacen/novelties/' + id + '/resolve', { method: 'POST', body: fd });
      showToast(d.message, 'success');
      resolveFiles.delete(id);
      await load();
    } catch (err) { fail(err); t.disabled = false; }
  });

  if (tab) tab.addEventListener('gw:tabshow', () => { if (!loaded) { loaded = true; load(); } });
})();
