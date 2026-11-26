/* Control de inventario (Fase 1.5). Lee window.EVENT_ID / CAN_REPORT / ENABLED (los pone la plantilla). Sin manejadores en línea. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  const busy = (btn, work) => (window.GW && window.GW.busy ? window.GW.busy(btn, work) : Promise.resolve(work()));
  let users = [], person = null, items = [], delivering = false, lastBatches = new Set();
  const AUTOSCAN = !!window.AUTOSCAN;          // Fase 10: «escanear / Enter = entrega automática» (Parámetros): al leer a la persona se entrega lo que esté marcado, sin pulsar «Entregar»
  const ASSIGNED = !!window.INV_ASSIGNED;          // 0161: «La base lo define»: no se elige; static/js/inventario-asignado.js muestra lo que le toca a cada persona
  /* 0161: lo marcado se recuerda en esta tableta; con «Bloquear configuración» (Parámetros) el digitador no lo puede cambiar sin la contraseña. */
  const SEL_KEY = 'gw-inv-sel:' + window.EVENT_ID;
  const LOCK = window.GWConfigLock || { isLocked: () => false, banner: () => {}, onChange: () => {} };
  const locked = () => !ASSIGNED && LOCK.isLocked('inventory');
  function saveSel() { try { localStorage.setItem(SEL_KEY, JSON.stringify(selection())); } catch (e) { /* sin almacenamiento: no se recuerda */ } }
  function readSel() { try { return JSON.parse(localStorage.getItem(SEL_KEY) || '{}') || {}; } catch (e) { return {}; } }
  function paintLock() {
    const on = locked();
    document.querySelectorAll('#itemsList .qty, #itemsList .qty-check, #itemsList .qty-none').forEach(el => { if (on) { el.dataset.gwWasDisabled = el.disabled ? '1' : ''; el.disabled = true; } else if (el.dataset.gwWasDisabled !== undefined) { el.disabled = el.dataset.gwWasDisabled === '1'; delete el.dataset.gwWasDisabled; } });
    document.getElementById('itemsList').classList.toggle('gw-locked-ctl', on);
  }
  const sprite = () => { const u = document.querySelector('.gw-icon use'); return u ? u.getAttribute('href').split('#')[0] : ''; };
  const icon = (name) => `<svg class="gw-icon" aria-hidden="true"><use href="${sprite()}#i-${name}"/></svg>`;
  function verdict(cls, title, html) {
    const b = $('resultBanner');
    b.className = 'gw-verdict gw-verdict--' + cls;
    b.setAttribute('role', cls === 'err' ? 'alert' : 'status');
    b.innerHTML = `<svg class="gw-icon gw-verdict__icon" aria-hidden="true"><use href="${sprite()}#i-${cls === 'ok' ? 'check-lg' : (cls === 'err' ? 'error' : 'alert')}"/></svg><div class="gw-verdict__body"><p class="gw-verdict__title">${esc(title)}</p><p class="gw-verdict__text">${html}</p></div>`;
    b.hidden = false;
  }

  /* Sin red (docs/28, static/js/offline-data.js): las lecturas salen de la última copia cifrada del dispositivo y cada entrega se guarda y se envía al volver la conexión. */
  const OFF = window.GWOff || null;
  const itemsUrl = () => `/api/events/${window.EVENT_ID}/inventory`, delUrl = () => `/api/events/${window.EVENT_ID}/inventory/deliveries`;
  async function getJson(url) {
    if (OFF) return OFF.json(url);
    const res = await fetch(url);
    if (!res.ok) throw new Error('http ' + res.status);
    return res.json();
  }

  async function init() {
    if (!window.ENABLED) return;
    if (window.CAN_REPORT) $('reportBtn').hidden = false;
    try { users = OFF ? await OFF.users() : await getJson(`/api/users?event_id=${window.EVENT_ID}`); }
    catch (e) { showToast('No se pudo cargar la base de personas. Recarga la página.', 'error'); }
    await loadItems(); loadDeliveries();
    $('scanInput').focus();
  }

  async function loadItems() {
    const box = $('itemsList');
    $('itemsLoading').hidden = false;
    try { items = await getJson(itemsUrl()); }
    catch (e) {
      $('itemsLoading').hidden = true;
      box.innerHTML = `<div class="gw-state gw-state--error gw-empty--hero" role="alert"><span class="gw-state__icon">${icon('error')}</span><p class="gw-state__title">No se pudo cargar el inventario. Revisa la conexión y recarga la página.</p></div>`;
      return;
    }
    $('itemsLoading').hidden = true;
    // Lo marcado se conserva entre personas con entrega automática o con la configuración bloqueada (0161: también entre recargas); si no, como siempre, la lista vuelve en blanco.
    // 25-nov-2026: lo marcado ya no se borra después de cada entrega (arriba se ve «Estás entregando…»); entre recargas solo se recuerda con entrega automática o configuración bloqueada.
    const sticky = AUTOSCAN || !!(LOCK.state && LOCK.state.inventory);
    const keep = document.querySelector('.item-row') ? selection() : (sticky ? readSel() : {});
    const real = items.filter(i => !i.is_group);
    $('statStock').textContent = real.filter(i => i.available > 0).length;
    $('statOut').textContent = real.filter(i => i.available <= 0).length;
    $('statOutBox').classList.toggle('gw-stat--err', real.some(i => i.available <= 0));
    // Subcategorías: se entrega una subcategoría (nunca el grupo); se muestra «Comida › Perro» y el disponible es el de cada una.
    const byId = {}; items.forEach(i => { byId[i.id] = i; });
    // ¿Varias unidades de este ítem en una entrega? Igual que el servidor (multi_units_allowed): «varias a la vez», o límite propio > 1, o (sin límite propio) el grupo permite más de 1.
    const multiOk = (i, g) => !!i.allow_multiple || (i.max_per_person != null ? i.max_per_person > 1 : !!(g && g.max_per_person > 1));
    /* 26-nov-2026 (Juan David): cuánto se le puede entregar a cada persona, según Parámetros › Control de inventario: el límite propio del ítem o, si no tiene, el de su grupo. */
    const unidades = (n) => `${n} unidad${n === 1 ? '' : 'es'}`;
    const limitText = (i, g) => {
      if (i.max_per_person != null) return `Solo se puede entregar ${i.max_per_person} por persona`;
      if (g && g.max_per_person != null) return `Solo se puede entregar ${g.max_per_person} por persona (contando todo «${g.name}»)`;
      if (i.allow_repeat_delivery === false) return 'Solo se entrega una vez por persona';
      return 'Sin límite por persona';
    };
    const row = (i, label, radioName, g) => `
      <div class="gw-card-row gw-ai__item item-row ${i.available <= 0 ? 'empty' : ''}" data-item="${i.id}">
        <div><strong class="gw-card-row__title">${esc(label)}</strong> <span class="gw-ai__avail"><span class="gw-ai__avail-num">${i.available}</span> disponibles de ${i.initial_qty}${i.available <= 0 ? ' · <span class="gw-badge gw-badge--err">Agotado</span>' : ''}</span><span class="gw-ai__limit">${esc(limitText(i, g))}</span></div>
        <div>${radioName
          ? `<label class="gw-check"><input type="radio" name="${radioName}" class="qty-check" ${i.available <= 0 ? 'disabled' : ''}> Elegir</label>`
          : (i.multi
            ? `<label class="gw-sr-only" for="qty${i.id}">Cantidad de ${esc(i.name)}</label><input type="number" id="qty${i.id}" class="gw-input qty" min="0" max="${Math.max(Math.min(i.available, i.max_per_person || i.available, (i.group_max || i.available)), 0)}" value="0" ${i.available <= 0 ? 'disabled' : ''}>`
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
      const rule = one ? 'Solo se puede entregar 1 por persona: elige una opción o «Nada elegido»' : (g.max_per_person ? `Solo se puede entregar ${unidades(g.max_per_person)} en total por persona (entre todas las opciones)` : 'Sin límite por persona');
      /* 25-nov-2026: en las de elegir una, «Nada elegido» permite quitar la opción (antes, una vez marcada, siempre quedaba alguna). */
      const none = one ? `<div class="gw-card-row gw-ai__item gw-ai__item--none"><div><strong class="gw-card-row__title">Nada elegido</strong> <span class="gw-ai__avail">no se entrega nada de ${esc(g.name)}</span></div><div><label class="gw-check"><input type="radio" name="grp${g.id}" class="qty-none" checked> Elegir</label></div></div>` : '';
      return `<fieldset class="gw-ai__group" data-group="${g.id}" data-max="${g.max_per_person || ''}"><legend><strong>${esc(g.name)}</strong>${rule ? ` · <span class="gw-ai__avail">${esc(rule)}</span>` : ''}</legend>${kids.map(k => row(Object.assign({}, k, { multi: multiOk(k, g), group_max: g.max_per_person || 0 }), k.name, one ? 'grp' + g.id : '', g)).join('')}${none}</fieldset>`;
    }).join('');
    const loose = items.filter(i => !i.is_group && !grouped.has(i.id)).map(i => (i.parent_id && byId[i.parent_id] ? Object.assign({}, i, { name: byId[i.parent_id].name + ' › ' + i.name }) : i));
    html += loose.map(i => row(Object.assign({}, i, { multi: multiOk(i, i.parent_id ? byId[i.parent_id] : null) }), i.name, '', i.parent_id ? byId[i.parent_id] : null)).join('');
    box.innerHTML = html || `<div class="gw-state gw-empty--hero"><span class="gw-state__icon">${icon('inbox')}</span><p class="gw-state__title">No hay ítems en el inventario. Un coordinador los crea en Parámetros del evento.</p></div>`;
    restore(keep);
    paintHero();
    if (!ASSIGNED) {
      paintLock();
      LOCK.banner($('lockBar'), 'inventory', () => { const sel = selection(); const names = items.filter(i => sel[i.id]).map(i => `${sel[i.id]} × ${i.name}`); return names.length ? 'se entrega ' + names.join(', ') : 'no hay nada marcado'; });
    }
  }
  document.addEventListener('change', (e) => { if (e.target.closest && e.target.closest('#itemsList')) { saveSel(); paintHero(); } });
  document.addEventListener('input', (e) => { if (e.target.classList && e.target.classList.contains('qty')) paintHero(); });
  /* 25-nov-2026 (Juan David): arriba, en grande, lo que se está entregando (lo marcado), una fila por cada cosa con sus cifras: «Lechona · 916 disponibles de 917 · 1 entregada». */
  /* Lo marcado, en celdas grandes dentro de la tarjeta de la persona (inventario elegido). */
  function paintCardSel() {
    const box = $('pcardSel'); if (!box) return;
    const sel = selection(), byIdx = {}; items.forEach(i => { byIdx[i.id] = i; });
    const chosen = Object.keys(sel).map(id => byIdx[id]).filter(Boolean);
    const label = (i) => (i.parent_id && byIdx[i.parent_id] ? byIdx[i.parent_id].name + ' › ' : '') + i.name;
    box.innerHTML = chosen.length
      ? '<p class="gw-pcard__deliver-title">Estás entregando:</p>' + chosen.map(i => `<div class="gw-pcard__cell"><span class="gw-pcard__cell-name">${esc(label(i))}</span><span class="gw-pcard__cell-qty">${sel[i.id]} unidad${sel[i.id] === 1 ? '' : 'es'}</span></div>`).join('')
      : '<p class="gw-alert gw-alert--warn">Todavía no has elegido qué entregar: márcalo en «2. ¿Qué se le entrega?».</p>';
    const go = $('deliverHereBtn'); if (go) go.disabled = !chosen.length;
  }
  function paintHero() {
    paintCardSel();
    const hero = $('invHero'); if (!hero) return;
    const sel = selection(), byIdx = {}; items.forEach(i => { byIdx[i.id] = i; });
    const chosen = Object.keys(sel).map(id => byIdx[id]).filter(Boolean);
    hero.classList.toggle('gw-hero--empty', !chosen.length);
    const label = (i) => (i.parent_id && byIdx[i.parent_id] ? byIdx[i.parent_id].name + ' › ' : '') + i.name;
    const delivered = (i) => (i.delivered != null ? i.delivered : Math.max(0, (i.initial_qty || 0) - (i.available || 0)));
    hero.innerHTML = '<p class="gw-hero__kicker">Estás entregando</p>' + (chosen.length
      ? chosen.map(i => { const d = delivered(i); return `<div class="gw-hero__row"><span class="gw-hero__title">${esc(label(i))}${sel[i.id] > 1 ? ` <span class="gw-hint">(${sel[i.id]} por persona)</span>` : ''}</span><span class="gw-hero__stats"><b>${i.available}</b> disponibles de <b>${i.initial_qty}</b> · <b>${d}</b> ${d === 1 ? 'entregada' : 'entregadas'}${i.available <= 0 ? ' · <span class="gw-badge gw-badge--err">Agotado</span>' : ''}</span></div>`; }).join('')
      : '<div class="gw-hero__row"><span class="gw-hero__title">Todavía no has elegido qué entregar (márcalo abajo en «2. ¿Qué se le entrega?»)</span></div>');
  }
  LOCK.onChange((scope) => { if (scope === 'inventory') paintLock(); });
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
    try { rows = await getJson(delUrl()); }
    catch (e) { setDelState('No se pudieron cargar las entregas. Recarga la página.', true); return; }
    lastBatches = new Set(rows.map(r => r.batch_id));
    $('statDeliveries').textContent = rows.length;
    if (!rows.length) { setDelState('Sin entregas todavía. Elige a una persona y entrega el primer ítem.', false); $('delBody').innerHTML = ''; return; }
    $('delState').hidden = true; $('delWrap').hidden = false;
    $('delBody').innerHTML = delTable(rows, false);
  }
  /* 26-nov-2026: tabla con columnas alineadas (fecha y hora, persona, cédula, qué se entregó y, en el historial, quién entregó). */
  const when = (t) => { const d = new Date(String(t).replace(/Z?$/, 'Z')); return isNaN(d) ? '' : d.toLocaleString('es-CO', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }); };
  function delTable(rows, withBy) {
    return `<div class="gw-table-wrap"><table class="gw-table gw-inv-del"><thead><tr><th scope="col">Fecha y hora</th>${withBy ? '' : '<th scope="col">Persona</th><th scope="col">Cédula</th>'}<th scope="col">Se entregó</th>${withBy ? '<th scope="col">Entregó</th>' : ''}</tr></thead><tbody>`
      + rows.map(r => `<tr><td class="gw-inv-del__time">${esc(when(r.time))}</td>${withBy ? '' : `<td>${esc(r.name)}</td><td class="gw-inv-del__num">${esc(r.user_id)}</td>`}<td><span class="gw-badge gw-badge--ok">${esc(r.qty)} × ${esc(r.item)}</span></td>${withBy ? `<td>${esc(r.by || '—')}</td>` : ''}</tr>`).join('')
      + '</tbody></table></div>';
  }
  /* Buscador del historial (solo coordinador en adelante): el MISMO buscador de arriba (cédula, nombre, código, lector o cámara), pero no toca a quién se le entrega. */
  async function showHistory(u) {
    const box = $('histResult'); if (!box) return;
    box.hidden = false; box.innerHTML = `<p class="gw-hint">Buscando el historial de ${esc(u.first_name || '')} ${esc(u.last_name || '')}…</p>`;
    let data;
    try {
      const r = await fetch(`/api/events/${window.EVENT_ID}/inventory/deliveries/person?cedula=${encodeURIComponent(u.id)}`);
      data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || 'No se pudo consultar el historial');
    } catch (e) { box.innerHTML = `<p class="gw-alert gw-alert--err" role="alert">${esc(e.message && e.message !== 'Failed to fetch' ? e.message : 'Sin conexión: el historial de una persona necesita internet.')}</p>`; return; }
    const p = data.person || u, rows = data.deliveries || [];
    const head = `<div class="gw-inv-hist__head"><div><p class="gw-inv-hist__name">${esc(p.first_name || '')} ${esc(p.last_name || '')}</p><p class="gw-hint">Cédula: ${esc(p.id)}${p.code ? ' · Código: ' + esc(p.code) : ''} · ${rows.length} entrega${rows.length === 1 ? '' : 's'}</p></div><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" id="histClose">Cerrar historial</button></div>`;
    box.innerHTML = head + (rows.length ? delTable(rows, true) : '<p class="gw-alert gw-alert--info">A esta persona todavía no se le ha entregado nada.</p>');
  }
  if ($('histInput')) {
    const hist = PersonFinder.attach({
      input: $('histInput'), box: $('histSuggest'), users: () => users, purpose: 'inventory',
      onPick: (u) => showHistory(u),
      onRaw: (ced) => { const u = users.find(x => x.id === ced); if (u) showHistory(u); else showToast('Esa persona no está en la base de este evento', 'error'); },
    });
    $('histResult').addEventListener('click', (e) => { if (e.target.closest('#histClose')) { $('histResult').hidden = true; $('histResult').innerHTML = ''; } });
    if ($('histScanBtn')) $('histScanBtn').addEventListener('click', () => { const sc = QrScanner.open({
      title: 'Escanear cédula o QR — Historial de entregas', formats: ['qr_code', 'pdf417'], modes: ['old', 'new', 'qr'],
      onCedula: (d) => { $('histInput').value = d.cedula; hist.submit(); sc.close(); },
      onCode: (text) => { $('histInput').value = text; hist.submit(); sc.close(); },
    }); });
  }
  function setDelState(text, isError) {
    const st = $('delState'); st.innerHTML = `<span class="gw-state__icon">${icon(isError ? 'error' : 'inbox')}</span><p class="gw-state__title">${esc(text)}</p>`; st.hidden = false; st.classList.toggle('gw-state--error', !!isError); $('delWrap').hidden = true;
  }

  function setPerson(u) {
    if (!u) return;
    if (!person || person.id !== u.id) { const rb = $('resultBanner'); if (rb) rb.hidden = true; }          // el resultado anterior era de otra persona
    person = u;
    const b = $('personBanner');
    // 25-nov-2026: la tarjeta muestra lo marcado «Mostrar en el registro» y si está o no registrada (en rojo si no); el botón «Entregar» va aquí mismo, junto a la persona.
    const full = users.find(x => x.id === u.id) || u;
    /* 26-nov-2026 (Juan David): lo que se entrega va DENTRO de la tarjeta, debajo de «Registrado», grande. «La base lo define»: una celda por regalo con su propio «Entregar»
       (la llena static/js/inventario-asignado.js); inventario elegido: lo marcado en celdas y un solo «Entregar» grande. */
    const action = ASSIGNED ? '<div class="gw-pcard__deliver" id="pcardAssign" aria-live="polite"><p class="gw-hint">Buscando lo que le corresponde…</p></div>'
      : `<div class="gw-pcard__deliver" id="pcardSel"></div><button type="button" class="gw-btn gw-btn--primary gw-btn--xl gw-pcard__go" id="deliverHereBtn">${icon('check-lg')} Entregar</button>`;
    const card = window.GWPersonCard ? GWPersonCard.render(full, { action }) : null;
    if (card) { b.className = card.cls + ' gw-ai__person'; b.innerHTML = card.html; }
    else b.innerHTML = `<div class="gw-person__body"><h3 class="gw-person__name">${esc(u.first_name)} ${esc(u.last_name)}</h3><p class="gw-person__meta">${esc(u.id)}</p></div>`;
    b.hidden = false;
    paintCardSel();
    $('suggest').innerHTML = ''; $('suggest').hidden = true;
    if (ASSIGNED && window.GWInvAssigned) window.GWInvAssigned.show(u, { auto: AUTOSCAN && !!u.__auto });
  }
  function byId(id, auto) {
    // Primero identificación y, si el evento usa código, el código (0140)
    const low = String(id || '').trim().toLowerCase();
    const byCode = low ? users.find(x => x.code && String(x.code).toLowerCase() === low) : null;
    const u = window.EVENT_CODE_ONLY === true ? byCode : (window.EVENT_CODE_FIRST === true ? (byCode || users.find(x => x.id === id)) : (users.find(x => x.id === id) || byCode));          // 0166/0168
    if (!u) { showToast('Esa persona no está en la base de este evento', 'error'); return false; }
    setPerson(Object.assign({}, u, { __auto: !!auto }));
    if (auto && AUTOSCAN && !ASSIGNED) deliver();          // entrega automática: la lectura (o el Enter) de la persona entrega lo marcado
    return true;
  }

  // Buscador único (static/js/person-finder.js): cédula, nombre, empresa o código con coincidencias en vivo; QR propio, vCard (de Golden o ajena), dinámico y lector de mano.
  PersonFinder.attach({
    input: $('scanInput'), box: $('suggest'), users: () => users, purpose: 'inventory',
    onPick: (u) => { setPerson(Object.assign({}, u, { __auto: true })); if (AUTOSCAN && !ASSIGNED) deliver(); },          // entrega automática: leer (o elegir) a la persona entrega lo marcado
    onRaw: () => showToast('Esa persona no está en la base de este evento', 'error'),
    onTyping: (t) => { if (String(t || '').trim() && person) clearPerson(); },          // 26-nov-2026: al escribir otra búsqueda se quita la tarjeta anterior (no queda «elegida»)
  });
  function clearPerson() {
    person = null;
    const b = $('personBanner'); b.hidden = true; b.innerHTML = '';
    const rb = $('resultBanner'); if (rb) rb.hidden = true;
    if (ASSIGNED && $('assignedBox')) $('assignedBox').innerHTML = '<div class="gw-state gw-empty--hero"><p class="gw-state__title">Escanea o busca a la persona para ver lo que le corresponde.</p></div>';
  }
  // Cámara del dispositivo: el MISMO escáner del Registro y de Control de áreas (selector «Cédula vieja · Cédula nueva · QR»); cada lectura elige a la persona a la que se le entrega.
  // Si la cámara lee el código y encuentra a la persona, se cierra sola (con entrega automática, después de lanzarla); si no la encuentra o falla, queda abierta con el aviso.
  let scanner = null;
  if (window.QrScanner && QrScanner.warm && $('scanQrBtn')) QrScanner.warm();          // deja listo el lector de cédula en reposo (abrir la cámara no traba)
  if ($('scanQrBtn')) $('scanQrBtn').addEventListener('click', () => { scanner = QrScanner.open({
    title: 'Escanear cédula o QR — Control de Inventario',
    formats: ['qr_code', 'pdf417'],
    modes: ['old', 'new', 'qr'],                       // cédula vieja (código de barras) · cédula nueva (3 líneas) · QR
    onCedula: (d) => { if (byId(d.cedula, true) && scanner) scanner.close(); },
    onCode: (text, format) => { QrCode.resolveDynamic(text, window.EVENT_ID, 'inventory').then((raw) => {
        const r = QrCode.classify(raw, format, window.GoldenDirectory && GoldenDirectory.parseOldCedulaBarcode);
        if (!r) { showToast('No se reconoció el código: acerca la cámara al QR o al reverso de la cédula', 'error'); return false; }
        return byId(r.cedula, true); })
      .then((found) => { if (found && scanner) scanner.close(); })
      .catch((err) => { if (typeof showToast === 'function') showToast(err.message || 'No se pudo validar el código', 'error'); }); },
  }); });
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
      const url = `/api/events/${window.EVENT_ID}/inventory/deliver`, opts = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cedula: person.id, items: lines }) };
      const who = `${person.first_name || ''} ${person.last_name || ''}`.trim();
      if (OFF && OFF.off()) {                                           // sin red: lo que el dispositivo puede comprobar (existencias y «no repetir»); el resto de reglas las aplica el servidor al recibirlo
        const byItem = {}; items.forEach(i => { byItem[i.id] = i; });
        const prev = (await OFF.get(delUrl())) || [];
        for (const ln of lines) {
          const it = byItem[ln.item_id];
          if (!it || it.available < ln.qty) { verdict('warn', 'No se pudo entregar', `No hay existencias suficientes de ${esc(it ? it.name : 'ese ítem')}.`); return; }
          if (!it.allow_repeat_delivery && prev.some(r => r.user_id === person.id && r.item_id === it.id)) { verdict('warn', 'No se pudo entregar', `${esc(who)} ya recibió ${esc(it.name)} (este ítem no se repite).`); return; }
        }
      }
      res = OFF ? await OFF.send(url, opts, `Entrega a ${who}`) : await fetch(url, opts);
      if (res.queued) {                                                  // guardada en el dispositivo: la copia local de existencias y de entregas queda al día
        const byItem = {}; items.forEach(i => { byItem[i.id] = i; });
        const now = new Date().toISOString().replace(/Z$/, ''), batch = 'local-' + Date.now();
        const mine = lines.map(ln => ({ time: now, user_id: person.id, batch_id: batch, name: who, item: (byItem[ln.item_id] || {}).name || '', item_id: ln.item_id, qty: ln.qty }));
        await OFF.put(itemsUrl(), items.map(i => { const q = lines.filter(ln => ln.item_id === i.id || (i.is_group && (byItem[ln.item_id] || {}).parent_id === i.id)).reduce((n, ln) => n + ln.qty, 0); return q ? Object.assign({}, i, { available: i.available - q, delivered: (i.delivered || 0) + q }) : i; }));
        await OFF.put(delUrl(), mine.concat((await OFF.get(delUrl())) || []).slice(0, 200));
        verdict('ok', 'Entregado', `<strong>${esc(who)}</strong>: ${mine.map(d => `${d.qty} × ${esc(d.item)}`).join(', ')}. Sin conexión: queda guardado en este dispositivo y se envía solo al volver la red.`);
        await loadItems(); await loadDeliveries();
        return;
      }
      data = await res.json().catch(() => ({}));
    } catch (e) { res = null; data = { detail: 'No se pudo entregar: sin conexión con el servidor. Inténtalo de nuevo.' }; }
    if (!res || !res.ok) { verdict(res ? 'warn' : 'err', res ? 'No se pudo entregar' : 'Sin conexión', esc(data.detail || 'No se pudo entregar')); return; }
    verdict('ok', 'Entregado', `<strong>${esc(person.first_name)} ${esc(person.last_name)}</strong>: ${data.delivered.map(d => `${d.qty} × ${esc(d.name)}`).join(', ')}. Quedan: ${data.stock.map(s => `${esc(s.name)} ${s.available}`).join(' · ')}`);
    await loadItems(); await loadDeliveries();
    // Comprobación: lo «entregado» tiene que aparecer en el registro. Si no aparece, NO se da por entregado (así no queda una entrega fantasma en pantalla).
    if (data.batch_id && !lastBatches.has(data.batch_id)) verdict('err', 'Revisa esta entrega', `No aparece en el registro del evento. Recarga la página y comprueba antes de volver a entregar: <strong>${esc(person.first_name)} ${esc(person.last_name)}</strong>.`);
  }
  $('deliverBtn').addEventListener('click', (e) => busy(e.currentTarget, deliver));
  $('personBanner').addEventListener('click', (e) => { const btn = e.target.closest('#deliverHereBtn'); if (btn) busy(btn, deliver); });
  window.GWInv = { verdict, esc, icon, busy, reload: async () => { await loadItems(); await loadDeliveries(); }, pickById: (id) => byId(id, false), lastBatches: () => lastBatches };

  init();
})();
