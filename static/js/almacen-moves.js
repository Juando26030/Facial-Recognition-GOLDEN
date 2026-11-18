/* Almacén (Inventario → pestaña «Almacén», Pieza 2): salidas y entradas por QR (lector USB o cámara) a un evento, aviso (sin bloqueo) cuando falta asignar lo que sale, checklist del evento
   con la casilla «OK S/N» por fila, equipos fuera de bodega y anulación del último movimiento. API: /api/almacen/move, /movements/{id}/void, /events/{id}/board, /events/{id}/checklist/{fila}
   y /api/inventory/events (lista de eventos de siempre). Todo se escapa; sin manejadores en línea (delegación); mensajes con showToast / showConfirm. */
(function () {
  'use strict';
  const root = document.getElementById('invPanelAlm');
  if (!root) return;
  const tab = document.getElementById('invTabAlm');
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const STATUS = { creado: 'Creado', en_proceso: 'En proceso', finalizado: 'Finalizado' };
  let events = [];
  let scanner = null;          // ventana de la cámara (qr.js), si está abierta
  let loaded = false;
  let busyMove = false;

  async function j(url, opts) {
    const r = await fetch(url, opts);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(typeof d.detail === 'string' ? d.detail : (d.detail && d.detail.message) || 'Error'); e.status = r.status; e.detail = d.detail; throw e; }
    return d;
  }
  const send = (url, method, body) => j(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const fail = (e) => showToast(e && e.message ? e.message : 'No se pudo completar la acción', 'error');
  const mode = () => (root.querySelector('input[name=almMvMode]:checked') || {}).value || 'salida';
  const eventId = () => Number($('almMvEvent').value) || null;
  const camOpen = () => !!document.querySelector('.gw-cam .qr-status');
  const focusScan = () => { const s = $('almMvScan'); if (s && !s.disabled) s.focus(); };

  /* ---- eventos: un solo buscador (igual al de Inicio: sin tildes ni mayúsculas, «N de M eventos») */
  const norm = (v) => String(v == null ? '' : v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const fmtDate = (d) => (d ? new Date(d).toLocaleDateString('es-CO') : '');
  const eventMeta = (e) => [e.code, fmtDate(e.start_date), STATUS[e.status] || e.status].filter(Boolean).join(' · ');
  function renderEvents() {
    const q = norm($('almMvEventSearch').value).trim();
    const shown = q ? events.filter((e) => norm(e.name + ' ' + (e.code || '')).includes(q)) : events;
    const list = shown.slice(0, 12);
    $('almMvEventList').innerHTML = !list.length
      ? '<div class="gw-state" role="status"><p class="gw-state__title">Ningún evento coincide</p><p class="gw-state__text">Prueba con otra palabra o borra la búsqueda.</p></div>'
      : '<div class="gw-cards">' + list.map((e) => `<article class="gw-card-row"><div class="gw-card-row__head"><span class="gw-card-row__title">${esc(e.name)}</span>
          <span class="gw-badge${e.status === 'en_proceso' ? ' gw-badge--ok' : ''}">${esc(STATUS[e.status] || e.status)}</span></div>
          <p class="gw-card-row__meta">${esc([e.code, fmtDate(e.start_date)].filter(Boolean).join(' · '))}</p>
          <div class="gw-card-row__actions"><button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-alm-pick="${e.id}">Elegir este evento</button></div></article>`).join('') + '</div>';
    $('almMvEventInfo').textContent = q ? `${shown.length} de ${events.length} eventos` + (shown.length > list.length ? ` (se muestran ${list.length}; escribe más para acotar)` : '') : (events.length > list.length ? `Se muestran ${list.length} de ${events.length} eventos: escribe para buscar.` : '');
  }
  async function loadEvents() {
    const d = await j('/api/inventory/events');
    events = (d.events || []).filter((e) => e.status !== 'archivado');
    renderEvents();
  }
  function chooseEvent(id) {
    const e = events.find((x) => x.id === Number(id));
    $('almMvEvent').value = e ? String(e.id) : '';
    $('almMvEventChosenName').textContent = e ? e.name : 'ninguno elegido';
    $('almMvEventChosenMeta').textContent = e ? eventMeta(e) : '';
    $('almMvEventBox').open = !e;          // elegido: el bloque se pliega y deja ver solo el nombre; para cambiarlo basta con desplegarlo
    if (!e) { $('almMvEventSearch').value = ''; renderEvents(); }
    onEventChange();
  }
  function onEventChange() {
    const id = eventId();
    $('almMvScan').disabled = !id;
    $('almMvQrBtn').disabled = !id;
    $('almMvHint').textContent = id ? 'El lector escribe el código y pulsa Enter, o usa la cámara; cada lectura registra un movimiento.' : 'Primero elige el evento. El lector escribe el código y pulsa Enter, o usa la cámara; cada lectura registra un movimiento.';
    $('almMvResult').innerHTML = '';
    if (id) { loadBoard(); focusScan(); } else { $('almBoardCard').hidden = true; if (scanner) scanner.close(); }
  }

  /* ---- movimiento por lectura */
  function result(ok, text, warning) {
    $('almMvResult').innerHTML = `<div class="gw-state${ok ? '' : ' gw-state--error'}" role="${ok ? 'status' : 'alert'}"><p class="gw-state__title"><span class="gw-badge ${ok ? 'gw-badge--ok' : 'gw-badge--err'}">${ok ? 'Registrado' : 'No registrado'}</span> ${esc(text)}</p></div>`
      + (warning ? `<div class="gw-alert gw-alert--warn" role="status"><p><strong>Aviso:</strong> ${esc(warning)}</p></div>` : '');
    const st = document.querySelector('.gw-cam .qr-status');          // con la cámara abierta el resultado se ve en su ventana
    if (st) st.textContent = (ok ? '✓ ' : '✕ ') + text + (warning ? ' ⚠ ' + warning : '');
  }
  async function doMove(body) {
    if (busyMove) return false;
    busyMove = true;
    $('almMvScan').disabled = true;
    let ok = false;
    try {
      const d = await send('/api/almacen/move', 'POST', body);
      ok = true;
      result(true, d.message, d.warning);          // si falta asignar el elemento al evento: solo se avisa, el movimiento ya quedó registrado
      if (d.product && d.product.tracking !== 'serial') $('almMvQty').value = '1';
      await loadBoard();
    } catch (e) {
      result(false, e.message);
    }
    busyMove = false;
    $('almMvScan').disabled = !eventId();
    if (!camOpen()) focusScan();
    return ok;
  }
  async function onScan(raw) {
    const code = String(raw || '').trim();
    if (!code) return false;
    const body = { mode: mode(), code, event_id: eventId(), qty: Number($('almMvQty').value) || 1 };
    if (!body.event_id) { result(false, 'Primero elige el evento.'); return false; }
    return doMove(body);
  }
  /* Cámara del dispositivo (la misma ventana de qr.js que usan Registro, Áreas e Inventario): cada QR leído registra un movimiento y la ventana sigue abierta para el siguiente. */
  function openCamera() {
    if (!eventId()) { showToast('Primero elige el evento', 'error'); return; }
    if (!window.QrScanner) { showToast('El lector de cámara no está disponible en esta página', 'error'); return; }
    scanner = QrScanner.open({
      title: 'Escanear QR — Almacén',
      onCode: (text) => { onScan(text); },          // qr.js ya entrega el código limpio (una vCard de Golden se desenvuelve sola)
    });
  }

  /* ---- tablero del evento */
  function boardTable(rows) {
    let section = '';
    const body = rows.map((r) => {
      let head = '';
      if (r.section !== section) { section = r.section; head = `<tr class="gw-alm__sec"><th colspan="7" scope="colgroup">${esc(r.section_label)}</th></tr>`; }
      const inv = r.kind === 'inv';
      const num = (v) => `<td class="gw-alm__num">${inv ? v : '—'}</td>`;
      const flags = (r.extra ? ` <span class="gw-badge gw-badge--warn" title="Salió más de lo que pidió el evento">+${r.extra} extra</span>` : '') + (r.plan_b ? ' <span class="gw-badge gw-badge--info">Plan B</span>' : '');
      return head + `<tr data-alm-row="${esc(r.key)}"><th scope="row">${esc(r.label)}${flags}</th>${num(r.needed)}${num(r.out)}${num(r.returned)}
        <td class="gw-alm__num${inv && r.pending ? ' gw-alm__bad' : ''}">${inv ? r.pending : '—'}</td>
        <td><label class="gw-check"><input type="checkbox" data-alm-done="${esc(r.key)}"${r.done ? ' checked' : ''} aria-label="Alistado: ${esc(r.label)}"></label></td>
        <td class="gw-alm__note"><input class="gw-input" type="text" value="${esc(r.notes)}" maxlength="300" data-alm-notes="${esc(r.key)}" aria-label="Observación de ${esc(r.label)}" autocomplete="off"></td></tr>`;
    }).join('');
    return `<div class="gw-table-wrap"><table class="gw-table"><caption class="gw-sr-only">Checklist del evento: necesario, cantidad despachada, devuelto, pendiente y alistado</caption>
      <thead><tr><th scope="col">Elemento</th><th scope="col" class="gw-alm__num">Necesario</th><th scope="col" class="gw-alm__num">Cantidad</th><th scope="col" class="gw-alm__num">Volvió</th><th scope="col" class="gw-alm__num">Falta volver</th><th scope="col">OK</th><th scope="col">Observaciones</th></tr></thead>
      <tbody>${body}</tbody></table></div>`;
  }
  function outsideList(list) {
    if (!list.length) return '<div class="gw-state" role="status"><p class="gw-state__title">No hay equipos con serial fuera de bodega para este evento.</p></div>';
    return `<ul class="gw-list">${list.map((u) => `<li><strong>${esc(u.title)}</strong> <code>${esc(u.code)}</code>${u.serial ? ' · Serial ' + esc(u.serial) : ''}</li>`).join('')}</ul>`;
  }
  function movementsList(list) {
    if (!list.length) return '<div class="gw-state" role="status"><p class="gw-state__title">Todavía no hay movimientos en este evento.</p></div>';
    return `<div class="gw-table-wrap"><table class="gw-table"><caption class="gw-sr-only">Últimos movimientos del evento</caption>
      <thead><tr><th scope="col">Fecha</th><th scope="col">Movimiento</th><th scope="col">Elemento</th><th scope="col">Nota</th><th scope="col"><span class="gw-sr-only">Acciones</span></th></tr></thead>
      <tbody>${list.map((m) => `<tr${m.voided ? ' class="gw-alm__void"' : ''}><td>${esc(m.at)}</td><td>${m.kind === 'salida' ? 'Salida' : 'Entrada'}${m.voided ? ' <span class="gw-badge">Anulado</span>' : ''}</td>
        <td>${esc(m.title)}${m.qty > 1 ? ' ×' + m.qty : ''}</td>
        <td>${m.plan_b ? '<span class="gw-badge gw-badge--info">Plan B</span> ' : ''}${m.extra ? `<span class="gw-hint">+${m.extra} sobre lo asignado${m.reason ? ': ' + esc(m.reason) : ''}</span>` : ''}</td>
        <td>${m.can_void ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-alm-void="${m.id}" data-title="${esc(m.title)}">Anular</button>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
  }
  async function loadBoard() {
    const id = eventId();
    if (!id) return;
    try {
      const d = await j('/api/almacen/events/' + id + '/board');
      if (eventId() !== id) return;          // cambiaron de evento mientras cargaba
      $('almBoardCard').hidden = false;
      $('almBoardTitle').textContent = 'Checklist del evento · ' + d.event.name;
      const s = d.summary;
      $('almBoardSummary').textContent = `${s.done} de ${s.rows} filas alistadas · ${s.pending_return} por volver`;
      $('almBoardUnmapped').innerHTML = d.unmapped.length ? `<div class="gw-state" role="status"><p class="gw-state__title"><span class="gw-badge gw-badge--warn">Sin fila</span> Estos elementos están en el evento pero no tienen fila del checklist, así que no saldrán en el Excel: ${d.unmapped.map((u) => esc(u.name)).join(', ')}.</p></div>` : '';
      $('almBoard').innerHTML = boardTable(d.board);
      $('almOutside').innerHTML = outsideList(d.outside);
      $('almOutsideCount').textContent = String(d.outside.length);
      $('almMovements').innerHTML = movementsList(d.movements);
      $('almMovementsCount').textContent = String(d.movements.length);
    } catch (e) { $('almBoard').innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(e.message)}</p></div>`; }
  }
  async function saveRow(key, body, input) {
    const id = eventId();
    if (!id) return;
    try {
      await send('/api/almacen/events/' + id + '/checklist/' + encodeURIComponent(key), 'PUT', body);
    } catch (e) {
      fail(e);
      if (input && input.type === 'checkbox') input.checked = !input.checked;
    }
  }

  /* ---- eventos del DOM (delegación) */
  $('almMvScan').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = e.target.value;
    e.target.value = '';
    onScan(v);
  });
  $('almMvEventSearch').addEventListener('input', renderEvents);
  $('almMvEventList').addEventListener('click', (e) => { const b = e.target.closest('button[data-alm-pick]'); if (b) chooseEvent(b.dataset.almPick); });
  $('almMvQrBtn').addEventListener('click', openCamera);
  root.querySelectorAll('input[name=almMvMode]').forEach((r) => r.addEventListener('change', () => { $('almMvResult').innerHTML = ''; focusScan(); }));

  $('almBoardCard').addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset.almDone) saveRow(t.dataset.almDone, { done: t.checked }, t);
    else if (t.dataset.almNotes) saveRow(t.dataset.almNotes, { notes: t.value }, t);
  });
  $('almBoardCard').addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b || !b.dataset.almVoid) return;
    if (!(await showConfirm(`¿Anular el movimiento de «${esc(b.dataset.title)}»? Quedará registrado como anulado.`, { confirmLabel: 'Anular' }))) return;
    try {
      const d = await send('/api/almacen/movements/' + b.dataset.almVoid + '/void', 'POST');
      showToast(d.message, 'success');
      await loadBoard();
    } catch (err) { fail(err); }
  });

  async function init() {
    if (loaded) return;
    try { await loadEvents(); loaded = true; } catch (e) { fail(e); }
  }
  if (tab) tab.addEventListener('gw:tabshow', () => { init(); });
})();
