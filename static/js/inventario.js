/* Control de inventario (Fase 1.5). Lee window.EVENT_ID / CAN_REPORT / ENABLED (los pone la plantilla). Sin manejadores en línea. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  const busy = (btn, work) => (window.GW && window.GW.busy ? window.GW.busy(btn, work) : Promise.resolve(work()));
  let users = [], person = null, items = [];
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
    $('statStock').textContent = items.filter(i => i.available > 0).length;
    $('statOut').textContent = items.filter(i => i.available <= 0).length;
    $('statOutBox').classList.toggle('gw-stat--err', items.some(i => i.available <= 0));
    box.innerHTML = items.length ? items.map(i => `
      <div class="gw-card-row gw-ai__item item-row ${i.available <= 0 ? 'empty' : ''}" data-item="${i.id}">
        <div><strong class="gw-card-row__title">${esc(i.name)}</strong> <span class="gw-ai__avail"><span class="gw-ai__avail-num">${i.available}</span> disponibles de ${i.initial_qty}${i.available <= 0 ? ' · <span class="gw-badge gw-badge--err">Agotado</span>' : ''}</span></div>
        <div>${i.allow_multiple
          ? `<label class="gw-sr-only" for="qty${i.id}">Cantidad de ${esc(i.name)}</label><input type="number" id="qty${i.id}" class="gw-input qty" min="0" max="${Math.max(i.available, 0)}" value="0" ${i.available <= 0 ? 'disabled' : ''}>`
          : `<label class="gw-check"><input type="checkbox" class="qty-check" ${i.available <= 0 ? 'disabled' : ''}> Entregar 1</label>`}</div>
      </div>`).join('') : `<div class="gw-state gw-empty--hero"><span class="gw-state__icon">${icon('inbox')}</span><p class="gw-state__title">No hay ítems en el inventario. Un coordinador los crea en Parámetros del evento.</p></div>`;
  }

  async function loadDeliveries() {
    let rows;
    try { rows = await getJson(`/api/events/${window.EVENT_ID}/inventory/deliveries`); }
    catch (e) { setDelState('No se pudieron cargar las entregas. Recarga la página.', true); return; }
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
  function byId(id) {
    const u = users.find(x => x.id === id);
    if (u) setPerson(u); else showToast('Esa persona no está en la base de este evento', 'error');
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
      byId(qr && qr.isQr ? qr.cedula : (parsed ? parsed.cedula : raw));   // QR propio: en vez de entregar la cédula
    }).catch((err) => { if (typeof showToast === 'function') showToast(err.message || 'No se pudo validar el código', 'error'); });
  });
  // Cámara del dispositivo: cada QR leído elige a la persona a la que se le entrega.
  if ($('scanQrBtn')) $('scanQrBtn').addEventListener('click', () => QrScanner.open({
    title: 'Escanear QR — Control de Inventario',
    onCode: (text) => { QrCode.resolveDynamic(text, window.EVENT_ID, 'inventory').then((raw) => { const qr = QrCode.parse(raw); if (qr) byId(qr.cedula); }).catch((err) => { if (typeof showToast === 'function') showToast(err.message || 'No se pudo validar el código', 'error'); }); },
  }));
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
    const lines = [];
    document.querySelectorAll('.item-row').forEach(row => {
      const id = parseInt(row.dataset.item, 10);
      const qty = row.querySelector('.qty') ? parseInt(row.querySelector('.qty').value, 10) || 0 : (row.querySelector('.qty-check').checked ? 1 : 0);
      if (qty > 0) lines.push({ item_id: id, qty });
    });
    if (!lines.length) { showToast('Elige al menos un ítem', 'error'); return; }
    let res, data;
    try {
      res = await fetch(`/api/events/${window.EVENT_ID}/inventory/deliver`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cedula: person.id, items: lines }) });
      data = await res.json().catch(() => ({}));
    } catch (e) { res = null; data = { detail: 'No se pudo entregar: sin conexión con el servidor. Inténtalo de nuevo.' }; }
    if (!res || !res.ok) { verdict(res ? 'warn' : 'err', res ? 'No se pudo entregar' : 'Sin conexión', esc(data.detail || 'No se pudo entregar')); return; }
    verdict('ok', 'Entregado', `<strong>${esc(person.first_name)} ${esc(person.last_name)}</strong>: ${data.delivered.map(d => `${d.qty} × ${esc(d.name)}`).join(', ')}. Quedan: ${data.stock.map(s => `${esc(s.name)} ${s.available}`).join(' · ')}`);
    await loadItems(); loadDeliveries();
  }
  $('deliverBtn').addEventListener('click', (e) => busy(e.currentTarget, deliver));

  init();
})();
