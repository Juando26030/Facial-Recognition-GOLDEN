/* Almacén dentro de «Administrar catálogo» (Inventario): cada producto es un TIPO de elemento («Portátil Lenovo»); aquí se le define cómo se controla (con serial / por modelo / por cantidad),
   la fila del checklist GEYL, si es consumible y su foto; y, para los de serial, se agregan los OBJETOS reales de ese tipo: cada objeto recibe su propio código QR, que se muestra en un campo.
   Los de modelo o cantidad llevan un solo QR por tipo (también visible). Se engancha a inventory-catalog-admin.js por eventos (gw:catalog-painted, gw:product-saved, gw:product-edit,
   gw:product-form-reset) y solo carga con Almacén activo. API: /api/almacen/*. Todo se escapa; sin manejadores en línea (delegación); mensajes con showToast / showConfirm.
   Guardado unificado: el serial de cada objeto es una EDICIÓN EN LÍNEA y queda pendiente (`serialDraft`) hasta «Guardar cambios» de la barra única (GWParams, bloque «almacen-seriales»; la tarjeta de objetos
   está dentro de [data-pnodirty], por eso se marca a mano). Agregar objetos, subir fotos, imprimir etiquetas y archivar son ACTOS inmediatos con aviso (archivar pide confirmación). */
(function () {
  'use strict';
  const root = document.getElementById('inventario');
  const box = document.getElementById('almCatBox');
  if (!root || !box) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());
  let meta = null;
  let byId = {};          // producto del almacén por id (control, QR, fotos, objetos)
  let currentProduct = null;
  let units = [];
  const serialDraft = {};          // serial editado sin guardar: serialDraft[idObjeto] = texto
  const P = () => window.GWParams;
  const icon = (name, cls) => `<svg class="gw-icon ${cls || ''}" aria-hidden="true"><use href="${esc(($('almUnitsCard') && $('almUnitsCard').dataset.icons) || '')}#i-${name}"/></svg>`;

  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error'); return d; }
  const send = (url, method, body) => j(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const fail = (e) => showToast(e && e.message ? e.message : 'No se pudo completar la acción', 'error');
  const trackingLabel = (k) => ((meta.tracking.find((t) => t.key === k) || {}).label) || k;

  /* ---- campos del formulario */
  function rowOptions(selected) {
    const groups = {};
    meta.rows.forEach((r) => { (groups[r.section] = groups[r.section] || []).push(r); });
    return '<option value="">Sin fila (no sale en el checklist)</option>' + Object.keys(groups).map((s) =>
      `<optgroup label="${esc(meta.sections[s] || s)}">${groups[s].map((r) => `<option value="${esc(r.key)}"${r.key === selected ? ' selected' : ''}>${esc(r.label)}</option>`).join('')}</optgroup>`).join('');
  }
  function fillForm() {
    $('almCatTracking').innerHTML = meta.tracking.map((t) => `<option value="${esc(t.key)}">${esc(t.label)}</option>`).join('');
    $('almCatRow').innerHTML = rowOptions('');
    showHint();
  }
  function showHint() {
    const t = meta.tracking.find((x) => x.key === $('almCatTracking').value);
    $('almCatTrackingHint').textContent = t ? t.hint : '';
  }
  function resetForm() {
    if (!meta) return;
    $('almCatTracking').value = 'serial';
    $('almCatRow').value = '';
    $('almCatConsumable').checked = false;
    $('almCatPhoto').value = '';
    showHint();
  }
  function loadForm(id) {
    const p = byId[id];
    if (!p || !meta) return;
    $('almCatTracking').value = p.tracking || 'cantidad';
    $('almCatRow').value = p.checklist_row || '';
    $('almCatConsumable').checked = !!p.is_consumable;
    $('almCatPhoto').value = '';
    showHint();
  }

  /* ---- datos y tarjetas */
  async function loadAlmacen() {
    const d = await j('/api/almacen/products');
    byId = {};
    (d.products || []).forEach((p) => { byId[p.id] = p; });
  }
  function slot(p) {
    if (!p) return '';
    const photo = p.photo_url ? `<img class="gw-alm__thumb" src="${esc(p.photo_url)}" alt="Foto de ${esc(p.name)}" width="48" height="48" loading="lazy">` : '';
    const ctrl = `<span class="gw-badge">${esc(trackingLabel(p.tracking))}</span>` + (p.is_consumable ? ' <span class="gw-badge gw-badge--warn">Consumible</span>' : '') + (p.checklist_row ? '' : ' <span class="gw-hint">Sin fila del checklist</span>');
    let qr;
    let btns = `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-alm-photo="${p.id}">${icon('image', 'gw-icon--sm')} ${p.has_photo ? 'Cambiar foto' : 'Agregar foto'}</button>`
      + (p.has_photo ? ` <button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-alm-photo-del="${p.id}" data-name="${esc(p.name)}">${icon('trash', 'gw-icon--sm')} Quitar foto</button>` : '');
    if (p.tracking === 'serial') {
      qr = `<span class="gw-hint">${p.units} ${p.units === 1 ? 'objeto' : 'objetos'} con QR propio</span>`;
      btns = `<button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-alm-units="${p.id}">${icon('qr', 'gw-icon--sm')} Objetos y QR</button> ` + btns;
    } else {
      qr = p.qr_code ? `<label class="gw-label" for="almQr${p.id}">Código QR del tipo</label><input class="gw-input gw-alm__qr" id="almQr${p.id}" type="text" readonly value="${esc(p.qr_code)}" data-alm-select>` : '';
      btns = `<button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-alm-label="${p.id}">${icon('printer', 'gw-icon--sm')} Etiqueta QR</button> ` + btns;
    }
    return `<div class="gw-alm__slot">${photo}<div class="gw-alm__slotbody"><div>${ctrl}</div>${qr ? `<div class="gw-alm__qrbox">${qr}</div>` : ''}<div class="gw-alm__actions">${btns}</div></div></div>`;
  }
  function paintSlots() {
    root.querySelectorAll('[data-alm-slot]').forEach((el) => { el.innerHTML = slot(byId[Number(el.dataset.almSlot)]); });
  }
  async function refresh() {
    try { await loadAlmacen(); paintSlots(); } catch (e) { fail(e); }
  }

  /* ---- fotos del elemento (el servidor valida y reduce la imagen) */
  async function uploadPhoto(productId, file) {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/almacen/products/' + productId + '/photo', { method: 'POST', body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo subir la foto');
    return d;
  }
  const photoPicker = document.createElement('input');          // un solo selector de archivos reutilizado por las tarjetas
  photoPicker.type = 'file';
  photoPicker.accept = 'image/*';
  photoPicker.hidden = true;
  root.appendChild(photoPicker);
  let photoFor = null;
  photoPicker.addEventListener('change', async () => {
    const f = photoPicker.files && photoPicker.files[0];
    const id = photoFor;
    photoPicker.value = '';
    if (!f || !id) return;
    try { await uploadPhoto(id, f); showToast('Foto guardada', 'success'); await refresh(); } catch (err) { fail(err); }
  });

  /* ---- objetos (unidades con serial) y su QR */
  function unitsTable() {
    if (!units.length) return `<div class="gw-empty gw-alm__empty" role="status"><p>Todavía no hay objetos de este tipo. Agrega los primeros arriba.</p></div>`;
    return `<div class="gw-table-wrap"><table class="gw-table gw-alm__table"><caption class="gw-sr-only">Objetos de ${esc(currentProduct.name)} con su código QR</caption>
      <thead><tr><th scope="col"><span class="gw-sr-only">Marcar para imprimir</span></th><th scope="col">Objeto</th><th scope="col">Código QR</th><th scope="col">Serial</th><th scope="col">Estado</th><th scope="col"><span class="gw-sr-only">Acciones</span></th></tr></thead>
      <tbody>${units.map((u) => {
        const dirty = Object.prototype.hasOwnProperty.call(serialDraft, u.id);
        const serial = dirty ? serialDraft[u.id] : (u.serial || '');
        return `<tr data-alm-unit="${u.id}"${dirty ? ' class="gw-alm__dirty"' : ''}>
        <td class="gw-alm__pickcell"><label class="gw-check"><input type="checkbox" class="gw-alm__pick" data-pick="${u.id}" aria-label="Marcar ${esc(u.title)} para imprimir"></label></td>
        <td>${esc(u.title)}</td>
        <td><input class="gw-input gw-alm__qr" type="text" readonly value="${esc(u.code)}" data-alm-select aria-label="Código QR de ${esc(u.title)}"></td>
        <td><input class="gw-input" type="text" value="${esc(serial)}" maxlength="80" data-serial="${u.id}" aria-label="Serial de ${esc(u.title)}" autocomplete="off"></td>
        <td><span class="gw-badge${u.status === 'novedad' ? ' gw-badge--warn' : u.status === 'en_evento' ? ' gw-badge--info' : ' gw-badge--ok'}">${esc(u.status_label)}</span>${u.event_name ? `<br><span class="gw-hint">${esc(u.event_name)}</span>` : ''}</td>
        <td><div class="gw-alm__actions"><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-alm-print-one="${u.id}">${icon('printer', 'gw-icon--sm')} Etiqueta</button>
          <button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-alm-archive="${u.id}" data-title="${esc(u.title)}">${icon('trash', 'gw-icon--sm')} Archivar</button></div></td></tr>`;
      }).join('')}</tbody></table></div>`;
  }

  /* ---- seriales pendientes: se guardan con la barra única */
  function setSerialDraft(id, value) {
    const u = units.find((x) => x.id === id);
    if (u && value === (u.serial || '')) delete serialDraft[id]; else serialDraft[id] = value;          // volvió a lo original: ya no es un cambio
    const tr = $('almUnits').querySelector(`[data-alm-unit="${id}"]`);
    if (tr) tr.classList.toggle('gw-alm__dirty', Object.prototype.hasOwnProperty.call(serialDraft, id));
    if (P()) { if (Object.keys(serialDraft).length) P().markDirty('almacen-seriales'); else P().markClean('almacen-seriales'); }
  }
  async function saveSerials() {          // lo llama la barra única; usa el endpoint de siempre, un objeto por llamada
    const fails = [];
    for (const id of Object.keys(serialDraft)) {
      const value = serialDraft[id];
      try {
        await send('/api/almacen/units/' + id, 'PATCH', { serial: value });
        if (serialDraft[id] === value) delete serialDraft[id];          // si lo editaron mientras guardaba, sigue pendiente
      } catch (e) { fails.push(e && e.message ? e.message : 'error'); }
    }
    if (currentProduct) { try { await reloadUnits(); } catch (e) { /* se repinta la próxima vez */ } }
    if (fails.length) throw new Error(`${fails.length} ${fails.length === 1 ? 'serial no se guardó' : 'seriales no se guardaron'} (${fails[0]})`);
  }
  if (P()) P().register({ key: 'almacen-seriales', label: 'Seriales de Almacén', order: 20, save: saveSerials });
  async function openUnits(productId) {
    currentProduct = byId[productId];
    if (!currentProduct) return;
    $('almUnitsTitle').textContent = 'Objetos de «' + currentProduct.name + '» y su QR';
    $('almUnitsCard').hidden = false;
    if (window.GW && window.GW.skeleton) window.GW.skeleton($('almUnits'), { kind: 'table', rows: 3, cols: 5, label: 'Cargando los objetos…' }); else $('almUnits').textContent = 'Cargando…';
    await reloadUnits();
    $('almUnitsCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
    $('almUnitsCount').focus();
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
    if (!unitIds.length && !productIds.length) { showToast('Marca al menos un objeto', 'error'); return; }
    window.open('/inventario/etiquetas?' + qs.toString(), '_blank');
  }

  /* ---- enganche con el administrador del catálogo */
  let starting = null;
  root.addEventListener('gw:catalog-painted', () => {          // se carga al abrir «Administrar catálogo», no antes
    if (!meta) { starting = starting || init(); return; }
    refresh();
  });
  root.addEventListener('gw:product-form-reset', resetForm);
  root.addEventListener('gw:product-edit', (e) => loadForm(e.detail && e.detail.id));
  root.addEventListener('gw:product-saved', (e) => {
    const d = e.detail;
    if (!d || !d.id || !meta) return;
    const body = { tracking: $('almCatTracking').value, checklist_row: $('almCatRow').value, is_consumable: $('almCatConsumable').checked };
    const photo = $('almCatPhoto').files && $('almCatPhoto').files[0];
    d.work = (async () => {          // se leyó el formulario YA (antes de que se limpie); el guardado corre mientras tanto
      try { await send('/api/almacen/products/' + d.id, 'PATCH', body); } catch (err) { showToast('El producto se guardó, pero su control de bodega no: ' + err.message, 'error'); return; }
      if (photo) { try { await uploadPhoto(d.id, photo); } catch (err) { showToast('El producto se guardó, pero la foto no: ' + err.message, 'error'); } }
      if (d.created && body.tracking === 'serial') showToast('Ahora agrega sus objetos con el botón «Objetos y QR» de la tarjeta', 'success');
    })();
  });
  $('almCatTracking').addEventListener('change', showHint);
  root.addEventListener('input', (e) => {          // serial de un objeto: solo queda pendiente
    const t = e.target;
    if (t && t.dataset && t.dataset.serial) setSerialDraft(Number(t.dataset.serial), t.value);
  });

  root.addEventListener('click', async (e) => {
    const sel = e.target.closest('[data-alm-select]');
    if (sel) { sel.select(); return; }
    const b = e.target.closest('button');
    if (!b) return;
    try {
      if (b.dataset.almPhoto) {
        photoFor = Number(b.dataset.almPhoto);
        photoPicker.click();
      } else if (b.dataset.almPhotoDel) {
        if (!(await showConfirm(`¿Quitar la foto de «${esc(b.dataset.name)}»?`, { confirmLabel: 'Quitar' }))) return;
        await busy(b, () => send('/api/almacen/products/' + b.dataset.almPhotoDel + '/photo', 'DELETE'));
        showToast('Foto quitada', 'success');
        await refresh();
      } else if (b.dataset.almUnits) {
        await openUnits(Number(b.dataset.almUnits));
      } else if (b.dataset.almLabel) {
        printLabels([], [Number(b.dataset.almLabel)]);
      } else if (b.dataset.almUnitsClose !== undefined) {
        $('almUnitsCard').hidden = true;
        currentProduct = null;
      } else if (b.dataset.almPrintOne) {
        printLabels([Number(b.dataset.almPrintOne)], []);
      } else if (b.dataset.almPrintSelected !== undefined) {
        printLabels(Array.from(root.querySelectorAll('.gw-alm__pick:checked')).map((c) => Number(c.dataset.pick)), []);
      } else if (b.dataset.almPrintAll !== undefined) {
        printLabels(units.map((u) => u.id), []);
      } else if (b.dataset.almArchive) {
        if (!(await showConfirm(`¿Archivar «${esc(b.dataset.title)}»? Deja de ofrecerse, pero conserva su número y su código.`, { confirmLabel: 'Archivar' }))) return;
        await busy(b, () => send('/api/almacen/units/' + b.dataset.almArchive + '/archive', 'POST'));
        delete serialDraft[Number(b.dataset.almArchive)];
        if (P() && !Object.keys(serialDraft).length) P().markClean('almacen-seriales');
        showToast('Objeto archivado', 'success');
        await reloadUnits();
        await refresh();
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
      showToast(d.units.length === 1 ? 'Objeto agregado: ' + d.units[0].title + ' · QR ' + d.units[0].code : `${d.units.length} objetos agregados`, 'success');
      await reloadUnits();
      await refresh();
    } catch (err) { fail(err); }
  });

  async function init() {
    try { meta = await j('/api/almacen/meta'); fillForm(); resetForm(); await loadAlmacen(); paintSlots(); } catch (e) { fail(e); starting = null; }
  }
})();
