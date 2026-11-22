/* Parámetros › Zonas e inventario (0161, docs/25_INVENTARIO_POR_BASE.md):
   - «¿Qué necesito?»: tres preguntas y una recomendación (no guarda nada).
   - «¿Quién decide qué se le entrega a cada persona?» (clave «inv_mode» del guardado global): La persona elige / La base lo define, con los campos de producto y cantidad,
     el resumen asignado vs. stock (con alerta cuando falta), «Actualizar productos desde la base», «Igualar el stock» y las entregas de más.
   - «Bloquear la configuración del digitador» (clave «cfg_lock»): zonas, inventario y la contraseña de desbloqueo.
   Usa el guardado global de la página (GWParams, static/js/params-save.js). Sin manejadores en línea. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const box = $('invModeBox');
  const EVENT_ID = window.EVENT_ID || (box && box.dataset.event);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toast = (m, k) => (window.showToast ? showToast(m, k) : null);

  /* ---------------------------------------------------------------- ¿Qué necesito? */
  (function wizard() {
    const out = $('invWizardOut');
    if (!out) return;
    const val = (name) => { const r = document.querySelector(`input[name="${name}"]:checked`); return r ? r.value : ''; };
    function advise() {
      const a = val('wzRepartir'), b = val('wzBase'), c = val('wzDeps');
      if (!a && !b && !c) { out.hidden = true; return; }
      const tips = [];
      if (a === 'no') tips.push('No necesitas el control de inventario. Si solo quieres saber cuántas personas entran con acompañantes, carga la <b>base de dependientes</b> en «Adjuntar base de datos» (aparece el campo «Dependientes» con su estadística).');
      if (a === 'si' && b === 'no') tips.push('Activa el <b>control de inventario</b> con <b>«La persona elige»</b> y crea los ítems en la tabla. Si cada puesto entrega siempre lo mismo, activa también <b>«Bloquear la configuración de control de inventario»</b>.');
      if (a === 'si' && b === 'si') tips.push('Activa el <b>control de inventario</b> con <b>«La base lo define»</b> y elige el campo que dice el producto. Los productos se crean solos con el stock de la base (puedes editarlo).');
      if (c === 'si') tips.push('Carga la <b>base de dependientes</b> (Adjuntar base de datos › Base de dependientes) DESPUÉS de la base de registro. ' + (b === 'si' ? 'Luego elige aquí la columna del producto de los dependientes.' : 'Con eso cada titular muestra cuántos dependientes trae y la estadística los cuenta.'));
      if (c === 'no' && a !== 'no') tips.push('No necesitas la base de dependientes.');
      out.innerHTML = '<b>Te recomendamos:</b><ul class="gw-list">' + tips.map(t => `<li>${t}</li>`).join('') + '</ul>';
      out.hidden = !tips.length;
    }
    document.addEventListener('change', (e) => { if (e.target.name && /^wz/.test(e.target.name)) advise(); });
  })();

  /* ---------------------------------------------------------------- ¿Quién decide qué se entrega? */
  let state = null;
  const modeVal = () => { const r = document.querySelector('input[name="invMode"]:checked'); return r ? r.value : 'choose'; };
  function fillSelect(sel, options, value, keepFirst) {
    if (!sel) return;
    const first = keepFirst ? sel.options[0].outerHTML : '';
    sel.innerHTML = first + options.map(o => `<option value="${esc(o.key)}">${esc(o.label)}</option>`).join('');
    sel.value = value || '';
  }
  function renderSummary(s) {
    const out = $('invAssignSummary');
    if (!out) return;
    if (!s || modeVal() !== 'assigned') { out.innerHTML = ''; return; }
    if (!s.products.length) { out.innerHTML = '<div class="gw-alert gw-alert--warn"><div>La base todavía no asigna ningún producto con los campos elegidos. Revisa que el campo tenga valores (o carga la base) y pulsa «Guardar cambios».</div></div>'; return; }
    const shortList = s.products.filter(p => p.short > 0 || p.missing_item);
    const alert = shortList.length
      ? `<div class="gw-alert gw-alert--warn" role="alert"><div><b>Ojo con el stock:</b> ${shortList.length} producto(s) tienen menos unidades que las asignadas (${shortList.map(p => `«${esc(p.product)}»: faltan ${p.missing_item ? p.assigned : p.short}`).join(', ')}). No se bloquea nada: cuando se acabe, el puesto avisará «No alcanza». Si es a propósito (hay menos regalos que personas), déjalo así.</div></div>`
      : '<div class="gw-alert gw-alert--ok"><div>El stock alcanza para todo lo asignado.</div></div>';
    out.innerHTML = alert + `<div class="gw-table-wrap"><table class="gw-table"><caption>Lo que pide la base frente al inventario (${s.products.length} productos)</caption>
      <thead><tr><th scope="col">Producto (como viene en la base)</th><th scope="col">Asignado</th><th scope="col">Stock</th><th scope="col">Entregado</th><th scope="col">Estado</th></tr></thead>
      <tbody>${s.products.map(p => `<tr><td>${esc(p.product)}${p.item_name && p.item_name !== p.product ? ` <span class="gw-hint">(en el inventario: ${esc(p.item_name)})</span>` : ''}</td><td>${p.assigned}</td><td>${p.missing_item ? '—' : p.stock}</td><td>${p.delivered}</td>
        <td>${p.missing_item ? '<span class="gw-badge gw-badge--warn">Falta crearlo: pulsa «Actualizar productos»</span>' : (p.short ? `<span class="gw-badge gw-badge--warn">Faltan ${p.short}</span>` : '<span class="gw-badge gw-badge--ok">Alcanza</span>')}</td></tr>`).join('')}</tbody></table></div>` +
      (s.orphans && s.orphans.length ? `<p class="gw-hint">Productos creados desde la base que ya nadie tiene asignado: ${s.orphans.map(o => '«' + esc(o.item_name) + '»').join(', ')}. Se conservan (no se borran solos); archívalos en la tabla de abajo si no los necesitas.</p>` : '');
  }
  function renderOver(list) {
    const out = $('invOverBox');
    if (!out) return;
    out.innerHTML = list && list.length ? `<div class="gw-alert gw-alert--err" role="alert"><div><b>Entregas de más (${list.length}).</b> Pasa cuando dos puestos sin internet entregan lo mismo antes de sincronizar. No se borró nada; revisa con la persona:
      <ul class="gw-list">${list.slice(0, 20).map(o => `<li>${esc(o.cedula)}${o.who ? ' · ' + esc(o.who) : ''}: «${esc(o.product)}» asignado ${o.assigned}, entregado ${o.delivered}</li>`).join('')}</ul></div></div>` : '';
  }
  function paint() {
    if (!state) return;
    const c = state.config || {};
    fillSelect($('invHolderProduct'), state.holder_fields || [], c.holder_product, true);
    fillSelect($('invHolderQty'), state.holder_fields || [], c.holder_qty, true);
    fillSelect($('invDepProduct'), state.dependent_columns || [], c.dep_product, true);
    fillSelect($('invDepQty'), state.dependent_columns || [], c.dep_qty, true);
    const hint = $('invDepHint');
    if (hint) hint.textContent = state.has_dependents ? 'Columnas que trae la base de dependientes del evento.' : 'Este evento todavía no tiene base de dependientes. Si los dependientes también reciben, cárgala en Adjuntar base de datos › Base de dependientes y vuelve aquí.';
    renderSummary(state.summary);
    renderOver(state.over_deliveries);
  }
  async function load() {
    if (!box) return;
    try { const r = await fetch(`/api/events/${EVENT_ID}/inventory-assign`, { cache: 'no-store' }); if (!r.ok) return; state = await r.json(); paint(); } catch (e) { /* sin red: queda lo de la página */ }
  }
  if (box) {
    document.addEventListener('change', (e) => {
      if (e.target.name === 'invMode') { $('invAssignCfg').hidden = modeVal() !== 'assigned'; renderSummary(state && state.summary); }
    });
    if (window.GWParams) GWParams.register({ key: 'inv_mode', label: 'Quién decide qué se entrega', order: 66.5, save: async () => {
      const body = { mode: modeVal(), holder_product: $('invHolderProduct').value || null, holder_qty: $('invHolderQty').value || null, dep_product: $('invDepProduct').value || null, dep_qty: $('invDepQty').value || null };
      const r = await fetch(`/api/events/${EVENT_ID}/inventory-assign`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || 'No se pudo guardar quién decide qué se entrega');
      state = d; paint();
      if (window.GWParamsItemsReload) window.GWParamsItemsReload();
    } });
    const act = async (btn, url, okMsg) => {
      const run = async () => {
        const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { toast(d.detail || 'No se pudo', 'error'); return; }
        toast(okMsg(d), 'success');
        await load();
        if (window.GWParamsItemsReload) window.GWParamsItemsReload();
      };
      return window.GW && GW.busy ? GW.busy(btn, run) : run();
    };
    if ($('invAssignSync')) $('invAssignSync').addEventListener('click', (e) => act(e.currentTarget, `/api/events/${EVENT_ID}/inventory-assign/sync`, (d) => d.created ? `Se crearon ${d.created} producto(s) nuevos con el stock de la base.` : 'No había productos nuevos en la base.'));
    if ($('invAssignMatch')) $('invAssignMatch').addEventListener('click', (e) => act(e.currentTarget, `/api/events/${EVENT_ID}/inventory-assign/match-stock`, (d) => d.changed ? `Se subió el stock de ${d.changed} producto(s) hasta lo asignado.` : 'Todos los productos ya tenían al menos lo asignado.'));
    load();
  }

  /* ---------------------------------------------------------------- bloqueo de la configuración del digitador */
  if ($('cfgLockBox') && window.GWParams) GWParams.register({ key: 'cfg_lock', label: 'Bloquear la configuración del digitador', order: 67.5, reload: true, save: async () => {
    const body = { areas_locked: $('lockAreas').checked, inventory_locked: $('lockInventory').checked };
    const pw = $('lockPassword').value;
    if ($('lockClearPw') && $('lockClearPw').checked) body.clear_password = true; else if (pw) body.password = pw;
    const hasPw = !!document.querySelector('#cfgLockBox .gw-badge--ok');
    if ((body.areas_locked || body.inventory_locked) && !pw && !hasPw) {
      toast('Ojo: sin contraseña de desbloqueo, solo un coordinador puede desbloquear (apagando la casilla).', 'info');
    }
    const r = await fetch(`/api/events/${EVENT_ID}/config-lock`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'No se pudo guardar el bloqueo');
    $('lockPassword').value = '';
  } });
})();
