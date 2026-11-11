/* Bloque «Inventario» del evento (Fase 5): lista los productos ACTIVOS del catálogo (los define el Super Admin en Configuración → Inventario) con sus cantidades y muestra el estado del cuadre.
   Dos modos: con evento (eventId: lee y guarda en /api/events/<id>/inventory-plan) y borrador (sin eventId: «Nuevo evento»; las cantidades se envían con save(eventId) cuando el evento ya existe).
   Lo que cada rol puede editar lo decide el servidor (can_edit_plan / can_edit_movement); aquí solo se deshabilitan los campos. Delegación de eventos; todo texto escapado; mensajes con showToast.
   API: GWInvPlan.mount(contenedor, { eventId, onChange, icons }) -> Promise<controlador { dirty(), save(eventId?), reload(), visible }>. Pura: GWInvPlan.rowsToPayload (se prueba con Node). */
(function (root) {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const QTY_KEYS = ['assigned', 'out', 'returned', 'consumed'];
  const num = (v) => { const n = parseInt(String(v == null ? '' : v).trim() || '0', 10); return Number.isFinite(n) && n >= 0 ? n : 0; };

  /* Pura: de las filas actuales (y las cargadas) arma las líneas a enviar: solo las que cambiaron (o, en borrador, las que tienen algo). */
  function rowsToPayload(current, loaded, opts) {
    const draft = !!(opts && opts.draft);
    const base = {}; (loaded || []).forEach((l) => { base[l.product_id] = l; });
    const out = [];
    (current || []).forEach((c) => {
      const b = base[c.product_id] || { assigned: 0, out: 0, returned: 0, consumed: 0, notes: '', attrs: {} };
      const attrsNow = JSON.stringify(sortObj(c.attrs || {})), attrsBefore = JSON.stringify(sortObj(b.attrs || {}));
      const changed = QTY_KEYS.some((k) => num(c[k]) !== num(b[k])) || (c.notes || '') !== (b.notes || '') || attrsNow !== attrsBefore;
      if (!changed) return;
      if (draft && !c.assigned && !c.notes && attrsNow === '{}') return;
      const line = { product_id: c.product_id, assigned: num(c.assigned), notes: c.notes || '', attrs: c.attrs || {} };
      if (!draft) { ['out', 'returned', 'consumed'].forEach((k) => { if (num(c[k]) !== num(b[k])) line[k] = num(c[k]); }); }
      out.push(line);
    });
    return out;
  }
  function sortObj(o) { const r = {}; Object.keys(o).sort().forEach((k) => { r[k] = o[k]; }); return r; }

  async function mount(box, opts) {
    opts = opts || {};
    if (!box) return null;
    let eventId = opts.eventId || null;
    let data = null, dirtyFlag = false;
    const ICONS = opts.icons || '/static/img/icons.svg';
    const icon = (n) => `<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${ICONS}#i-${n}"/></svg>`;
    const ctrl = { visible: true, dirty: () => dirtyFlag, reload, save };

    async function fetchData() {
      if (eventId) {
        const r = await fetch(`/api/events/${eventId}/inventory-plan`, { cache: 'no-store' });
        if (r.status === 403 || r.status === 404) return null;
        if (!r.ok) throw new Error('No se pudo leer el inventario');
        return r.json();
      }
      const r = await fetch('/api/inventory/catalog', { cache: 'no-store' });
      if (r.status === 403) return null;
      if (!r.ok) throw new Error('No se pudo leer el catálogo');
      const c = await r.json();
      return { lines: c.products.map((p) => ({ product_id: p.id, name: p.name, unit: p.unit, sku: p.sku, category_id: p.category_id, category_name: p.category_name, fields: p.fields, archived: false, assigned: 0, out: 0, returned: 0, consumed: 0, notes: '', attrs: {} })),
        can_edit_plan: true, can_edit_movement: false, balance: null, totals: null, status: 'creado', draft: true };
    }

    function qtyInput(l, key, label, enabled) {
      return `<input class="gw-input gw-inv-plan__qty" type="number" inputmode="numeric" min="0" step="1" value="${num(l[key])}" data-ip-qty="${key}" aria-label="${esc(label)}: ${esc(l.name)}"${enabled ? '' : ' disabled'}>`;
    }
    function rowHtml(l) {
      const plan = data.can_edit_plan, mov = data.can_edit_movement && !data.draft;
      const pending = Math.max(num(l.out) - num(l.returned) - num(l.consumed), 0);
      const fields = (l.fields || []).map((f) => `<label class="gw-field gw-inv-plan__field"><span class="gw-label">${esc(f.label)}</span><input class="gw-input" type="${f.kind === 'number' ? 'number' : 'text'}" maxlength="80" value="${esc((l.attrs || {})[f.key])}" data-ip-attr="${esc(f.key)}"${plan ? '' : ' disabled'}></label>`).join('');
      const detail = `<details class="gw-inv-plan__more"><summary>Detalles</summary><div class="gw-inv-plan__morebody">${fields}<label class="gw-field gw-inv-plan__field"><span class="gw-label">Nota</span><input class="gw-input" type="text" maxlength="200" value="${esc(l.notes)}" data-ip-notes${plan ? '' : ' disabled'}></label></div></details>`;
      return `<div class="gw-inv-plan__row" data-ip-row="${l.product_id}">
        <div class="gw-inv-plan__name"><strong>${esc(l.name)}</strong><span class="gw-hint">${esc(l.unit)}${l.sku ? ' · SKU ' + esc(l.sku) : ''}${l.archived ? ' · archivado' : ''}</span></div>
        <div class="gw-inv-plan__cells">
          <label class="gw-inv-plan__cell"><span class="gw-inv-plan__lbl">Asignado</span>${qtyInput(l, 'assigned', 'Asignado', plan)}</label>
          ${data.draft ? '' : `<label class="gw-inv-plan__cell"><span class="gw-inv-plan__lbl">Salió</span>${qtyInput(l, 'out', 'Salió', mov)}</label>
          <label class="gw-inv-plan__cell"><span class="gw-inv-plan__lbl">Volvió</span>${qtyInput(l, 'returned', 'Volvió', mov)}</label>
          <label class="gw-inv-plan__cell"><span class="gw-inv-plan__lbl">Consumido</span>${qtyInput(l, 'consumed', 'Consumido', mov)}</label>
          <span class="gw-inv-plan__cell"><span class="gw-inv-plan__lbl">Pendiente</span><span class="gw-inv-plan__pending" data-ip-pending>${pending}</span></span>`}
        </div>${detail}</div>`;
    }
    function balanceHtml() {
      const b = data.balance;
      if (!b) return '<p class="gw-hint">El cuadre se revisa cuando el evento ya existe: el almacén registra lo que sale, vuelve y se consume.</p>';
      const items = b.errors.map((i) => `<li>${esc(i.message)}</li>`).join('') + b.warnings.map((i) => `<li>${esc(i.message)}</li>`).join('');
      const head = b.ok ? (b.balanced ? '<span class="gw-badge gw-badge--ok">' + icon('check') + 'Cuadra</span>' : '<span class="gw-badge gw-badge--warn">' + icon('info') + 'Con avisos</span>') : '<span class="gw-badge gw-badge--err">' + icon('alert') + 'No cuadra</span>';
      const t = data.totals;
      const tot = t ? `<span class="gw-hint">Asignado ${t.assigned} · Salió ${t.out} · Volvió ${t.returned} · Consumido ${t.consumed} · Pendiente ${t.pending}</span>` : '';
      const warn = (data.warnings || []).map((m) => `<li>${esc(m)}</li>`).join('');          // avisos de anticipación y de falta de material: nunca bloquean
      const warnBox = warn ? `<div class="gw-inv-plan__warnings" role="alert"><span class="gw-badge gw-badge--warn">${icon('alert')}Aviso (no bloquea)</span><ul class="gw-inv-plan__issues">${warn}</ul></div>` : '';
      return `<div class="gw-inv-plan__balance" role="status">${head} ${tot}${items ? `<ul class="gw-inv-plan__issues">${items}</ul>` : ''}</div>${warnBox}`;
    }
    function paint() {
      if (!data) { box.innerHTML = ''; ctrl.visible = false; ctrl.empty = true; return; }
      ctrl.visible = true;
      const lines = data.lines || [];
      ctrl.empty = !lines.length;
      if (!lines.length) { box.innerHTML = '<div class="gw-state" role="status"><p class="gw-state__title">El catálogo de inventario está vacío</p><p class="gw-state__text">El Super Admin define los productos en Configuración → Inventario.</p></div>'; return; }
      const groups = [], index = {};
      lines.forEach((l) => { const k = l.category_name || ''; if (!(k in index)) { index[k] = groups.length; groups.push({ name: k, items: [] }); } groups[index[k]].items.push(l); });
      const readonly = !data.can_edit_plan;
      box.innerHTML = (readonly ? '<p class="gw-hint">Solo lectura: tu rol puede ver el inventario pero no cambiarlo.</p>' : '') + balanceHtml() +
        groups.map((g) => `<fieldset class="gw-inv-plan__group"><legend>${g.name ? esc(g.name) : 'Sin categoría'}</legend>${g.items.map(rowHtml).join('')}</fieldset>`).join('') +
        (opts.saveButton === false || readonly ? '' : `<div class="gw-actions"><button type="button" class="gw-btn gw-btn--secondary" data-ip-save>Guardar inventario</button></div>`);
    }
    function read() {
      return Array.prototype.map.call(box.querySelectorAll('[data-ip-row]'), (row) => {
        const l = { product_id: parseInt(row.dataset.ipRow, 10), notes: (row.querySelector('[data-ip-notes]') || {}).value || '', attrs: {} };
        QTY_KEYS.forEach((k) => { const el = row.querySelector(`[data-ip-qty="${k}"]`); l[k] = el ? num(el.value) : 0; });
        row.querySelectorAll('[data-ip-attr]').forEach((el) => { if (el.value.trim()) l.attrs[el.dataset.ipAttr] = el.value.trim(); });
        return l;
      });
    }
    async function reload() {
      try { data = await fetchData(); } catch (e) { box.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(e.message)}</p></div>`; return; }
      dirtyFlag = false; paint();
    }
    async function save(idOverride) {
      if (idOverride) eventId = idOverride;
      if (!data || !data.can_edit_plan) return { ok: true, skipped: true };
      const payload = rowsToPayload(read(), data.lines, { draft: !!data.draft });
      if (!payload.length) return { ok: true, skipped: true };
      let res;
      try { res = await fetch(`/api/events/${eventId}/inventory-plan`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lines: payload }) }); }
      catch (e) { return { ok: false, error: 'Sin conexión: no se guardó el inventario.' }; }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: typeof body.detail === 'string' ? body.detail : 'No se pudo guardar el inventario' };
      data = body; dirtyFlag = false; if (!idOverride) paint();
      return { ok: true, plan: body };
    }

    box.addEventListener('input', (e) => {
      if (!e.target.closest('[data-ip-row]')) return;
      dirtyFlag = true;
      const row = e.target.closest('[data-ip-row]'), p = row.querySelector('[data-ip-pending]');
      if (p) { const v = (k) => num((row.querySelector(`[data-ip-qty="${k}"]`) || {}).value); p.textContent = Math.max(v('out') - v('returned') - v('consumed'), 0); }
      if (opts.onChange) opts.onChange();
    });
    box.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-ip-save]');
      if (!b) return;
      b.disabled = true;
      const r = await save();
      b.disabled = false;
      if (r.ok) showToast(r.skipped ? 'No hay cambios en el inventario' : 'Inventario guardado', 'success'); else showToast(r.error, 'error');
    });
    await reload();
    return ctrl;
  }

  const api = { mount, rowsToPayload };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.GWInvPlan = api;
})(typeof window !== 'undefined' ? window : globalThis);
