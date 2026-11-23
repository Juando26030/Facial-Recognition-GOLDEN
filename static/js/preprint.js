/* Preimpresiones (18-nov-2026): elegir a quién se le imprime la escarapela antes de que llegue. A mano (buscador) o por filtro (mismas condiciones que la ruleta).
   Toda la selección sale en UNA sola ejecución de impresión (una ventana, una hoja por escarapela, como «Imprimir pendientes»); la ventana es la de siempre
   (templates/badge_print.html, parámetros inamovibles). Al terminar se pregunta si salieron bien y solo entonces se dejan marcadas como preimpresas. */
(function () {
  'use strict';
  const ROOT = document.querySelector('main[data-event-id]');     // datos del evento en atributos (sin <script> en línea: CSP)
  const EID = ROOT.dataset.eventId;
  const ICONS = ROOT.dataset.gwIcons;
  const API = `/api/events/${EID}/preprint`;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ico = (n, c) => `<svg class="gw-icon ${c || ''}" aria-hidden="true"><use href="${ICONS}#i-${n}"/></svg>`;
  const RENDER_CAP = 500;                                   // filas dibujadas (el resto se alcanza buscando o filtrando); «elegir todas» sí toma todas las que cumplen
  const PRINT_WINDOW = 'goldenweb_print';

  const state = { mode: 'hand', reg: 'todos', conds: [], selected: new Set(), people: [], total: 0, preprinted: 0, pending: 0, canPreprint: true, maxBatch: 300, eventStatus: '', busy: false };
  let fields = [];
  let loadTimer = null, loadSeq = 0;

  async function j(url, opt) {
    const r = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' }, opt || {}));
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'No se pudo completar la acción');
    return d;
  }
  const toast = (m, t) => (window.showToast ? window.showToast(m, t) : null);
  const fmt = (iso) => { try { return new Date(iso).toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' }); } catch (e) { return ''; } };
  const defaultValue = (f) => (f.type === 'choice' && f.choices && f.choices.length ? f.choices[0][0] : '');
  const activeConds = () => state.conds.filter((c) => c.value !== '' && c.value != null);

  /* ---------- Carga ---------- */
  function scheduleLoad(delay) { clearTimeout(loadTimer); loadTimer = setTimeout(load, delay == null ? 250 : delay); }
  async function load() {
    const seq = ++loadSeq;
    const q = $('ppSearch').value.trim();
    const conds = state.mode === 'filter' ? activeConds() : [];
    const qs = new URLSearchParams();
    if (q) qs.set('q', q);
    if (state.reg !== 'todos') qs.set('reg', state.reg);
    if (conds.length) qs.set('filter', JSON.stringify({ conditions: conds }));
    try {
      const d = await j(`${API}/people?${qs}`);
      if (seq !== loadSeq) return;
      state.people = d.people; state.total = d.total; state.preprinted = d.preprinted; state.pending = d.pending;
      state.canPreprint = d.can_preprint; state.maxBatch = d.max_batch; state.eventStatus = d.event_status;
    } catch (e) {
      if (seq !== loadSeq) return;
      state.people = []; state.total = state.preprinted = state.pending = 0;
      toast(e.message, 'error');
    }
    $('ppList').setAttribute('aria-busy', 'false');
    paint();
  }

  /* ---------- Pintado ---------- */
  function paint() {
    $('ppClosed').hidden = state.canPreprint;
    $('ppCreado').hidden = !(state.canPreprint && state.eventStatus === 'creado');
    $('ppModeHand').setAttribute('aria-pressed', String(state.mode === 'hand'));
    $('ppModeFilter').setAttribute('aria-pressed', String(state.mode === 'filter'));
    $('ppFilterBox').hidden = state.mode !== 'filter';
    const shown = state.people.length;
    $('ppSummary').textContent = `${state.total} persona(s) en la lista · ${state.preprinted} ya preimpresa(s) · ${state.pending} sin preimprimir` + (state.total > shown ? ` · se muestran las primeras ${shown}` : '');
    if (!shown) {
      $('ppList').innerHTML = `<div class="gw-empty"><p>${state.mode === 'filter' && !activeConds().length ? 'Agrega una condición para armar el grupo.' : 'No hay personas con ese criterio.'}</p></div>`;
    } else {
      const rows = state.people.slice(0, RENDER_CAP).map((p) => {
        const sel = state.selected.has(p.id);
        const pre = p.preprinted_at ? `<span class="gw-badge gw-badge--ok" title="Preimpresa el ${esc(fmt(p.preprinted_at))}">Preimpresa</span>` : '';
        const reg = p.status === 'registrado' ? '<span class="gw-badge gw-badge--info">Registrada</span>' : '<span class="gw-badge">No registrada</span>';
        const times = p.times_printed > 0 && !p.preprinted_at ? `<span class="gw-badge gw-badge--warn" title="Ya se imprimió su escarapela">Impresa ${p.times_printed}×</span>` : '';
        return `<tr><td><label class="gw-check"><input type="checkbox" data-id="${esc(p.id)}" ${sel ? 'checked' : ''} aria-label="Elegir a ${esc(p.name)}"><span></span></label></td>
          <td>${esc(p.name)}<br><small>${esc(p.id)}</small></td><td>${esc(p.entity || '')}</td><td>${esc((p.categories || []).join(', '))}</td><td>${reg} ${pre} ${times}</td></tr>`;
      }).join('');
      $('ppList').innerHTML = `<div class="gw-table-wrap"><table class="gw-table"><thead><tr><th scope="col"><span class="gw-sr-only">Elegir</span></th><th scope="col">Persona</th><th scope="col">Entidad</th><th scope="col">Categoría</th><th scope="col">Estado</th></tr></thead><tbody>${rows}</tbody></table></div>`
        + (shown > RENDER_CAP ? `<p class="gw-hint">Se dibujan las primeras ${RENDER_CAP}; usa el buscador o un filtro para acotar. «Elegir todas las que se ven» toma las ${shown} de la lista.</p>` : '');
    }
    paintPrint();
  }
  function paintPrint() {
    const n = state.selected.size;
    const over = n > state.maxBatch;
    $('ppPrint').disabled = state.busy || !state.canPreprint || n === 0 || over;
    $('ppPrintLabel').textContent = n ? `Preimprimir ${n} escarapela${n === 1 ? '' : 's'}` : 'Preimprimir';
    $('ppPrintHint').textContent = !state.canPreprint ? 'El evento está finalizado.'
      : over ? `Elegiste ${n}: el máximo por impresión es ${state.maxBatch}. Quita algunas o imprime en dos veces.`
        : n ? `${n} persona${n === 1 ? '' : 's'} elegida${n === 1 ? '' : 's'}. Saldrán en una sola impresión, una hoja por escarapela.` : 'Elige al menos una persona.';
  }

  /* ---------- Filtro (mismas condiciones que la ruleta) ---------- */
  function renderConds() {
    $('ppConds').innerHTML = state.conds.map((c, i) => {
      const f = fields.find((x) => x.key === c.field) || fields[0];
      const opts = fields.map((x) => `<option value="${esc(x.key)}" ${x.key === c.field ? 'selected' : ''}>${esc(x.label)}</option>`).join('');
      let v;
      if (f.type === 'choice') v = f.choices && f.choices.length ? `<select class="gw-select" id="ppv${i}" data-v="${i}" aria-label="Valor de la condición ${i + 1}">${f.choices.map(([val, l]) => `<option value="${esc(val)}" ${c.value === val ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>` : `<select class="gw-select" id="ppv${i}" disabled aria-label="Valor de la condición ${i + 1}"><option>Nadie tiene un valor todavía</option></select>`;
      else if (f.type === 'datetime') v = `<input type="datetime-local" class="gw-input" id="ppv${i}" data-v="${i}" value="${esc(c.value || '')}">`;
      else v = `<select class="gw-select" data-op="${i}" aria-label="Condición ${i + 1}: comparación"><option value="equals" ${c.op !== 'contains' ? 'selected' : ''}>es igual a</option><option value="contains" ${c.op === 'contains' ? 'selected' : ''}>contiene</option></select><input type="text" class="gw-input" id="ppv${i}" data-v="${i}" value="${esc(c.value || '')}">`;
      return `<div class="gw-ruleta-cond"><div class="gw-field"><label class="gw-label" for="ppf${i}">Campo</label><select class="gw-select" id="ppf${i}" data-f="${i}">${opts}</select></div><div class="gw-field"><label class="gw-label" for="ppv${i}">Valor</label><div class="gw-ruleta-cond__value">${v}</div></div><button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-del="${i}">Quitar</button></div>`;
    }).join('');
  }
  $('ppConds').addEventListener('change', (e) => {
    const el = e.target;
    if (el.dataset.f !== undefined) { const c = state.conds[+el.dataset.f]; c.field = el.value; c.op = 'equals'; c.value = defaultValue(fields.find((x) => x.key === c.field)); renderConds(); scheduleLoad(0); }
    else if (el.dataset.op !== undefined) { state.conds[+el.dataset.op].op = el.value; scheduleLoad(0); }
    else if (el.dataset.v !== undefined) { state.conds[+el.dataset.v].value = el.value; scheduleLoad(0); }
  });
  $('ppConds').addEventListener('input', (e) => { const el = e.target; if (el.dataset.v !== undefined && el.tagName === 'INPUT') { state.conds[+el.dataset.v].value = el.value; scheduleLoad(300); } });
  $('ppConds').addEventListener('click', (e) => {
    const b = e.target.closest('[data-del]'); if (!b) return;
    state.conds.splice(+b.dataset.del, 1); renderConds(); scheduleLoad(0);
  });
  $('ppAddCond').addEventListener('click', () => {
    if (!fields.length) return;
    const f = fields[0];
    state.conds.push({ field: f.key, op: 'equals', value: defaultValue(f) });
    renderConds(); scheduleLoad(0);
  });
  function setMode(m) {
    state.mode = m;
    if (m === 'filter' && !state.conds.length && fields.length) state.conds.push({ field: fields[0].key, op: 'equals', value: defaultValue(fields[0]) });
    renderConds(); scheduleLoad(0); paint();
  }
  $('ppModeHand').addEventListener('click', () => setMode('hand'));
  $('ppModeFilter').addEventListener('click', () => setMode('filter'));
  $('ppSearch').addEventListener('input', () => scheduleLoad(250));
  $('ppReg').addEventListener('change', (e) => { state.reg = e.target.value; state.selected.clear(); scheduleLoad(0); });

  /* ---------- Selección ---------- */
  $('ppList').addEventListener('change', (e) => {
    const cb = e.target.closest('input[data-id]'); if (!cb) return;
    if (cb.checked) state.selected.add(cb.dataset.id); else state.selected.delete(cb.dataset.id);
    paintPrint();
  });
  $('ppSelectAll').addEventListener('click', () => { state.people.forEach((p) => state.selected.add(p.id)); paint(); });
  $('ppSelectPending').addEventListener('click', () => { state.people.filter((p) => !p.preprinted_at).forEach((p) => state.selected.add(p.id)); paint(); });
  $('ppClear').addEventListener('click', () => { state.selected.clear(); paint(); });

  /* ---------- Impresión: UNA ventana, UNA ejecución, todas las hojas ---------- */
  function printUrl(ids) {
    const first = encodeURIComponent(ids[0]);
    const users = ids.length > 1 ? `users=${ids.map(encodeURIComponent).join(',')}&` : '';
    return `/kiosk/${EID}/escarapela/imprimir/${first}?${users}preprint=1`;
  }
  function waitPrint(win) {                                  // la ventana avisa al terminar el cuadro de impresión (se imprima o se cancele)
    return new Promise((resolve) => {
      let done = false;
      const end = (r) => { if (done) return; done = true; window.removeEventListener('message', onMsg); clearInterval(poll); resolve(r); };
      const onMsg = (ev) => { if (ev.origin === location.origin && ev.data && ev.data.gwPrint === 'done') end({ batch: ev.data.batch }); };
      window.addEventListener('message', onMsg);
      const poll = setInterval(() => { if (!win || win.closed) end({ batch: null, closed: true }); }, 1500);
    });
  }
  $('ppPrint').addEventListener('click', async () => {
    const ids = Array.from(state.selected);
    if (!ids.length || state.busy) return;
    const again = state.people.filter((p) => state.selected.has(p.id) && p.preprinted_at).length;
    if (again && !(await window.showConfirm(`${again} de las ${ids.length} personas ya tienen la escarapela preimpresa. ¿Imprimirlas otra vez?`, { variant: 'warning', confirmLabel: 'Sí, imprimir' }))) return;
    let win = null;
    try { win = window.open(printUrl(ids), PRINT_WINDOW, 'width=480,height=720'); } catch (e) { win = null; }
    if (!win) { toast('El navegador bloqueó la ventana de impresión. Permite las ventanas emergentes de este sitio e intenta de nuevo.', 'error'); return; }
    state.busy = true; paintPrint();
    $('ppPrintHint').textContent = 'Preparando las escarapelas e imprimiendo… no cierres esta pantalla.';
    const res = await waitPrint(win);
    state.busy = false;
    const batch = res.batch || { rendered: ids, failed: [] };
    const rendered = (batch.rendered || []).filter((id) => state.selected.has(id));
    const failed = batch.failed || [];
    if (!rendered.length) { toast(failed.length ? 'No se pudo armar ninguna escarapela.' : 'No se imprimió nada.', 'error'); paint(); return; }
    const msg = `¿Salieron bien las ${rendered.length} escarapelas?` + (failed.length ? ` (${failed.length} no se pudieron armar y no se marcarán)` : '') + ' Si sí, se dejan marcadas como preimpresas.';
    if (!(await window.showConfirm(msg, { variant: 'warning', confirmLabel: 'Sí, salieron' }))) { toast('No se marcó nada. Puedes volver a imprimirlas.', 'success'); paint(); return; }
    try {
      await j(`${API}/mark`, { method: 'POST', body: JSON.stringify({ user_ids: rendered }) });
      toast(`${rendered.length} escarapela${rendered.length === 1 ? '' : 's'} marcada${rendered.length === 1 ? '' : 's'} como preimpresa${rendered.length === 1 ? '' : 's'}.`, 'success');
      rendered.forEach((id) => state.selected.delete(id));
      await load();
    } catch (e) { toast(e.message, 'error'); paint(); }
  });

  /* ---------- Arranque ---------- */
  (async function init() {
    try { fields = await j(`${API}/fields`); } catch (e) { fields = []; toast(e.message, 'error'); }
    await load();
  })();
})();
