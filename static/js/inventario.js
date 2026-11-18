/* Control de inventario (Fase 1.5). Lee window.EVENT_ID / CAN_REPORT / ENABLED (los pone la plantilla). Sin manejadores en línea. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  const busy = (btn, work) => (window.GW && window.GW.busy ? window.GW.busy(btn, work) : Promise.resolve(work()));
  let users = [], person = null, items = [], delivering = false, lastBatches = new Set();
  const AUTOSCAN = !!window.AUTOSCAN;          // Fase 10: «escanear / Enter = entrega automática» (Parámetros): al leer a la persona se entrega lo que esté marcado, sin pulsar «Entregar»
  const sprite = () => { const u = document.querySelector('.gw-icon use'); return u ? u.getAttribute('href').split('#')[0] : ''; };
  const icon = (name) => `<svg class="gw-icon" aria-hidden="true"><use href="${sprite()}#i-${name}"/></svg>`;
  function verdict(cls, title, html) {
    const b = $('resultBanner');
    b.className = 'gw-verdict gw-verdict--' + cls;
    b.setAttribute('role', cls === 'err' ? 'alert' : 'status');
    b.innerHTML = `<svg class="gw-icon gw-verdict__icon" aria-hidden="true"><use href="${sprite()}#i-${cls === 'ok' ? 'check-lg' : (cls === 'err' ? 'error' : 'alert')}"/></svg><div class="gw-verdict__body"><p class="gw-verdict__title">${esc(title)}</p><p class="gw-verdict__text">${html}</p></div>`;
    b.hidden = false;
  }

  async function getJson(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error('http ' + res.status);
    return res.json();
  }

  async function init() {
    if (!window.ENABLED) return;
    if (window.CAN_REPORT) $('reportBtn').hidden = false;
    try { users = await getJson(`/api/users?event_id=${window.EVENT_ID}`); }
    catch (e) { showToast('No se pudo cargar la base de personas. Recarga la página.', 'error'); }
    await loadItems(); loadDeliveries();
    $('scanInput').focus();
  }

  async function loadItems() {
    const box = $('itemsList');
    $('itemsLoading').hidden = false;
    try { items = await getJson(`/api/events/${window.EVENT_ID}/inventory`); }
    catch (e) {
      $('itemsLoading').hidden = true;
      box.innerHTML = `<div class="gw-state gw-state--error gw-empty--hero" role="alert"><span class="gw-state__icon">${icon('error')}</span><p class="gw-state__title">No se pudo cargar el inventario. Revisa la conexión y recarga la página.</p></div>`;
      return;
    }
    $('itemsLoading').hidden = true;
    const keep = AUTOSCAN ? selection() : {};          // con entrega automática lo marcado se conserva entre personas
    const real = items.filter(i => !i.is_group);
    $('statStock').textContent = real.filter(i => i.available > 0).length;
    $('statOut').textContent = real.filter(i => i.available <= 0).length;
    $('statOutBox').classList.toggle('gw-stat--err', real.some(i => i.available <= 0));
    // Subcategorías: se entrega una subcategoría (nunca el grupo); se muestra «Comida › Perro» y el disponible es el de cada una.
    const byId = {}; items.forEach(i => { byId[i.id] = i; });
    const row = (i, label, radioName) => `
      <div class="gw-card-row gw-ai__item item-row ${i.available <= 0 ? 'empty' : ''}" data-item="${i.id}">
        <div><strong class="gw-card-row__title">${esc(label)}</strong> <span class="gw-ai__avail"><span class="gw-ai__avail-num">${i.available}</span> disponibles de ${i.initial_qty}${i.available <= 0 ? ' · <span class="gw-badge gw-badge--err">Agotado</span>' : ''}</span></div>
        <div>${radioName
          ? `<label class="gw-check"><input type="radio" name="${radioName}" class="qty-check" ${i.available <= 0 ? 'disabled' : ''}> Elegir</label>`
          : (i.allow_multiple
            ? `<label class="gw-sr-only" for="qty${i.id}">Cantidad de ${esc(i.name)}</label><input type="number" id="qty${i.id}" class="gw-input qty" min="0" max="${Math.max(i.available, 0)}" value="0" ${i.available <= 0 ? 'disabled' : ''}>`
            : `<label class="gw-check"><input type="checkbox" class="qty-check" ${i.available <= 0 ? 'disabled' : ''}> Entregar 1</label>`)}</div>
      </div>`;
    // Un grupo con «Máx. por persona» = 1 es de ELEGIR UNA (botones de opción: ni dos ni ninguna); con un máximo mayor se frena al pasarse (ver limitGroup). Las subcategorías sin grupo y los ítems sueltos, como siempre.
    const groups = items.filter(i => i.is_group);
    const grouped = new Set();
    let html = groups.map(g => {
      const kids = items.filter(i => i.parent_id === g.id && !i.is_group);
      if (!kids.length) return '';
      kids.forEach(k => grouped.add(k.id));
      const one = g.max_per_person === 1;
      const rule = one ? 'Elige una opción (obligatorio)' : (g.max_per_person ? `Máximo ${g.max_per_person} por persona` : '');
      return `<fieldset class="gw-ai__group" data-group="${g.id}" data-max="${g.max_per_person || ''}"><legend><strong>${esc(g.name)}</strong>${rule ? ` · <span class="gw-ai__avail">${esc(rule)}</span>` : ''}</legend>${kids.map(k => row(k, k.name, one && !k.allow_multiple ? 'grp' + g.id : '')).join('')}</fieldset>`;
    }).join('');
    const loose = items.filter(i => !i.is_group && !grouped.has(i.id)).map(i => (i.parent_id && byId[i.parent_id] ? Object.assign({}, i, { name: byId[i.parent_id].name + ' › ' + i.name }) : i));
    html += loose.map(i => row(i, i.name, '')).join('');
    box.innerHTML = html || `<div class="gw-state gw-empty--hero"><span class="gw-state__icon">${icon('inbox')}</span><p class="gw-state__title">No hay ítems en el inventario. Un coordinador los crea en Parámetros del evento.</p></div>`;
    if (AUTOSCAN) restore(keep);
  }
  /* Tope por persona de un grupo (Máx. > 1): al pasarse, se deshace lo último marcado y se avisa. Con el máximo en 1 son botones de opción y no hace falta. */
  document.addEventListener('change', (e) => {
    const fs = e.target.closest && e.target.closest('fieldset[data-group]'); if (!fs) return;
    const max = parseInt(fs.dataset.max, 10); if (!max) return;
    const total = Array.from(fs.querySelectorAll('.item-row')).reduce((n, r) => n + (r.querySelector('.qty') ? (parseInt(r.querySelector('.qty').value, 10) || 0) : (r.querySelector('.qty-check').checked ? 1 : 0)), 0);
    if (total <= max) return;
    if (e.target.classList.contains('qty')) e.target.value = Math.max(0, (parseInt(e.target.value, 10) || 0) - (total - max)); else e.target.checked = false;
    showToast(`Solo se permiten ${max} por persona en «${fs.querySelector('legend strong').textContent}».`, 'error');
  });
  /* Lo marcado en pantalla: {id_del_ítem: cantidad}. Pura sobre el DOM; se usa para conservarlo al recargar y para armar la entrega. */
  function selection() {
    const out = {};
    document.querySelectorAll('.item-row').forEach(row => {
      const id = parseInt(row.dataset.item, 10);
      const q = row.querySelector('.qty') ? parseInt(row.querySelector('.qty').value, 10) || 0 : (row.querySelector('.qty-check').checked ? 1 : 0);
      if (q > 0) out[id] = q;
    });
    return out;
  }
  function restore(sel) {
    document.querySelectorAll('.item-row').forEach(row => {
      const q = sel[parseInt(row.dataset.item, 10)] || 0;
      if (!q) return;
      if (row.querySelector('.qty')) { const inp = row.querySelector('.qty'); if (!inp.disabled) inp.value = Math.min(q, parseInt(inp.max, 10) || q); }
      else { const chk = row.querySelector('.qty-check'); if (chk && !chk.disabled) chk.checked = true; }
    });
  }

  async function loadDeliveries() {
    let rows;
    try { rows = await getJson(`/api/events/${window.EVENT_ID}/inventory/deliveries`); }
    catch (e) { setDelState('No se pudieron cargar las entregas. Recarga la página.', true); return; }
    lastBatches = new Set(rows.map(r => r.batch_id));
    $('statDeliveries').textContent = rows.length;
    if (!rows.length) { setDelState('Sin entregas todavía. Elige a una persona y entrega el primer ítem.', false); $('delBody').innerHTML = ''; return; }
    $('delState').hidden = true; $('delWrap').hidden = false;
    $('delBody').innerHTML = rows.map(r => `<article class="gw-card-row"><div class="gw-card-row__head"><h3 class="gw-card-row__title">${esc(r.name)}</h3><span class="gw-badge gw-badge--ok">${r.qty} × ${esc(r.item)}</span></div><p class="gw-card-row__meta">${esc(r.user_id)} · ${new Date(r.time + 'Z').toLocaleTimeString()}</p></article>`).join('');
  }
  function setDelState(text, isError) {
    const st = $('delState'); st.innerHTML = `<span class="gw-state__icon">${icon(isError ? 'error' : 'inbox')}</span><p class="gw-state__title">${esc(text)}</p>`; st.hidden = false; st.classList.toggle('gw-state--error', !!isError); $('delWrap').hidden = true;
  }

  function setPerson(u) {
    if (!u) return;
    person = u;
    const b = $('personBanner');
    b.innerHTML = `<div class="gw-person__photo" aria-hidden="true">${esc((String(u.first_name || '?').trim()[0] || '?').toUpperCase())}</div><div class="gw-person__body"><h3 class="gw-person__name">${esc(u.first_name)} ${esc(u.last_name)}</h3><p class="gw-person__meta">${esc(u.id)}</p></div><div class="gw-person__status"><span class="gw-badge gw-badge--ok">${icon('check')} Entregando a esta persona</span></div>`;
    b.hidden = false;
    $('suggest').innerHTML = ''; $('nameSearch').value = '';
  }
  function byId(id, auto) {
    // Primero identificación y, si el evento usa código, el código (0140)
    const low = String(id || '').trim().toLowerCase();
    const u = users.find(x => x.id === id) || (low ? users.find(x => x.code && String(x.code).toLowerCase() === low) : null);
    if (!u) { showToast('Esa persona no está en la base de este evento', 'error'); return false; }
    setPerson(u);
    if (auto && AUTOSCAN) deliver();          // entrega automática: la lectura (o el Enter) de la persona entrega lo marcado
    return true;
  }

  $('scanInput').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    let typed = e.target.value.trim(); e.target.value = '';
    if (!typed) return;
    typed = QrCode.collect(typed);                                             // QR en vCard con lector de mano: llega en varias líneas (Fase 10, C)
    if (typed === null) return;
    QrCode.resolveDynamic(typed, window.EVENT_ID, 'inventory').then((raw) => {          // QR dinámico de la credencial digital: lo valida el servidor
      const qr = QrCode.parse(raw);
      const parsed = GoldenDirectory.parseOldCedulaBarcode(raw);
      byId(qr && qr.isQr ? qr.cedula : (parsed ? parsed.cedula : raw), true);   // QR propio: en vez de entregar la cédula
    }).catch((err) => { if (typeof showToast === 'function') showToast(err.message || 'No se pudo validar el código', 'error'); });
  });
  // Cámara del dispositivo: cada QR leído elige a la persona a la que se le entrega.
  let scanner = null;
  if ($('scanQrBtn')) $('scanQrBtn').addEventListener('click', () => { scanner = QrScanner.open({
    title: 'Escanear QR — Control de Inventario',
    // Si la cámara lee el QR y encuentra a la persona, se cierra sola (con entrega automática, después de lanzarla); si no la encuentra o falla, queda abierta con el aviso.
    onCode: (text) => { QrCode.resolveDynamic(text, window.EVENT_ID, 'inventory').then((raw) => { const qr = QrCode.parse(raw); return qr ? byId(qr.cedula, true) : false; })
      .then((found) => { if (found && scanner) scanner.close(); })
      .catch((err) => { if (typeof showToast === 'function') showToast(err.message || 'No se pudo validar el código', 'error'); }); },
  }); });
  $('nameSearch').addEventListener('input', (e) => {
    const q = e.target.value.trim();
    const found = q ? users.filter(u => GoldenDirectory.matchesWordPrefix(`${u.first_name} ${u.last_name}`, q)).slice(0, 6) : [];
    $('suggest').innerHTML = found.map(u => `<button type="button" data-id="${esc(u.id)}">${esc(u.first_name)} ${esc(u.last_name)} · ${esc(u.id)}</button>`).join('');
  });
  $('suggest').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-id]'); if (btn) setPerson(users.find(u => u.id === btn.dataset.id));
  });

  async function deliver() {
    if (!person) { showToast('Primero elige a quién se le entrega', 'error'); return; }
    if (delivering) return;          // un segundo Enter mientras se entrega no duplica la entrega
    const sel = selection();
    const lines = Object.keys(sel).map(id => ({ item_id: parseInt(id, 10), qty: sel[id] }));
    if (!lines.length) { showToast(AUTOSCAN ? 'Marca primero qué se entrega: se entregará solo al escanear a cada persona' : 'Elige al menos un ítem', 'error'); return; }
    delivering = true;
    try { await doDeliver(lines); } finally { delivering = false; }
  }
  async function doDeliver(lines) {
    let res, data;
    try {
      res = await fetch(`/api/events/${window.EVENT_ID}/inventory/deliver`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cedula: person.id, items: lines }) });
      data = await res.json().catch(() => ({}));
    } catch (e) { res = null; data = { detail: 'No se pudo entregar: sin conexión con el servidor. Inténtalo de nuevo.' }; }
    if (!res || !res.ok) { verdict(res ? 'warn' : 'err', res ? 'No se pudo entregar' : 'Sin conexión', esc(data.detail || 'No se pudo entregar')); return; }
    verdict('ok', 'Entregado', `<strong>${esc(person.first_name)} ${esc(person.last_name)}</strong>: ${data.delivered.map(d => `${d.qty} × ${esc(d.name)}`).join(', ')}. Quedan: ${data.stock.map(s => `${esc(s.name)} ${s.available}`).join(' · ')}`);
    await loadItems(); await loadDeliveries();
    // Comprobación: lo «entregado» tiene que aparecer en el registro. Si no aparece, NO se da por entregado (así no queda una entrega fantasma en pantalla).
    if (data.batch_id && !lastBatches.has(data.batch_id)) verdict('err', 'Revisa esta entrega', `No aparece en el registro del evento. Recarga la página y comprueba antes de volver a entregar: <strong>${esc(person.first_name)} ${esc(person.last_name)}</strong>.`);
  }
  $('deliverBtn').addEventListener('click', (e) => busy(e.currentTarget, deliver));

  init();
})();
