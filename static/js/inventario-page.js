/* Pantalla /inventario (Fase 10). Dos secciones:
   1) Catálogo: categorías, productos y existencias (lo crea el Super Admin en Configuración › Inventario), con lo que está en uso hoy. Admin y almacén cambian categoría y existencias.
   2) «Dónde está cada equipo»: calendario (día / semana / mes) con el material que tiene asignado cada evento y la disponibilidad por equipo.
   La lista de eventos ya no es la pantalla: un evento se abre desde el calendario (botón «Abrir inventario del evento»), con el bloque de GWInvPlan.
   Delegación de eventos, todo texto escapado, mensajes con showToast / GW.busy. Funciones puras expuestas en GWInvPage (se prueban con Node). */
(function (root) {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const STATUS = { creado: 'Creado', en_proceso: 'En proceso', finalizado: 'Finalizado' };
  const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const DOW = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'];
  const DOW_LONG = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];

  /* ------------------------------------------------------------------ puras (fechas como «AAAA-MM-DD», sin zonas horarias) */
  const pad = (n) => String(n).padStart(2, '0');
  const parse = (iso) => { const p = String(iso).split('-').map(Number); return new Date(p[0], p[1] - 1, p[2], 12, 0, 0); };
  const toIso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const addDays = (iso, n) => { const d = parse(iso); d.setDate(d.getDate() + n); return toIso(d); };
  const mondayOf = (iso) => addDays(iso, -((parse(iso).getDay() + 6) % 7));
  const dowIndex = (iso) => (parse(iso).getDay() + 6) % 7;
  const monthStart = (iso) => iso.slice(0, 8) + '01';
  const addMonths = (iso, n) => { const d = parse(monthStart(iso)); d.setMonth(d.getMonth() + n); return toIso(d); };
  const eventOnDay = (ev, day) => ev.start <= day && day <= ev.end;
  /* Rango que se pide al servidor para una vista: el mes pide sus 6 semanas completas; la semana y el día, la semana. */
  function rangeFor(view, anchor) {
    if (view === 'month') { const a = mondayOf(monthStart(anchor)); return { start: a, end: addDays(a, 41) }; }
    const a = mondayOf(anchor); return { start: a, end: addDays(a, 6) };
  }
  function gridDays(view, anchor) { const r = rangeFor(view, anchor); const n = view === 'month' ? 42 : 7; return Array.from({ length: n }, (_, i) => addDays(r.start, i)); }
  /* Unidades usadas de un producto ese día (de `daily`, que cuenta todos los eventos) y lo que queda; null = sin control de existencias. */
  const usedOn = (daily, day, pid) => ((daily && daily[day]) || {})[String(pid)] || 0;
  const availOn = (stock, used) => (stock == null ? null : stock - used);
  function shortOn(daily, day, products) { return (products || []).filter((p) => p.stock != null && usedOn(daily, day, p.id) > p.stock); }
  function eventsOn(events, day, pid) {
    return (events || []).filter((e) => eventOnDay(e, day) && (!pid || e.lines.some((l) => l.product_id === pid)));
  }
  function titleFor(view, anchor) {
    const d = parse(anchor);
    if (view === 'month') return `${MONTHS[d.getMonth()]} de ${d.getFullYear()}`;
    if (view === 'week') { const a = parse(mondayOf(anchor)), b = parse(addDays(mondayOf(anchor), 6)); return `${a.getDate()} ${MONTHS[a.getMonth()].slice(0, 3)} – ${b.getDate()} ${MONTHS[b.getMonth()].slice(0, 3)} ${b.getFullYear()}`; }
    return `${DOW_LONG[dowIndex(anchor)]} ${d.getDate()} de ${MONTHS[d.getMonth()]} de ${d.getFullYear()}`;
  }
  /* Catálogo: agrupa por categoría (las sin categoría al final) aplicando búsqueda y filtro. */
  function groupCatalog(cat, q, categoryId) {
    const needle = String(q || '').trim().toLowerCase();
    const prods = (cat.products || []).filter((p) => (!categoryId || String(p.category_id || '') === String(categoryId)) &&
      (!needle || (p.name || '').toLowerCase().includes(needle) || (p.sku || '').toLowerCase().includes(needle)));
    const groups = (cat.categories || []).map((c) => ({ id: c.id, name: c.name, products: prods.filter((p) => p.category_id === c.id) })).filter((g) => g.products.length);
    const loose = prods.filter((p) => p.category_id == null || !(cat.categories || []).some((c) => c.id === p.category_id));
    if (loose.length) groups.push({ id: null, name: 'Sin categorizar', products: loose });
    return groups;
  }
  root.GWInvPage = { parse, toIso, addDays, mondayOf, monthStart, addMonths, eventOnDay, rangeFor, gridDays, usedOn, availOn, shortOn, eventsOn, titleFor, groupCatalog, dowIndex };

  const doc = root.document;
  if (!doc || !doc.getElementById('invCatalog')) return;          // en Node solo se exponen las funciones puras

  /* ------------------------------------------------------------------ pantalla */
  const $ = (id) => doc.getElementById(id);
  const icons = (doc.currentScript && doc.currentScript.dataset.icons) || '/static/img/icons.svg';
  const busy = (btn, fn) => (root.GW && root.GW.busy ? root.GW.busy(btn, fn) : fn());
  const jget = async (url, signal) => { const r = await fetch(url, { cache: 'no-store', signal }); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo cargar'); return d; };
  const send = async (url, method, body) => { const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo guardar'); return d; };
  const stateBox = (msg, err) => `<div class="gw-state${err ? ' gw-state--error' : ''}" role="${err ? 'alert' : 'status'}"><p class="gw-state__title">${esc(msg)}</p></div>`;

  /* ---- pestañas */
  function showTab(name) {
    ['cat', 'cal'].forEach((t) => {
      const on = t === name;
      $(t === 'cat' ? 'invTabCat' : 'invTabCal').setAttribute('aria-selected', String(on));
      $(t === 'cat' ? 'invTabCat' : 'invTabCal').tabIndex = on ? 0 : -1;
      $(t === 'cat' ? 'invPanelCat' : 'invPanelCal').hidden = !on;
    });
    if (name === 'cal' && !cal.loaded) loadCalendar();
  }
  doc.querySelector('.gw-invpg__tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) showTab(b.dataset.tab); });

  /* ---- catálogo */
  let catalog = null;
  const unitText = (p, n) => `${n} ${p.unit || ''}`.trim();
  function productCard(p, canManage) {
    const short = p.available != null && p.available < 0;
    const edit = canManage ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-edit="${p.id}" aria-label="Cambiar categoría o existencias de ${esc(p.name)}">Cambiar</button>` : '';
    const catOptions = (catalog.categories || []).map((c) => `<option value="${c.id}"${c.id === p.category_id ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
    const editor = canManage ? `<div class="gw-invpg__edit" data-editor="${p.id}" hidden>
        <div class="gw-field"><label class="gw-label" for="invStock${p.id}">Existencias de Golden</label><input class="gw-input gw-input--short" type="number" min="0" id="invStock${p.id}" value="${p.stock == null ? '' : p.stock}" placeholder="Sin control"></div>
        <div class="gw-field"><label class="gw-label" for="invCat${p.id}">Categoría</label><select class="gw-select" id="invCat${p.id}"><option value="">Sin categorizar</option>${catOptions}</select></div>
        <button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-save="${p.id}">Guardar</button>
        <button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-cancel="${p.id}">Cancelar</button>
      </div>` : '';
    return `<article class="gw-invpg__prod" data-product="${p.id}">
      <div class="gw-invpg__name">${esc(p.name)}${p.sku ? ` <span class="gw-hint">${esc(p.sku)}</span>` : ''}</div>
      <div class="gw-invpg__num"><span class="gw-invpg__lbl">Existencias</span><span class="gw-invpg__val">${p.stock == null ? 'Sin control' : esc(unitText(p, p.stock))}</span></div>
      <div class="gw-invpg__num"><span class="gw-invpg__lbl">En uso hoy</span><span class="gw-invpg__val">${esc(unitText(p, p.in_use || 0))}</span></div>
      <div class="gw-invpg__num"><span class="gw-invpg__lbl">Disponible hoy</span><span class="gw-invpg__val${short ? ' gw-invpg__val--short' : ''}">${p.available == null ? '—' : esc(unitText(p, p.available))}${short ? ' · falta material' : ''}</span></div>
      <div>${edit}</div>${editor}</article>`;
  }
  function renderCatalog() {
    const box = $('invCatalog');
    box.setAttribute('aria-busy', 'false');
    const groups = groupCatalog(catalog, $('invSearch').value, $('invCatFilter').value);
    if (!(catalog.products || []).length) { box.innerHTML = stateBox('Todavía no hay productos en el catálogo. El Super Admin los crea en Configuración › Inventario.'); return; }
    if (!groups.length) { box.innerHTML = stateBox('Ningún producto coincide con la búsqueda.'); return; }
    box.innerHTML = groups.map((g) => `<section class="gw-stack" aria-label="${esc(g.name)}"><h2 class="gw-invpg__cat">${esc(g.name)} <span class="gw-hint">${g.products.length}</span></h2>${g.products.map((p) => productCard(p, catalog.can_manage)).join('')}</section>`).join('');
  }
  async function loadCatalog() {
    try {
      catalog = await jget('/api/inventory/overview');
      const sel = $('invCatFilter'), cur = sel.value;
      sel.innerHTML = '<option value="">Todas</option>' + catalog.categories.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
      sel.value = cur;
      $('invAdminLink').hidden = !catalog.can_edit_catalog;
      const hint = $('invCatHint');
      hint.hidden = false;
      hint.textContent = catalog.can_manage ? 'Puedes cambiar la categoría y las existencias de cada producto. Crear, renombrar o archivar productos y categorías lo hace el Super Admin en Configuración.' : 'Solo consulta: las existencias y categorías las ajustan Admin y Almacén.';
      renderCatalog();
    } catch (err) { $('invCatalog').setAttribute('aria-busy', 'false'); $('invCatalog').innerHTML = stateBox(err.message, true); }
  }
  let searchTimer = null;
  $('invSearch').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => catalog && renderCatalog(), 200); });
  $('invCatFilter').addEventListener('change', () => catalog && renderCatalog());
  $('invCatalog').addEventListener('click', (e) => {
    const edit = e.target.closest('[data-edit]'), cancel = e.target.closest('[data-cancel]'), save = e.target.closest('[data-save]');
    if (edit || cancel) { const id = (edit || cancel).dataset.edit || (edit || cancel).dataset.cancel; const ed = $('invCatalog').querySelector(`[data-editor="${id}"]`); if (ed) ed.hidden = !edit; return; }
    if (save) {
      const id = Number(save.dataset.save);
      const stock = $(`invStock${id}`).value.trim(), cat = $(`invCat${id}`).value;
      busy(save, async () => {
        try { await send(`/api/inventory/products/${id}/manage`, 'PATCH', { stock, category_id: cat }); showToast('Producto actualizado', 'success'); await loadCatalog(); }
        catch (err) { showToast(err.message, 'error'); }
      });
    }
  });

  /* ---- calendario */
  const today = toIso(new Date());
  const cal = { view: 'month', anchor: today, selected: today, data: null, loaded: false, ctrl: null, key: '' };
  const pidFilter = () => Number($('invCalProduct').value) || 0;

  async function loadCalendar() {
    const r = rangeFor(cal.view, cal.anchor);
    const key = r.start + '|' + r.end;
    $('invCalTitle').textContent = titleFor(cal.view, cal.anchor);
    if (cal.data && cal.key === key) { renderCalendar(); return; }
    if (cal.ctrl) cal.ctrl.abort();
    cal.ctrl = new AbortController();
    $('invCalBody').setAttribute('aria-busy', 'true');
    if (root.GW && root.GW.skeleton) root.GW.skeleton($('invCalBody'), { kind: 'list', rows: 4, label: 'Cargando el calendario…' });
    try {
      cal.data = await jget(`/api/inventory/calendar?start=${r.start}&end=${r.end}`, cal.ctrl.signal);
      cal.key = key; cal.loaded = true;
      fillProducts();
      renderCalendar();
    } catch (err) { if (err.name === 'AbortError') return; $('invCalBody').setAttribute('aria-busy', 'false'); $('invCalBody').innerHTML = stateBox(err.message, true); }
  }
  function fillProducts() {
    const sel = $('invCalProduct'), cur = sel.value;
    sel.innerHTML = '<option value="">Todos los equipos</option>' + cal.data.products.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
    sel.value = cur;
  }
  const lineQty = (ev, pid) => { const l = ev.lines.find((x) => x.product_id === pid); return l ? l.assigned : 0; };
  function chip(ev, pid) {
    const pend = ev.status === 'finalizado' && ev.lines.some((l) => l.pending_return > 0);
    const txt = pid ? `${ev.name} · ${lineQty(ev, pid)}` : `${ev.name} · ${ev.lines.length} equipo${ev.lines.length === 1 ? '' : 's'}`;
    return `<span class="gw-invcal__chip${pend ? ' gw-invcal__chip--warn' : ''}" title="${esc(ev.name)}">${esc(txt)}</span>`;
  }
  function availText(day, pid, onlyIfUsed) {
    const prod = cal.data.products.find((p) => p.id === pid);
    if (!prod || prod.stock == null) return '';
    const used = usedOn(cal.data.daily, day, pid);
    if (onlyIfUsed && !used) return '';          // en el mes, los días sin uso no repiten «Disp.»
    const a = availOn(prod.stock, used);
    return `<span class="gw-invcal__avail${a < 0 ? ' gw-invcal__avail--short' : ''}">Disp. ${a}</span>`;
  }
  function renderMonth() {
    const pid = pidFilter(), month = cal.anchor.slice(0, 7);
    const head = DOW.map((d) => `<div class="gw-invcal__dow">${d}</div>`).join('');
    const cells = gridDays('month', cal.anchor).map((day) => {
      const evs = eventsOn(cal.data.events, day, pid);
      const short = pid ? [] : shortOn(cal.data.daily, day, cal.data.products);
      const chips = evs.slice(0, 3).map((e) => chip(e, pid)).join('') + (evs.length > 3 ? `<span class="gw-invcal__more">+${evs.length - 3} más</span>` : '');
      const warn = short.length ? `<span class="gw-invcal__chip gw-invcal__chip--warn">Falta material (${short.length})</span>` : '';
      return `<button type="button" class="gw-invcal__cell${day.slice(0, 7) === month ? '' : ' gw-invcal__cell--out'}${day === today ? ' gw-invcal__cell--today' : ''}" data-day="${day}" aria-pressed="${day === cal.selected}" aria-label="${esc(titleFor('day', day))}: ${evs.length} evento${evs.length === 1 ? '' : 's'}">
        <span class="gw-invcal__d">${Number(day.slice(8))}</span>${chips}${warn}${pid ? availText(day, pid, true) : ''}</button>`;
    }).join('');
    return `<div class="gw-invcal__month" role="group" aria-label="Calendario del mes">${head}${cells}</div>`;
  }
  function renderWeek() {
    const pid = pidFilter();
    return `<div class="gw-invcal__week">${gridDays('week', cal.anchor).map((day) => {
      const evs = eventsOn(cal.data.events, day, pid);
      const body = evs.length ? evs.map((e) => `<div class="gw-invcal__evt"><strong>${esc(e.name)}</strong><ul>${e.lines.filter((l) => !pid || l.product_id === pid).slice(0, 6).map((l) => `<li>${l.assigned} × ${esc(l.name)}</li>`).join('')}${e.lines.length > 6 && !pid ? `<li>+${e.lines.length - 6} más</li>` : ''}</ul></div>`).join('') : '<span class="gw-hint">Sin material asignado</span>';
      return `<div class="gw-invcal__col"${day === today ? ' aria-current="date"' : ''}><button type="button" class="gw-btn gw-btn--${day === cal.selected ? 'primary' : 'secondary'} gw-btn--sm" data-day="${day}" aria-pressed="${day === cal.selected}">${DOW[dowIndex(day)]} ${Number(day.slice(8))}</button>${body}${pid ? availText(day, pid) : ''}</div>`;
    }).join('')}</div>`;
  }
  function renderDetail() {
    const day = cal.selected, pid = pidFilter(), box = $('invCalDetail');
    const evs = eventsOn(cal.data.events, day, pid);
    const inRange = cal.data.start <= day && day <= cal.data.end;
    if (!inRange) { box.innerHTML = ''; return; }
    const evHtml = evs.length ? evs.map((e) => {
      const lines = e.lines.filter((l) => !pid || l.product_id === pid);
      return `<article class="gw-card gw-stack"><div class="gw-invcal__evhead"><h3 class="gw-invcal__evtitle">${esc(e.name)} <span class="gw-hint">${esc(e.code)} · ${esc(STATUS[e.status] || e.status)} · ${esc(e.event_start)}${e.event_end !== e.event_start ? ' al ' + esc(e.event_end) : ''}${e.start < e.event_start ? ' · montaje desde ' + esc(e.start) : ''}</span></h3>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-open-event="${e.id}" data-name="${esc(e.name)}">Abrir inventario del evento</button></div>
        <div class="gw-table-wrap"><table class="gw-table"><caption class="gw-sr-only">Material de ${esc(e.name)}</caption><thead><tr><th scope="col">Equipo</th><th scope="col">Asignado</th><th scope="col">Salió</th><th scope="col">Volvió</th><th scope="col">Falta por volver</th></tr></thead><tbody>${lines.map((l) => `<tr><td>${esc(l.name)}</td><td>${l.assigned} ${esc(l.unit)}</td><td>${l.out}</td><td>${l.returned}</td><td>${l.pending_return > 0 && e.status === 'finalizado' ? `<span class="gw-badge gw-badge--warn">${l.pending_return}</span>` : l.pending_return}</td></tr>`).join('')}</tbody></table></div></article>`;
    }).join('') : stateBox('Ningún evento tiene material asignado este día.');
    const prods = cal.data.products.filter((p) => (!pid || p.id === pid) && (usedOn(cal.data.daily, day, p.id) > 0 || p.stock != null));
    const avail = prods.length ? `<div class="gw-table-wrap"><table class="gw-table"><caption class="gw-sr-only">Disponibilidad por equipo</caption><thead><tr><th scope="col">Equipo</th><th scope="col">Existencias</th><th scope="col">Asignado</th><th scope="col">Disponible</th></tr></thead><tbody>${prods.map((p) => {
      const u = usedOn(cal.data.daily, day, p.id), a = availOn(p.stock, u);
      return `<tr><td>${esc(p.name)}</td><td>${p.stock == null ? 'Sin control' : p.stock}</td><td>${u}</td><td>${a == null ? '—' : (a < 0 ? `<span class="gw-badge gw-badge--err">${a} · falta</span>` : a)}</td></tr>`;
    }).join('')}</tbody></table></div>` : '';
    box.innerHTML = `<h2 class="gw-card__title">${esc(titleFor('day', day))}</h2>${evHtml}${avail ? `<h3 class="gw-invcal__evtitle">Disponibilidad por equipo</h3>${avail}` : ''}`;
  }
  function renderCalendar() {
    $('invCalBody').setAttribute('aria-busy', 'false');
    $('invCalTitle').textContent = titleFor(cal.view, cal.anchor);
    $('invCalBody').innerHTML = cal.view === 'month' ? renderMonth() : (cal.view === 'week' ? renderWeek() : '');
    doc.querySelectorAll('[data-view]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.view === cal.view)));
    renderDetail();
  }
  function step(dir) {
    if (cal.view === 'month') cal.anchor = addMonths(cal.anchor, dir);
    else cal.anchor = addDays(cal.anchor, dir * (cal.view === 'week' ? 7 : 1));
    if (cal.view === 'day') cal.selected = cal.anchor;
    else if (cal.view === 'month') cal.selected = cal.anchor.slice(0, 8) + '01';
    else cal.selected = mondayOf(cal.anchor);
    loadCalendar();
  }
  doc.querySelector('.gw-invcal__nav').addEventListener('click', (e) => {
    const v = e.target.closest('[data-view]'), n = e.target.closest('[data-nav]');
    if (v) { cal.view = v.dataset.view; if (cal.view === 'day') cal.anchor = cal.selected; loadCalendar(); return; }
    if (n) { if (n.dataset.nav === 'today') { cal.anchor = cal.selected = today; loadCalendar(); } else step(n.dataset.nav === 'next' ? 1 : -1); }
  });
  $('invCalProduct').addEventListener('change', () => cal.data && renderCalendar());
  $('invPanelCal').addEventListener('click', (e) => {
    const d = e.target.closest('[data-day]');
    if (d) { cal.selected = d.dataset.day; if (cal.view === 'day') { cal.anchor = cal.selected; loadCalendar(); } else renderCalendar(); return; }
    const o = e.target.closest('[data-open-event]');
    if (o) openEvent(Number(o.dataset.openEvent), o.dataset.name);
  });

  /* ---- bloque de inventario de un evento (el mismo de siempre), abierto desde el calendario */
  let plan = null;
  async function openEvent(id, name) {
    if (plan && plan.dirty() && !(await showConfirm('Hay cambios sin guardar en el inventario abierto. ¿Descartarlos y abrir otro evento?', { variant: 'warning', confirmLabel: 'Descartar' }))) return;
    $('invPanelTitle').textContent = 'Inventario de ' + name;
    $('invPanel').hidden = false;
    if (root.GW && root.GW.skeleton) root.GW.skeleton($('invPlanBox'), { kind: 'list', rows: 4, label: 'Cargando el inventario del evento…' });
    plan = await root.GWInvPlan.mount($('invPlanBox'), { eventId: id, icons, onChange: () => {} });
    $('invPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  $('invPanelClose').addEventListener('click', async () => {
    if (plan && plan.dirty() && !(await showConfirm('Hay cambios sin guardar. ¿Cerrar y descartarlos?', { variant: 'warning', confirmLabel: 'Descartar' }))) return;
    plan = null; $('invPanel').hidden = true; $('invPlanBox').innerHTML = '';
    if (cal.data) { cal.key = ''; loadCalendar(); }          // el inventario pudo cambiar: se vuelve a leer
    loadCatalog();
  });

  loadCatalog();
})(typeof window !== 'undefined' ? window : globalThis);
if (typeof module !== 'undefined' && typeof globalThis.GWInvPage !== 'undefined') module.exports = globalThis.GWInvPage;
