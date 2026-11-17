/* Almacén (Inventario → pestaña «Almacén», Pieza 1): cómo se controla cada elemento (con serial / por modelo / por cantidad), unidades con serial, etiquetas QR y modo escáner.
   API: /api/almacen/* (app/routers/almacen.py) y, para crear el producto, /api/inventory/products (catálogo de siempre). Todo se escapa; sin manejadores en línea (delegación);
   mensajes con showToast / showConfirm. Las etiquetas se imprimen en una ventana propia (/inventario/etiquetas), sin tocar la impresión compartida de escarapelas. */
(function () {
  'use strict';
  const root = document.getElementById('invPanelAlm');
  if (!root) return;
  const tab = document.getElementById('invTabAlm');
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());
  let meta = null;
  let products = [];
  let currentProduct = null;          // producto cuyas unidades se ven
  let units = [];
  let loaded = false;

  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error'); return d; }
  const send = (url, method, body) => j(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const fail = (e) => showToast(e && e.message ? e.message : 'No se pudo completar la acción', 'error');
  const trackingLabel = (k) => ((meta.tracking.find((t) => t.key === k) || {}).label) || k;

  /* ---- datos fijos y listas */
  function fillSelects() {
    $('almNewTracking').innerHTML = meta.tracking.map((t) => `<option value="${esc(t.key)}">${esc(t.label)}</option>`).join('');
    $('almNewRow').innerHTML = rowOptions('');
    showTrackingHint();
  }
  function rowOptions(selected) {
    const groups = {};
    meta.rows.forEach((r) => { (groups[r.section] = groups[r.section] || []).push(r); });
    return '<option value="">Sin fila (no sale en el checklist)</option>' + Object.keys(groups).map((s) =>
      `<optgroup label="${esc(meta.sections[s] || s)}">${groups[s].map((r) => `<option value="${esc(r.key)}"${r.key === selected ? ' selected' : ''}>${esc(r.label)}</option>`).join('')}</optgroup>`).join('');
  }
  function showTrackingHint() {
    const t = meta.tracking.find((x) => x.key === $('almNewTracking').value);
    $('almNewTrackingHint').textContent = t ? t.hint : '';
  }
  async function loadCategories() {
    const d = await j('/api/inventory/catalog');
    const cats = d.categories || [];
    $('almNewCat').innerHTML = cats.length ? cats.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('') : '<option value="">Primero crea una categoría en «Administrar catálogo»</option>';
  }

  /* ---- elementos */
  function productsTable() {
    if (!products.length) return `<div class="gw-state" role="status"><p class="gw-state__title">No hay elementos todavía. Crea el primero arriba.</p></div>`;
    return `<div class="gw-table-wrap"><table class="gw-table"><caption class="gw-sr-only">Elementos de bodega y cómo se controla cada uno</caption>
      <thead><tr><th scope="col">Elemento</th><th scope="col">¿Cómo se controla?</th><th scope="col">Fila del checklist</th><th scope="col">Consumible</th><th scope="col">Unidades</th><th scope="col"><span class="gw-sr-only">Acciones</span></th></tr></thead>
      <tbody>${products.map((p) => `<tr data-alm-prod="${p.id}">
        <td>${esc(p.name)}<br><span class="gw-hint">${esc(p.category_name || 'Sin categoría')}</span></td>
        <td><select class="gw-select" data-f="tracking" aria-label="Cómo se controla ${esc(p.name)}">${meta.tracking.map((t) => `<option value="${esc(t.key)}"${t.key === p.tracking ? ' selected' : ''}>${esc(t.label)}</option>`).join('')}</select></td>
        <td><select class="gw-select" data-f="checklist_row" aria-label="Fila del checklist de ${esc(p.name)}">${rowOptions(p.checklist_row || '')}</select></td>
        <td><label class="gw-check"><input type="checkbox" data-f="is_consumable"${p.is_consumable ? ' checked' : ''} aria-label="${esc(p.name)} es consumible"></label></td>
        <td>${p.tracking === 'serial' ? `<span class="gw-badge">${p.units}</span>` : '—'}</td>
        <td class="gw-alm__actions"><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-alm-save="${p.id}">Guardar</button>
          ${p.tracking === 'serial' ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-alm-units="${p.id}">Unidades</button>`
    : `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-alm-label="${p.id}">Etiqueta QR</button>`}</td></tr>`).join('')}</tbody></table></div>`;
  }
  async function loadProducts() {
    const box = $('almProducts');
    box.setAttribute('aria-busy', 'true');
    try {
      const d = await j('/api/almacen/products?q=' + encodeURIComponent($('almSearch').value.trim()));
      products = d.products || [];
      box.innerHTML = productsTable();
    } catch (e) { box.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(e.message)}</p></div>`; }
    box.setAttribute('aria-busy', 'false');
  }

  /* ---- unidades con serial */
  function unitsTable() {
    if (!units.length) return `<div class="gw-state" role="status"><p class="gw-state__title">Todavía no hay unidades. Crea las primeras arriba.</p></div>`;
    return `<div class="gw-table-wrap"><table class="gw-table"><caption class="gw-sr-only">Unidades de ${esc(currentProduct.name)}</caption>
      <thead><tr><th scope="col"><span class="gw-sr-only">Marcar</span></th><th scope="col">Número</th><th scope="col">Código QR</th><th scope="col">Serial</th><th scope="col">Estado</th><th scope="col"><span class="gw-sr-only">Acciones</span></th></tr></thead>
      <tbody>${units.map((u) => `<tr data-alm-unit="${u.id}">
        <td><input type="checkbox" class="gw-alm__pick" data-pick="${u.id}" aria-label="Marcar ${esc(u.title)} para imprimir"></td>
        <td>#${u.number}</td><td><code>${esc(u.code)}</code></td>
        <td><input class="gw-input" type="text" value="${esc(u.serial || '')}" maxlength="80" data-serial="${u.id}" aria-label="Serial de ${esc(u.title)}" autocomplete="off"></td>
        <td><span class="gw-badge${u.status === 'novedad' ? ' gw-badge--warn' : u.status === 'en_evento' ? ' gw-badge--info' : ' gw-badge--ok'}">${esc(u.status_label)}</span></td>
        <td class="gw-alm__actions"><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-alm-serial-save="${u.id}">Guardar serial</button>
          <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-alm-print-one="${u.id}">Etiqueta</button>
          <button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-alm-archive="${u.id}" data-title="${esc(u.title)}">Archivar</button></td></tr>`).join('')}</tbody></table></div>`;
  }
  async function openUnits(productId) {
    currentProduct = products.find((p) => p.id === productId);
    if (!currentProduct) return;
    $('almUnitsTitle').textContent = 'Unidades de ' + currentProduct.name;
    $('almUnitsCard').hidden = false;
    $('almUnits').innerHTML = '';
    await reloadUnits();
    $('almUnitsCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  async function reloadUnits() {
    if (!currentProduct) return;
    try { units = (await j('/api/almacen/units?product_id=' + currentProduct.id)).units || []; $('almUnits').innerHTML = unitsTable(); } catch (e) { fail(e); }
  }

  /* ---- etiquetas: ventana propia, con solo los ids; los datos los pide esa página */
  function printLabels(unitIds, productIds) {
    const qs = new URLSearchParams();
    if (unitIds.length) qs.set('u', unitIds.join(','));
    if (productIds.length) qs.set('p', productIds.join(','));
    if (!unitIds.length && !productIds.length) { showToast('Marca al menos una unidad', 'error'); return; }
    window.open('/inventario/etiquetas?' + qs.toString(), '_blank');
  }

  /* ---- modo escáner: el lector USB escribe el código y pulsa Enter */
  async function scan(text) {
    const out = $('almScanResult');
    const code = String(text || '').trim();
    if (!code) return;
    try {
      const d = await j('/api/almacen/scan?code=' + encodeURIComponent(code));
      if (d.kind === 'unit') {
        const u = d.unit;
        out.innerHTML = `<div class="gw-state" role="status"><p class="gw-state__title"><span class="gw-badge gw-badge--ok">Encontrado</span> ${esc(u.title)}</p>
          <p class="gw-hint">Código ${esc(u.code)} · ${u.serial ? 'Serial ' + esc(u.serial) + ' · ' : ''}${esc(u.status_label)}</p></div>`;
      } else {
        const p = d.product;
        out.innerHTML = `<div class="gw-state" role="status"><p class="gw-state__title"><span class="gw-badge gw-badge--ok">Encontrado</span> ${esc(p.name)}</p>
          <p class="gw-hint">Código ${esc(d.code)} · ${esc(trackingLabel(p.tracking))}</p></div>`;
      }
    } catch (e) {
      out.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title"><span class="gw-badge gw-badge--err">No encontrado</span> ${esc(e.message)}</p></div>`;
    }
  }

  /* ---- eventos (delegación) */
  $('almScan').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = e.target.value;
    e.target.value = '';
    scan(v);
  });
  $('almNewTracking').addEventListener('change', showTrackingHint);
  $('almSearch').addEventListener('input', (() => { let t; return () => { clearTimeout(t); t = setTimeout(loadProducts, 250); }; })());

  $('almNewForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('almNewName').value.trim();
    const cat = $('almNewCat').value;
    if (!name) { showToast('Escribe el nombre del elemento', 'error'); return; }
    if (!cat) { showToast('Elige una categoría', 'error'); return; }
    try {
      await busy($('almNewBtn'), async () => {
        const p = await send('/api/inventory/products', 'POST', { name, category_id: Number(cat), unit: 'unidad' });
        await send('/api/almacen/products/' + p.id, 'PATCH', { tracking: $('almNewTracking').value, checklist_row: $('almNewRow').value, is_consumable: $('almNewConsumable').checked });
      });
      $('almNewName').value = '';
      $('almNewConsumable').checked = false;
      showToast(`Elemento «${name}» creado`, 'success');
      loadProducts();
    } catch (err) { fail(err); }
  });

  root.addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    try {
      if (b.dataset.almSave) {
        const row = b.closest('tr');
        const body = { tracking: row.querySelector('[data-f=tracking]').value, checklist_row: row.querySelector('[data-f=checklist_row]').value, is_consumable: row.querySelector('[data-f=is_consumable]').checked };
        await busy(b, () => send('/api/almacen/products/' + b.dataset.almSave, 'PATCH', body));
        showToast('Cambios guardados', 'success');
        await loadProducts();
      } else if (b.dataset.almUnits) {
        await openUnits(Number(b.dataset.almUnits));
      } else if (b.dataset.almLabel) {
        printLabels([], [Number(b.dataset.almLabel)]);
      } else if (b.dataset.almUnitsClose !== undefined) {
        $('almUnitsCard').hidden = true;
        currentProduct = null;
      } else if (b.dataset.almSerialSave) {
        const id = b.dataset.almSerialSave;
        const input = root.querySelector(`[data-serial="${id}"]`);
        await busy(b, () => send('/api/almacen/units/' + id, 'PATCH', { serial: input.value }));
        showToast('Serial guardado', 'success');
        await reloadUnits();
      } else if (b.dataset.almPrintOne) {
        printLabels([Number(b.dataset.almPrintOne)], []);
      } else if (b.dataset.almPrintSelected !== undefined) {
        printLabels(Array.from(root.querySelectorAll('.gw-alm__pick:checked')).map((c) => Number(c.dataset.pick)), []);
      } else if (b.dataset.almPrintAll !== undefined) {
        printLabels(units.map((u) => u.id), []);
      } else if (b.dataset.almArchive) {
        if (!(await showConfirm(`¿Archivar «${esc(b.dataset.title)}»? Deja de ofrecerse, pero conserva su número y su código.`, { confirmLabel: 'Archivar' }))) return;
        await busy(b, () => send('/api/almacen/units/' + b.dataset.almArchive + '/archive', 'POST'));
        showToast('Unidad archivada', 'success');
        await reloadUnits();
        await loadProducts();
      }
    } catch (err) { fail(err); }
  });

  $('almUnitsForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentProduct) return;
    const count = Number($('almUnitsCount').value);
    const serial = $('almUnitsSerial').value.trim();
    try {
      const d = await busy($('almUnitsBtn'), () => send('/api/almacen/products/' + currentProduct.id + '/units', 'POST', { count, serial: serial || null }));
      $('almUnitsSerial').value = '';
      showToast(d.units.length === 1 ? 'Unidad creada' : `${d.units.length} unidades creadas`, 'success');
      await reloadUnits();
      await loadProducts();
    } catch (err) { fail(err); }
  });

  /* ---- carga al abrir la pestaña */
  async function init() {
    if (loaded) return;
    try {
      meta = await j('/api/almacen/meta');
      fillSelects();
      await Promise.all([loadCategories(), loadProducts()]);
      loaded = true;
    } catch (e) { $('almProducts').innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(e.message)}</p></div>`; }
  }
  if (tab) tab.addEventListener('gw:tabshow', () => { init().then(() => { const s = $('almScan'); if (s) s.focus(); }); });
})();
