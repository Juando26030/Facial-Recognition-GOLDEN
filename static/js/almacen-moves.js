/* Almacén (Inventario → pestaña «Almacén», Pieza 2): salidas y entradas por QR a un evento, justificación de lo que excede lo asignado (razón o Plan B), checklist del evento
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
  let pending = null;          // salida que espera razón o Plan B: el mismo cuerpo, para reenviarlo
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
  const focusScan = () => { const s = $('almMvScan'); if (s && !s.disabled) s.focus(); };

  /* ---- eventos */
  function eventOptions() {
    const term = $('almMvEventFilter').value.trim().toLowerCase();
    const keep = $('almMvEvent').value;
    const rows = events.filter((e) => e.status !== 'archivado' && (!term || (e.name + ' ' + (e.code || '')).toLowerCase().includes(term)));
    $('almMvEvent').innerHTML = '<option value="">Elige un evento…</option>' + rows.map((e) => `<option value="${e.id}"${String(e.id) === keep ? ' selected' : ''}>${esc(e.name)}${e.code ? ' · ' + esc(e.code) : ''} (${esc(STATUS[e.status] || e.status)})</option>`).join('');
  }
  async function loadEvents() {
    const d = await j('/api/inventory/events');
    events = d.events || [];
    eventOptions();
  }
  function onEventChange() {
    const id = eventId();
    $('almMvScan').disabled = !id;
    $('almMvHint').textContent = id ? 'El lector escribe el código y pulsa Enter; cada lectura registra un movimiento.' : 'Primero elige el evento. El lector escribe el código y pulsa Enter; cada lectura registra un movimiento.';
    $('almMvResult').innerHTML = '';
    hideReason();
    if (id) { loadBoard(); focusScan(); } else { $('almBoardCard').hidden = true; }
  }

  /* ---- movimiento por lectura */
  function result(ok, text, extra) {
    $('almMvResult').innerHTML = `<div class="gw-state${ok ? '' : ' gw-state--error'}" role="${ok ? 'status' : 'alert'}"><p class="gw-state__title"><span class="gw-badge ${ok ? 'gw-badge--ok' : 'gw-badge--err'}">${ok ? 'Registrado' : 'No registrado'}</span> ${esc(text)}</p>${extra || ''}</div>`;
  }
  function hideReason() {
    pending = null;
    $('almMvReason').hidden = true;
    $('almMvReasonText').value = '';
    $('almMvPlanB').checked = false;
  }
  async function doMove(body) {
    if (busyMove) return;
    busyMove = true;
    $('almMvScan').disabled = true;
    try {
      const d = await send('/api/almacen/move', 'POST', body);
      hideReason();
      result(true, d.message);
      if (d.product && d.product.tracking !== 'serial') $('almMvQty').value = '1';
      await loadBoard();
    } catch (e) {
      if (e.status === 409 && e.detail && e.detail.needs_reason) {
        pending = body;
        $('almMvReasonMsg').textContent = e.detail.message;
        $('almMvReason').hidden = false;
        $('almMvReasonText').focus();
        result(false, 'Falta justificar: escribe la razón o marca Plan B.');
        busyMove = false;
        return;
      }
      result(false, e.message);
    }
    busyMove = false;
    $('almMvScan').disabled = !eventId();
    focusScan();
  }
  async function onScan(raw) {
    const code = String(raw || '').trim();
    if (!code || pending) return;
    const m = mode();
    const body = { mode: m, code, event_id: eventId(), qty: Number($('almMvQty').value) || 1 };
    if (!body.event_id) { result(false, 'Primero elige el evento.'); return; }
    await doMove(body);
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
      $('almMovements').innerHTML = movementsList(d.movements);
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
  $('almMvEvent').addEventListener('change', onEventChange);
  $('almMvEventFilter').addEventListener('input', eventOptions);
  root.querySelectorAll('input[name=almMvMode]').forEach((r) => r.addEventListener('change', () => { $('almMvResult').innerHTML = ''; hideReason(); focusScan(); }));

  $('almMvReason').addEventListener('submit', (e) => {
    e.preventDefault();
    if (!pending) return;
    const reason = $('almMvReasonText').value.trim();
    const planB = $('almMvPlanB').checked;
    if (!reason && !planB) { showToast('Escribe la razón o marca Plan B', 'error'); return; }
    doMove(Object.assign({}, pending, { reason, plan_b: planB }));
  });
  $('almMvReasonCancel').addEventListener('click', () => { hideReason(); $('almMvResult').innerHTML = ''; focusScan(); });

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
