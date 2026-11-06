/* Control de inventario (Fase 1.5). Lee window.EVENT_ID / CAN_REPORT / ENABLED (los pone la plantilla). Sin manejadores en línea. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  const busy = (btn, work) => (window.GW && window.GW.busy ? window.GW.busy(btn, work) : Promise.resolve(work()));
  let users = [], person = null, items = [];

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
      box.innerHTML = '<div class="gw-empty gw-state--error" role="alert">No se pudo cargar el inventario. Revisa la conexión y recarga la página.</div>';
      return;
    }
    $('itemsLoading').hidden = true;
    box.innerHTML = items.length ? items.map(i => `
      <div class="gw-ai__item item-row ${i.available <= 0 ? 'empty' : ''}" data-item="${i.id}">
        <div><strong>${esc(i.name)}</strong> <span class="gw-ai__avail">Disponibles: <strong>${i.available}</strong> de ${i.initial_qty}${i.available <= 0 ? ' (agotado)' : ''}</span></div>
        <div>${i.allow_multiple
          ? `<label class="gw-sr-only" for="qty${i.id}">Cantidad de ${esc(i.name)}</label><input type="number" id="qty${i.id}" class="gw-input qty" min="0" max="${Math.max(i.available, 0)}" value="0" ${i.available <= 0 ? 'disabled' : ''}>`
          : `<label class="gw-check"><input type="checkbox" class="qty-check" ${i.available <= 0 ? 'disabled' : ''}> Entregar 1</label>`}</div>
      </div>`).join('') : '<div class="gw-empty">No hay ítems en el inventario. Un coordinador los crea en Parámetros del evento.</div>';
  }

  async function loadDeliveries() {
    let rows;
    try { rows = await getJson(`/api/events/${window.EVENT_ID}/inventory/deliveries`); }
    catch (e) { setDelState('No se pudieron cargar las entregas. Recarga la página.', true); return; }
    if (!rows.length) { setDelState('Sin entregas todavía. Elige a una persona y entrega el primer ítem.', false); $('delBody').innerHTML = ''; return; }
    $('delState').hidden = true; $('delWrap').hidden = false;
    $('delBody').innerHTML = rows.map(r => `<tr><td data-label="Hora">${new Date(r.time + 'Z').toLocaleTimeString()}</td><td data-label="Persona">${esc(r.name)} <span class="gw-hint">(${esc(r.user_id)})</span></td><td data-label="Ítem">${esc(r.item)}</td><td data-label="Cant.">${r.qty}</td></tr>`).join('');
  }
  function setDelState(text, isError) {
    const st = $('delState'); st.textContent = text; st.hidden = false; st.classList.toggle('gw-state--error', !!isError); $('delWrap').hidden = true;
  }

  function setPerson(u) {
    if (!u) return;
    person = u;
    const b = $('personBanner');
    const sp = document.querySelector('.gw-icon use');
    const href = sp ? sp.getAttribute('href').split('#')[0] : '';
    b.innerHTML = `<svg class="gw-icon" aria-hidden="true"><use href="${href}#i-check"/></svg><div>Entregando a: <strong>${esc(u.first_name)} ${esc(u.last_name)}</strong> (${esc(u.id)})</div>`;
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
    const raw = e.target.value.trim(); e.target.value = '';
    if (!raw) return;
    const qr = QrCode.parse(raw);
    const parsed = GoldenDirectory.parseOldCedulaBarcode(raw);
    byId(qr && qr.isQr ? qr.cedula : (parsed ? parsed.cedula : raw));   // QR propio: en vez de entregar la cédula
  });
  // Cámara del dispositivo: cada QR leído elige a la persona a la que se le entrega.
  if ($('scanQrBtn')) $('scanQrBtn').addEventListener('click', () => QrScanner.open({
    title: 'Escanear QR — Control de Inventario',
    onCode: (text) => { const qr = QrCode.parse(text); if (qr) byId(qr.cedula); },
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
    const banner = $('resultBanner');
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
    banner.hidden = false;
    if (!res || !res.ok) { banner.className = 'gw-alert gw-alert--warn'; banner.textContent = data.detail || 'No se pudo entregar'; return; }
    banner.className = 'gw-alert gw-alert--ok';
    banner.innerHTML = `Entregado a <strong>${esc(person.first_name)} ${esc(person.last_name)}</strong>: ${data.delivered.map(d => `${d.qty} × ${esc(d.name)}`).join(', ')}. Quedan: ${data.stock.map(s => `${esc(s.name)} ${s.available}`).join(' · ')}`;
    await loadItems(); loadDeliveries();
  }
  $('deliverBtn').addEventListener('click', (e) => busy(e.currentTarget, deliver));

  init();
})();
