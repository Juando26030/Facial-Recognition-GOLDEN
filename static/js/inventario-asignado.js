/* Control de inventario con «La base lo define» (0161, app/inv_assign.py). La persona elegida en el paso 1 (static/js/inventario.js) se consulta aquí:
   se ve lo que le corresponde según la base (lo suyo y lo de sus dependientes), con «Entregar» en cada línea y «Entregar todo». No se elige otro producto.
   Solo a personas registradas; lo entregado no se repite; se puede entregar por partes. Sin manejadores en línea: delegación de eventos. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const G = () => window.GWInv || {};
  const esc = (v) => (G().esc ? G().esc(v) : String(v == null ? '' : v));
  let current = null, busyNow = false;
  /* Sin red (docs/28): lo que le toca a cada persona sale del paquete guardado en el dispositivo (GET …/offline-pack, pedido una vez al abrir) y lo entregado aquí se suma encima; la entrega
     se guarda y se envía al volver la conexión con las asignaciones exactas que se entregaron. */
  const OFF = window.GWOff || null;
  const packUrl = () => `/api/events/${window.EVENT_ID}/offline-pack`, doneKey = () => `inv-local-done:${window.EVENT_ID}`;
  if (OFF) OFF.json(packUrl()).then(() => OFF.put(doneKey(), {})).catch(() => {});          // con red: paquete fresco (ya trae lo entregado) y se olvida lo local
  async function localView(u) { const pack = await OFF.get(packUrl()); if (!pack || !pack.assigned) return null; return OFF.assignedView(pack, u, (await OFF.get(doneKey())) || {}); }
  async function showOffline(u, opts) {
    const view = await localView(u);
    if (!view) { const msg = 'Sin conexión y sin la copia de lo asignado en este dispositivo. Abre esta pantalla una vez con conexión.'; $('assignedBox').innerHTML = stateHtml(msg, 'error'); if ($('pcardAssign')) $('pcardAssign').innerHTML = `<p class="gw-alert gw-alert--err" role="alert">${esc(msg)}</p>`; return; }
    render(view);
    if (opts && opts.auto && view.registered && view.pending > 0) deliver({ all: true });
  }
  async function deliverOffline(body) {
    const view = await localView(current);
    const name = `${current.first_name || ''} ${current.last_name || ''}`.trim();
    if (!view) { if (G().verdict) G().verdict('err', 'Sin conexión', 'No hay copia de lo asignado en este dispositivo.'); return; }
    if (!view.registered) { if (G().verdict) G().verdict('warn', 'No se pudo entregar', `${esc(name)} aún no está registrada en el evento.`); return; }
    const plan = OFF.assignedDeliver(view, body);
    if (!plan.keys.length) { if (G().verdict) G().verdict('warn', 'No se pudo entregar', 'No hay nada pendiente que se pueda entregar (ya se entregó o no hay existencias).'); return; }
    await OFF.send(`/api/events/${window.EVENT_ID}/inventory/deliver-assigned`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cedula: current.id, keys: plan.keys }) }, `Entrega a ${name}`);
    const done = (await OFF.get(doneKey())) || {};
    view.lines.forEach((l) => { if (plan.keys.includes(l.key)) done[l.key] = (done[l.key] || 0) + l.pending; });
    await OFF.put(doneKey(), done);
    if (G().verdict) G().verdict('ok', 'Entregado', `<strong>${esc(name)}</strong>: ${plan.delivered.map(d => `${d.qty} × ${esc(d.name)}${d.who ? ` (para ${esc(d.who)})` : ''}`).join(', ')}. Sin conexión: queda guardado en este dispositivo y se envía solo al volver la red.`);
    render(await localView(current));
  }

  function stateHtml(text, kind) {
    return `<div class="gw-state gw-empty--hero${kind === 'error' ? ' gw-state--error' : ''}" role="${kind === 'error' ? 'alert' : 'status'}"><p class="gw-state__title">${esc(text)}</p></div>`;
  }

  /* 26-nov-2026: las celdas van en la tarjeta de la persona (#pcardAssign, debajo de «Registrado»), una por regalo, cada una con su «Entregar» grande; abajo queda solo un aviso. */
  function render(data) {
    const inCard = $('pcardAssign');
    if (inCard) { renderCells(data, inCard); $('assignedBox').innerHTML = stateHtml('Lo que le corresponde está arriba, en la tarjeta de la persona: entrega cada regalo con su botón.'); return; }
    const box = $('assignedBox');
    const lines = data.lines || [];
    const p = data.person || {};
    const name = `${p.first_name || ''} ${p.last_name || ''}`.trim() || p.id;
    let html = '';
    if (!data.registered) {
      html += `<div class="gw-alert gw-alert--warn" role="alert"><div><b>${esc(name)} aún no está registrada en el evento.</b> Regístrala primero (pantalla de Registro) y vuelve a escanearla: solo se entrega a personas registradas.</div></div>`;
    }
    if (!lines.length) {
      box.innerHTML = html + stateHtml('La base de datos no le asigna nada a esta persona. Si dice que trae a alguien más, búscalo abajo por su nombre o documento.');
      return;
    }
    const pending = lines.filter(l => l.pending > 0 && !l.problem);
    html += lines.map(l => {
      const cls = l.problem ? ' gw-assign__row--problem' : (l.done ? ' gw-assign__row--done' : '');
      const who = l.dependent ? `Para: ${esc(l.who || 'dependiente')}` : 'Para el titular';
      const status = l.problem ? `<span class="gw-badge gw-badge--warn">${esc(l.problem)}</span>`
        : (l.done ? '<span class="gw-badge gw-badge--ok">Entregado</span>'
          : `<span class="gw-badge gw-badge--info">Pendiente: ${l.pending}${l.delivered ? ` (ya recibió ${l.delivered})` : ''}</span>${l.available < l.pending ? ` <span class="gw-badge gw-badge--err">Quedan ${Math.max(l.available, 0)} en stock</span>` : ''}`);
      const btn = (!l.problem && l.pending > 0 && data.registered)
        ? `<button type="button" class="gw-btn gw-btn--primary" data-assign-key="${esc(l.key)}">Entregar${l.pending > 1 ? ` (${l.pending})` : ''}</button>` : '';
      return `<div class="gw-assign__row${cls}"><div><strong>${esc(l.item_name || l.product)}</strong> · ${l.qty} unidad${l.qty === 1 ? '' : 'es'}<span class="gw-assign__who">${who}</span><div>${status}</div></div>${btn}</div>`;
    }).join('');
    if (pending.length > 1 && data.registered) html += `<div class="gw-ai__foot"><button type="button" class="gw-btn gw-btn--primary gw-btn--xl" data-assign-all="1">Entregar todo (${pending.length})</button></div>`;
    box.innerHTML = html;
  }

  function renderCells(data, host) {
    const lines = data.lines || [];
    if (!lines.length) { host.innerHTML = '<p class="gw-alert gw-alert--info">La base no le asigna nada a esta persona. Si trae a alguien más, búscalo abajo por su nombre o documento.</p>'; return; }
    const pending = lines.filter(l => l.pending > 0 && !l.problem);
    let html = '<p class="gw-pcard__deliver-title">Le corresponde:</p>';
    html += lines.map(l => {
      const who = l.dependent ? `Para: ${esc(l.who || 'dependiente')}` : 'Para el titular';
      const cls = l.problem ? ' gw-pcard__cell--problem' : (l.done ? ' gw-pcard__cell--done' : '');
      const status = l.problem ? `<span class="gw-badge gw-badge--warn">${esc(l.problem)}</span>`
        : (l.done ? '<span class="gw-badge gw-badge--ok">Entregado</span>'
          : `<span class="gw-badge gw-badge--info">Pendiente: ${l.pending}${l.delivered ? ` (ya recibió ${l.delivered})` : ''}</span>${l.available < l.pending ? ` <span class="gw-badge gw-badge--err">Quedan ${Math.max(l.available, 0)} en stock</span>` : ''}`);
      const btn = (!l.problem && l.pending > 0 && data.registered)
        ? `<button type="button" class="gw-btn gw-btn--primary gw-btn--xl gw-pcard__go" data-assign-key="${esc(l.key)}">Entregar${l.pending > 1 ? ` (${l.pending})` : ''}</button>` : '';
      return `<div class="gw-pcard__cell gw-pcard__cell--stack${cls}"><span class="gw-pcard__cell-name">${esc(l.item_name || l.product)} · ${l.qty} unidad${l.qty === 1 ? '' : 'es'}</span><span class="gw-pcard__cell-who">${who}</span><span>${status}</span>${btn}</div>`;
    }).join('');
    if (pending.length > 1 && data.registered) html += `<button type="button" class="gw-btn gw-btn--secondary gw-btn--xl gw-pcard__go" data-assign-all="1">Entregar todo (${pending.length})</button>`;
    host.innerHTML = html;
  }

  async function show(u, opts) {
    current = u;
    const box = $('assignedBox');
    box.innerHTML = stateHtml('Buscando lo que le corresponde…');
    const fail = (msg) => { box.innerHTML = stateHtml(msg, 'error'); if ($('pcardAssign')) $('pcardAssign').innerHTML = `<p class="gw-alert gw-alert--err" role="alert">${esc(msg)}</p>`; };
    if (OFF && OFF.off()) return showOffline(u, opts);
    let res, data;
    try {
      res = await fetch(`/api/events/${window.EVENT_ID}/inventory/assigned?cedula=${encodeURIComponent(u.id)}`);
      data = await res.json().catch(() => ({}));
    } catch (e) { if (OFF) return showOffline(u, opts); fail('Sin conexión con el servidor. Inténtalo de nuevo.'); return; }
    if (!res.ok) { fail(data.detail || 'No se pudo consultar a esta persona'); return; }
    render(data);
    if (opts && opts.auto && data.registered && (data.pending || 0) > 0) deliver({ all: true });          // «escanear = entregar» (Parámetros): entrega todo lo pendiente
  }

  async function deliver(body) {
    if (!current || busyNow) return;
    busyNow = true;
    if (OFF && OFF.off()) { try { await deliverOffline(body); } finally { busyNow = false; } return; }
    let res, data;
    try {
      res = await fetch(`/api/events/${window.EVENT_ID}/inventory/deliver-assigned`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ cedula: current.id }, body)) });
      data = await res.json().catch(() => ({}));
    } catch (e) { res = null; data = { detail: 'No se pudo entregar: sin conexión con el servidor. Inténtalo de nuevo.' }; }
    busyNow = false;
    const name = `${current.first_name || ''} ${current.last_name || ''}`.trim();
    if (!res || !res.ok) { if (G().verdict) G().verdict(res ? 'warn' : 'err', res ? 'No se pudo entregar' : 'Sin conexión', esc(data.detail || 'No se pudo entregar')); return; }
    if (G().verdict) G().verdict('ok', 'Entregado', `<strong>${esc(name)}</strong>: ${(data.delivered || []).map(d => `${d.qty} × ${esc(d.name)}${d.who ? ` (para ${esc(d.who)})` : ''}`).join(', ')}.` + (data.warning ? `<br>${esc(data.warning)}` : ''));
    render({ person: data.person, registered: true, lines: data.lines });
    if (G().reload) await G().reload();
  }

  document.addEventListener('click', (e) => {
    const one = e.target.closest && e.target.closest('[data-assign-key]');
    if (one) { const btn = one; (G().busy || ((b, w) => w()))(btn, () => deliver({ keys: [btn.dataset.assignKey] })); return; }
    const all = e.target.closest && e.target.closest('[data-assign-all]');
    if (all) { (G().busy || ((b, w) => w()))(all, () => deliver({ all: true })); return; }
    const pick = e.target.closest && e.target.closest('[data-dep-holder]');
    if (pick) { if (G().pickById && !G().pickById(pick.dataset.depHolder)) showToast('El titular de ese dependiente no está en la base de este evento', 'error'); }
  });

  async function searchDeps() {
    const q = $('depSearchInput').value.trim();
    const out = $('depSearchResults');
    if (q.length < 3) { showToast('Escribe al menos 3 letras o números', 'error'); return; }
    out.innerHTML = stateHtml('Buscando…');
    let data;
    if (OFF && OFF.off()) {                                              // sin red: se busca en el paquete guardado (nombre o documento del dependiente)
      const pack = await OFF.get(packUrl()), low = q.toLowerCase(), found = [];
      Object.keys((pack && pack.dependents) || {}).forEach((h) => pack.dependents[h].forEach((p) => { if (found.length < 15 && (String(p.label || '').toLowerCase().includes(low) || String(p.doc || '').toLowerCase().includes(low))) found.push({ dependent: p.label, doc: p.doc, holder_id: h, holder_name: '' }); }));
      data = { results: found };
    } else
    try { const r = await fetch(`/api/events/${window.EVENT_ID}/dependents/search?q=${encodeURIComponent(q)}`); data = await r.json(); if (!r.ok) throw new Error(data.detail || 'error'); }
    catch (e) { out.innerHTML = stateHtml(e.message && e.message !== 'error' ? e.message : 'No se pudo buscar. Revisa la conexión.', 'error'); return; }
    const rows = data.results || [];
    out.innerHTML = rows.length ? rows.map(r => `<article class="gw-card-row"><div class="gw-card-row__head"><h3 class="gw-card-row__title">${esc(r.dependent || 'Dependiente sin nombre')}${r.doc ? ` · ${esc(r.doc)}` : ''}</h3>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-dep-holder="${esc(r.holder_id)}">Ver lo de su titular</button></div>
        <p class="gw-card-row__meta">Titular: ${esc(r.holder_name || r.holder_id)} (${esc(r.holder_id)})</p></article>`).join('')
      : stateHtml('No hay dependientes con ese nombre o documento. Si se registró con su propio documento, búscalo arriba como a cualquier persona.');
  }
  if ($('depSearchBtn')) $('depSearchBtn').addEventListener('click', searchDeps);
  if ($('depSearchInput')) $('depSearchInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchDeps(); } });

  window.GWInvAssigned = { show };
})();
