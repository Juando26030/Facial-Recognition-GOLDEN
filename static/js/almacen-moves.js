/* Almacén (Inventario → pestaña «Almacén», Pieza 2): salidas y entradas por QR a un evento, justificación de lo que excede lo asignado (razón o Plan B), checklist del evento
   con la casilla «OK S/N» por fila, equipos fuera de bodega y anulación del último movimiento. API: /api/almacen/move, /movements/{id}/void, /events/{id}/board, /events/{id}/checklist/{fila}
   y /api/inventory/events (lista de eventos de siempre). Todo se escapa; sin manejadores en línea (delegación); mensajes con showToast / showConfirm.
   Guardado unificado: registrar una salida o entrada (por lectura del QR) y anular son ACTOS inmediatos con aviso; el «OK» y las observaciones del checklist son EDICIONES: quedan en `drafts`
   (pendientes, también si se cambia de evento o se repinta el tablero) y los guarda la barra única de la pantalla (GWParams, bloque «almacen-checklist»). */
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
  const drafts = {};           // cambios del checklist sin guardar: drafts[eventId][fila] = { done?, notes? }
  const base = {};             // lo último que dijo el servidor: base[eventId][fila] = { done, notes } (para saber si una edición volvió a lo original)
  const P = () => window.GWParams;
  const icon = (name, cls) => `<svg class="gw-icon ${cls || ''}" aria-hidden="true"><use href="${esc(root.dataset.icons || '')}#i-${name}"/></svg>`;

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
    if (id) { $('almBoard').replaceChildren(); loadBoard(); focusScan(); } else { $('almBoardCard').hidden = true; }
  }

  /* ---- movimiento por lectura */
  function result(kind, text, extra) {          // kind: 'ok' | 'warn' | 'err'
    const title = { ok: 'Registrado', warn: 'Falta justificar', err: 'No registrado' }[kind];
    const ico = { ok: 'check-lg', warn: 'alert', err: 'error' }[kind];
    $('almMvResult').innerHTML = `<div class="gw-verdict gw-verdict--${kind}" role="${kind === 'err' ? 'alert' : 'status'}">${icon(ico, 'gw-verdict__icon')}<div class="gw-verdict__body"><p class="gw-verdict__title">${title}</p><p class="gw-verdict__text">${esc(text)}</p>${extra || ''}</div></div>`;
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
      result('ok', d.message);
      if (d.product && d.product.tracking !== 'serial') $('almMvQty').value = '1';
      await loadBoard();
    } catch (e) {
      if (e.status === 409 && e.detail && e.detail.needs_reason) {
        pending = body;
        $('almMvReasonMsg').textContent = e.detail.message;
        $('almMvReason').hidden = false;
        $('almMvReasonText').focus();
        result('warn', 'Escribe la razón o marca Plan B y pulsa «Registrar el movimiento».');
        busyMove = false;
        return;
      }
      result('err', e.message);
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
    if (!body.event_id) { result('err', 'Primero elige el evento.'); return; }
    await doMove(body);
  }

  /* ---- tablero del evento */
  const empty = (text) => `<div class="gw-empty gw-alm__empty" role="status"><p>${esc(text)}</p></div>`;
  const draftOf = (eid, key) => (drafts[eid] && drafts[eid][key]) || null;
  function boardTable(rows, eid) {
    let section = '';
    const body = rows.map((r) => {
      let head = '';
      if (r.section !== section) { section = r.section; head = `<tr class="gw-alm__sec"><th colspan="7" scope="colgroup">${esc(r.section_label)}</th></tr>`; }
      const inv = r.kind === 'inv';
      const dr = draftOf(eid, r.key) || {};
      const done = 'done' in dr ? dr.done : r.done;
      const notes = 'notes' in dr ? dr.notes : r.notes;
      const num = (v) => `<td class="gw-alm__num">${inv ? v : '—'}</td>`;
      const flags = (r.extra ? ` <span class="gw-badge gw-badge--warn" title="Salió más de lo que pidió el evento">+${r.extra} extra</span>` : '') + (r.plan_b ? ' <span class="gw-badge gw-badge--info">Plan B</span>' : '');
      return head + `<tr data-alm-row="${esc(r.key)}"${Object.keys(dr).length ? ' class="gw-alm__dirty"' : ''}><th scope="row">${esc(r.label)}${flags}</th>${num(r.needed)}${num(r.out)}${num(r.returned)}
        <td class="gw-alm__num${inv && r.pending ? ' gw-alm__bad' : ''}">${inv ? r.pending : '—'}</td>
        <td><label class="gw-check"><input type="checkbox" data-alm-done="${esc(r.key)}"${done ? ' checked' : ''} aria-label="Alistado: ${esc(r.label)}"></label></td>
        <td class="gw-alm__note"><input class="gw-input" type="text" value="${esc(notes)}" maxlength="300" data-alm-notes="${esc(r.key)}" aria-label="Observación de ${esc(r.label)}" autocomplete="off"></td></tr>`;
    }).join('');
    return `<div class="gw-table-wrap"><table class="gw-table gw-alm__table"><caption class="gw-sr-only">Checklist del evento: necesario, cantidad despachada, devuelto, pendiente y alistado</caption>
      <thead><tr><th scope="col">Elemento</th><th scope="col" class="gw-alm__num">Necesario</th><th scope="col" class="gw-alm__num">Cantidad</th><th scope="col" class="gw-alm__num">Volvió</th><th scope="col" class="gw-alm__num">Falta volver</th><th scope="col">OK</th><th scope="col">Observaciones</th></tr></thead>
      <tbody>${body}</tbody></table></div>`;
  }
  function outsideList(list) {
    if (!list.length) return empty('No hay equipos con serial fuera de bodega para este evento.');
    return `<ul class="gw-list">${list.map((u) => `<li><strong>${esc(u.title)}</strong> <code>${esc(u.code)}</code>${u.serial ? ' · Serial ' + esc(u.serial) : ''}</li>`).join('')}</ul>`;
  }
  function movementsList(list) {
    if (!list.length) return empty('Todavía no hay movimientos en este evento.');
    return `<div class="gw-table-wrap"><table class="gw-table gw-alm__table"><caption class="gw-sr-only">Últimos movimientos del evento</caption>
      <thead><tr><th scope="col">Fecha</th><th scope="col">Movimiento</th><th scope="col">Elemento</th><th scope="col">Nota</th><th scope="col"><span class="gw-sr-only">Acciones</span></th></tr></thead>
      <tbody>${list.map((m) => `<tr${m.voided ? ' class="gw-alm__void"' : ''}><td>${esc(m.at)}</td><td>${m.kind === 'salida' ? 'Salida' : 'Entrada'}${m.voided ? ' <span class="gw-badge">Anulado</span>' : ''}</td>
        <td>${esc(m.title)}${m.qty > 1 ? ' ×' + m.qty : ''}</td>
        <td>${m.plan_b ? '<span class="gw-badge gw-badge--info">Plan B</span> ' : ''}${m.extra ? `<span class="gw-hint">+${m.extra} sobre lo asignado${m.reason ? ': ' + esc(m.reason) : ''}</span>` : ''}</td>
        <td>${m.can_void ? `<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-alm-void="${m.id}" data-title="${esc(m.title)}">${icon('undo', 'gw-icon--sm')} Anular</button>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function skeleton(el, kind) { if (window.GW && window.GW.skeleton) window.GW.skeleton(el, { kind, rows: 4, cols: 6, label: 'Cargando el checklist…' }); else el.textContent = 'Cargando…'; }
  async function loadBoard() {
    const id = eventId();
    if (!id) return;
    if (!$('almBoard').firstElementChild) skeleton($('almBoard'), 'table');
    try {
      const d = await j('/api/almacen/events/' + id + '/board');
      if (eventId() !== id) return;          // cambiaron de evento mientras cargaba
      $('almBoardCard').hidden = false;
      $('almBoardTitle').textContent = 'Checklist del evento · ' + d.event.name;
      const s = d.summary;
      $('almBoardSummary').hidden = false;
      $('almBoardSummary').textContent = `${s.done} de ${s.rows} filas alistadas · ${s.pending_return} por volver`;
      $('almBoardUnmapped').innerHTML = d.unmapped.length ? `<div class="gw-alert gw-alert--warn" role="status">${icon('alert')}<div><p class="gw-alert__title">Elementos sin fila del checklist</p><p class="gw-alert__body">Están en el evento pero no tienen fila, así que no saldrán en el Excel: ${d.unmapped.map((u) => esc(u.name)).join(', ')}.</p></div></div>` : '';
      base[id] = {};
      d.board.forEach((r) => { base[id][r.key] = { done: !!r.done, notes: r.notes || '' }; });
      $('almBoard').innerHTML = boardTable(d.board, id);
      $('almOutside').innerHTML = outsideList(d.outside);
      $('almMovements').innerHTML = movementsList(d.movements);
    } catch (e) { $('almBoard').innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudo cargar el checklist</p><p class="gw-state__text">${esc(e.message)}</p><button type="button" class="gw-btn gw-btn--secondary" data-alm-retry>Reintentar</button></div>`; }
  }

  /* ---- ediciones del checklist: quedan pendientes (drafts) hasta «Guardar cambios» */
  const anyDraft = () => Object.keys(drafts).some((eid) => Object.keys(drafts[eid]).length);
  function setDraft(eid, key, patch) {
    if (!drafts[eid]) drafts[eid] = {};
    const dr = drafts[eid][key] || (drafts[eid][key] = {});
    Object.assign(dr, patch);
    const b = (base[eid] || {})[key];
    if (b) Object.keys(dr).forEach((f) => { if (dr[f] === b[f]) delete dr[f]; });          // volvió a lo original: ya no es un cambio
    if (!Object.keys(dr).length) delete drafts[eid][key];
    if (!Object.keys(drafts[eid]).length) delete drafts[eid];
    const tr = $('almBoard').querySelector(`[data-alm-row="${CSS.escape(key)}"]`);
    if (tr) tr.classList.toggle('gw-alm__dirty', !!draftOf(eid, key));
    if (P()) { if (anyDraft()) P().markDirty('almacen-checklist'); else P().markClean('almacen-checklist'); }
  }
  async function saveChecklist() {          // lo llama la barra única; usa el endpoint de siempre, una fila por llamada
    const fails = [];
    for (const eid of Object.keys(drafts)) {
      for (const key of Object.keys(drafts[eid] || {})) {
        const snap = JSON.stringify(drafts[eid][key]);
        try {
          await send('/api/almacen/events/' + eid + '/checklist/' + encodeURIComponent(key), 'PUT', drafts[eid][key]);
          if (drafts[eid] && drafts[eid][key] && JSON.stringify(drafts[eid][key]) === snap) delete drafts[eid][key];          // si la editaron mientras guardaba, sigue pendiente
        } catch (e) { fails.push(e && e.message ? e.message : 'error'); }
      }
      if (drafts[eid] && !Object.keys(drafts[eid]).length) delete drafts[eid];
    }
    try { await loadBoard(); } catch (e) { /* el tablero se repinta solo la próxima vez */ }
    if (fails.length) throw new Error(`${fails.length} ${fails.length === 1 ? 'fila' : 'filas'} del checklist no se guardaron (${fails[0]})`);
  }
  if (P()) P().register({ key: 'almacen-checklist', label: 'Checklist de Almacén', order: 10, save: saveChecklist });

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

  const onBoardEdit = (e) => {          // OK y observaciones: solo quedan pendientes; guarda la barra única
    const t = e.target;
    const id = eventId();
    if (!id || !t.dataset) return;
    if (t.dataset.almDone) setDraft(id, t.dataset.almDone, { done: t.checked });
    else if (t.dataset.almNotes) setDraft(id, t.dataset.almNotes, { notes: t.value });
  };
  $('almBoardCard').addEventListener('change', onBoardEdit);
  $('almBoardCard').addEventListener('input', onBoardEdit);
  $('almBoardCard').addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (b && b.dataset.almRetry !== undefined) { loadBoard(); return; }
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
