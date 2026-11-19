/* Catálogo de inventario (Configuración → «Inventario», solo Super Admin): categorías y productos (unidad, SKU y campos propios). Crear, editar, archivar, restaurar y eliminar.
   API: /api/inventory/* (app/routers/inventory.py). Todo se escapa; sin manejadores en línea (delegación); mensajes con showToast / showConfirm. */
(function () {
  'use strict';
  const root = document.getElementById('inventario');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const ICONS = root.dataset.icons || '/static/img/icons.svg';
  const icon = (n) => `<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="${ICONS}#i-${n}"/></svg>`;
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());
  let catalog = { categories: [], products: [], units: [] };
  let showArchived = false;
  let editing = null;          // id del producto que se edita (null = crear)
  const PROD_TITLE = $('invProdFormTitle').textContent;
  const norm = (v) => String(v == null ? '' : v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();          // sin tildes ni mayúsculas, como el buscador de Inicio
  const NOUNIT = !$('invProdUnit');          // con Almacén activo el formulario no pide unidad de medida ni SKU (la unidad queda «unidad» y el SKU vacío)
  const NOCATS = !$('invCatForm');          // con Almacén activo la pantalla no tiene categorías (ni su selector): los productos no se agrupan

  async function j(url, opts) { const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error'); return d; }
  const send = (url, method, body) => j(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });

  const STATUS_ES = { creado: 'Creado', en_proceso: 'En proceso', finalizado: 'Finalizado' };
  function whereHtml(name, u, listOnly) {
    const evs = (u.events || []).map((e) => `<li><strong>${esc(e.name)}</strong> · ${esc(STATUS_ES[e.status] || e.status)}${e.archived ? ' · archivado' : ''} · ${esc(e.qty_assigned)} asignado(s)${e.qty_out ? `, ${esc(e.qty_out)} salieron` : ''}</li>`).join('');
    const units = u.units ? `<p class="gw-hint">Objetos con serial: ${esc(u.units)}</p>` : '';
    const body = evs ? `<ul class="gw-list">${evs}</ul>` : '<p class="gw-hint">No está asignado a ningún evento.</p>';
    return (listOnly ? '' : `«${esc(name)}»:`) + body + units;
  }

  /* «Marca» · «Voltaje:número» -> [{label, kind}] (y de vuelta para editar). */
  function parseFields(text) {
    return String(text || '').split('\n').map((l) => l.trim()).filter(Boolean).map((line) => {
      const m = line.match(/^(.*?)\s*:\s*(n[uú]mero|numero|number|texto|text)\s*$/i);
      if (m) return { label: m[1].trim(), kind: /^n/i.test(m[2]) ? 'number' : 'text' };
      return { label: line, kind: 'text' };
    });
  }
  const fieldsToText = (fields) => (fields || []).map((f) => f.label + (f.kind === 'number' ? ':número' : '')).join('\n');

  function catRow(c) {
    const btns = [];
    if (!c.archived) {
      btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-cat-rename="${c.id}" data-name="${esc(c.name)}" aria-label="Renombrar ${esc(c.name)}">${icon('edit')} Renombrar</button>`);
      btns.push(`<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-cat-archive="${c.id}" data-name="${esc(c.name)}" aria-label="Archivar ${esc(c.name)}">${icon('trash')} Archivar</button>`);
    } else {
      btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-cat-restore="${c.id}" aria-label="Restaurar ${esc(c.name)}">${icon('undo')} Restaurar</button>`);
      btns.push(`<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-cat-del="${c.id}" data-name="${esc(c.name)}" aria-label="Eliminar definitivamente ${esc(c.name)}">${icon('trash')} Eliminar definitivamente</button>`);
    }
    return `<article class="gw-card-row"><div class="gw-card-row__head"><span class="gw-card-row__title">${esc(c.name)}</span>${c.archived ? '<span class="gw-badge">Archivada</span>' : ''}</div>
      <p class="gw-card-row__meta">${c.archived ? 'Archivada' : (c.products === 1 ? '1 producto activo' : c.products + ' productos activos')}</p><div class="gw-card-row__actions">${btns.join('')}</div></article>`;
  }

  function prodRow(p) {
    const btns = [`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-prod-where="${p.id}" data-name="${esc(p.name)}" aria-label="¿Dónde está ${esc(p.name)}?">${icon('search')} ¿Dónde está?</button>`];
    if (!p.archived) {
      btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-prod-edit="${p.id}" aria-label="Editar ${esc(p.name)}">${icon('edit')} Editar</button>`);
      btns.push(`<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-prod-archive="${p.id}" data-name="${esc(p.name)}" aria-label="Archivar ${esc(p.name)}">${icon('trash')} Archivar</button>`);
    } else {
      btns.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-prod-restore="${p.id}" aria-label="Restaurar ${esc(p.name)}">${icon('undo')} Restaurar</button>`);
      btns.push(`<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-prod-del="${p.id}" data-name="${esc(p.name)}" aria-label="Eliminar definitivamente ${esc(p.name)}">${icon('trash')} Eliminar definitivamente</button>`);
    }
    const meta = [NOCATS ? '' : (p.category_name ? esc(p.category_name) : '<span class="gw-badge gw-badge--warn">Sin categoría</span>'), NOUNIT ? '' : esc(p.unit), p.sku && !NOUNIT ? 'SKU ' + esc(p.sku) : '', p.stock != null ? 'Existencias ' + esc(p.stock) : '']
      .concat((p.fields || []).length ? ['Campos: ' + p.fields.map((f) => esc(f.label)).join(', ')] : []).filter(Boolean).join(' · ');
    return `<article class="gw-card-row" data-prod-id="${p.id}"><div class="gw-card-row__head"><span class="gw-card-row__title">${esc(p.name)}</span>${p.archived ? '<span class="gw-badge">Archivado</span>' : ''}</div>
      <p class="gw-card-row__meta">${meta}</p><div class="gw-card-row__actions">${btns.join('')}</div><div data-alm-slot="${p.id}"></div></article>`;          // el hueco lo llena almacen-catalog.js (solo con Almacén activo)
  }

  const empty = (title, text) => `<div class="gw-state" role="status"><p class="gw-state__title">${title}</p><p class="gw-state__text">${text}</p></div>`;

  function paint() {
    if (!NOCATS) {
      const cats = catalog.categories.filter((c) => showArchived || !c.archived);
      $('invCatList').innerHTML = cats.map(catRow).join('') || empty('Todavía no hay categorías', 'Crea la primera con el formulario de arriba.');
    }
    const q = norm($('invProdSearch').value).trim();
    const active = catalog.products.filter((p) => showArchived || !p.archived);
    const prods = q ? active.filter((p) => norm(p.name + (NOUNIT ? '' : ' ' + (p.sku || ''))).includes(q)) : active;
    $('invProdList').innerHTML = prods.map(prodRow).join('') || (q ? empty('Ningún tipo coincide', 'Prueba con otra palabra o borra la búsqueda.') : empty('Todavía no hay productos', 'Crea el primero con el formulario de arriba; aparecerá en el inventario de los eventos.'));
    $('invProdSearchInfo').textContent = q ? `${prods.length} de ${active.length}` : '';
    if (!NOCATS) {
      const sel = $('invProdCat'), keep = sel.value;
      sel.innerHTML = '<option value="">Sin categoría</option>' + catalog.categories.filter((c) => !c.archived).map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
      sel.value = keep;
    }
    if (!NOUNIT) $('invUnitList').innerHTML = (catalog.units || []).map((u) => `<option value="${esc(u)}">`).join('');
    root.dispatchEvent(new CustomEvent('gw:catalog-painted'));          // Almacén (almacen-catalog.js) agrega a cada tarjeta su control, objetos y QR
  }

  async function load() {
    try { catalog = await j('/api/inventory/catalog?include_archived=true', { cache: 'no-store' }); paint(); }
    catch (e) {
      if (window.console && console.error) console.error('Catálogo de inventario:', e);
      const where = String((e && e.stack) || '').split('\n').slice(1, 3).map((l) => l.trim().replace(/^at\s+/, '').replace(/https?:\/\/[^/]+/, '')).join(' ← ');          // dónde falló (archivo y línea): para poder diagnosticar con una captura
      if (!NOCATS) $('invProdList').innerHTML = '';
      $((NOCATS ? 'invProdList' : 'invCatList')).innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudo cargar el catálogo</p><p class="gw-state__text">${esc(e.message)}</p>${where ? `<p class="gw-hint">${esc(where)}</p>` : ''}<button type="button" class="gw-btn gw-btn--secondary" data-inv-retry>Reintentar</button></div>`;
    }
  }

  function resetProductForm() {
    editing = null;
    $('invProdName').value = ''; if (!NOUNIT) { $('invProdSku').value = ''; $('invProdUnit').value = 'unidad'; } $('invProdStock').value = ''; $('invProdFields').value = ''; if (!NOCATS) $('invProdCat').value = '';
    $('invProdBtn').innerHTML = `${icon('plus')} Crear producto`; $('invProdCancel').hidden = true; $('invProdFormTitle').textContent = PROD_TITLE; $('invProdFormSum').textContent = 'Crear un tipo de elemento';
    root.dispatchEvent(new CustomEvent('gw:product-form-reset'));
  }

  if (!NOCATS) $('invCatForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('invCatName').value.trim();
    if (!name) { showToast('Escribe el nombre de la categoría', 'error'); return; }
    try { await busy($('invCatBtn'), () => send('/api/inventory/categories', 'POST', { name })); $('invCatName').value = ''; showToast(`Categoría «${name}» creada`, 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
  });

  $('invProdForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { name: $('invProdName').value.trim(), stock: $('invProdStock').value.trim(), fields: parseFields($('invProdFields').value) };
    if (!NOUNIT) { body.unit = $('invProdUnit').value.trim(); body.sku = $('invProdSku').value.trim(); }
    if (!NOCATS) body.category_id = $('invProdCat').value || null;          // sin selector de categoría, no se toca la que ya tenga
    if (!body.name) { showToast('Escribe el nombre del producto', 'error'); return; }
    try {
      const wasEditing = !!editing;
      const saved = await busy($('invProdBtn'), () => (editing ? send(`/api/inventory/products/${editing}`, 'PATCH', body) : send('/api/inventory/products', 'POST', body)));
      showToast(wasEditing ? 'Producto actualizado' : `Producto «${body.name}» creado`, 'success');
      const detail = { id: saved && saved.id, created: !wasEditing, work: null };
      root.dispatchEvent(new CustomEvent('gw:product-saved', { detail }));          // Almacén (si está activo) pone en detail.work lo suyo: control, fila, foto
      if (detail.work) await detail.work;
      resetProductForm(); load();
    } catch (err) { showToast(err.message, 'error'); }
  });
  $('invProdCancel').addEventListener('click', resetProductForm);
  $('invProdSearch').addEventListener('input', () => { if (catalog) paint(); });
  $('invShowArchived').addEventListener('change', (e) => { showArchived = e.target.checked; paint(); });

  root.addEventListener('click', async (e) => {
    const t = (sel) => e.target.closest(sel);
    if (t('[data-inv-retry]')) { load(); return; }
    let b;
    if ((b = t('[data-cat-rename]'))) {
      const name = await showPrompt('Nuevo nombre de la categoría:', { title: 'Renombrar categoría', defaultValue: b.dataset.name, confirmLabel: 'Guardar' });
      if (!name || name === b.dataset.name) return;
      try { await busy(b, () => send(`/api/inventory/categories/${b.dataset.catRename}`, 'PATCH', { name })); showToast('Categoría renombrada', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    } else if ((b = t('[data-cat-archive]'))) {
      if (!(await showConfirm(`¿Archivar la categoría «${esc(b.dataset.name)}»? No se puede si tiene productos activos.`, { confirmLabel: 'Archivar' }))) return;
      try { await busy(b, () => send(`/api/inventory/categories/${b.dataset.catArchive}/archive`, 'POST')); showToast('Categoría archivada', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    } else if ((b = t('[data-cat-restore]'))) {
      try { await busy(b, () => send(`/api/inventory/categories/${b.dataset.catRestore}/restore`, 'POST')); showToast('Categoría restaurada', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    } else if ((b = t('[data-cat-del]'))) {
      if (!(await showConfirm(`¿Eliminar DEFINITIVAMENTE la categoría «${esc(b.dataset.name)}»? No se puede deshacer y queda registrado.`, { confirmLabel: 'Eliminar definitivamente' }))) return;
      try { await busy(b, () => send(`/api/inventory/categories/${b.dataset.catDel}`, 'DELETE')); showToast('Categoría eliminada', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    } else if ((b = t('[data-prod-edit]'))) {
      const p = catalog.products.find((x) => String(x.id) === b.dataset.prodEdit);
      if (!p) return;
      editing = p.id;
      $('invProdName').value = p.name; if (!NOUNIT) { $('invProdSku').value = p.sku || ''; $('invProdUnit').value = p.unit; } $('invProdStock').value = p.stock == null ? '' : String(p.stock); if (!NOCATS) $('invProdCat').value = p.category_id == null ? '' : String(p.category_id); $('invProdFields').value = fieldsToText(p.fields);
      $('invProdBtn').textContent = 'Guardar producto'; $('invProdCancel').hidden = false; $('invProdFormTitle').textContent = `Editando «${p.name}»`; $('invProdFormBox').open = true; $('invProdFormSum').textContent = `Editando «${p.name}»`;
      root.dispatchEvent(new CustomEvent('gw:product-edit', { detail: { id: p.id } }));
      $('invProdName').focus();
    } else if ((b = t('[data-prod-archive]'))) {
      if (!(await showConfirm(`¿Archivar el producto «${esc(b.dataset.name)}»? Deja de ofrecerse en los eventos; el historial de los que ya lo usan se conserva.`, { confirmLabel: 'Archivar' }))) return;
      try { await busy(b, () => send(`/api/inventory/products/${b.dataset.prodArchive}/archive`, 'POST')); showToast('Producto archivado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    } else if ((b = t('[data-prod-restore]'))) {
      try { await busy(b, () => send(`/api/inventory/products/${b.dataset.prodRestore}/restore`, 'POST')); showToast('Producto restaurado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    } else if ((b = t('[data-prod-where]'))) {
      try {
        const u = await busy(b, () => j(`/api/inventory/products/${b.dataset.prodWhere}/usage`));
        await showConfirm(whereHtml(b.dataset.name, u), { variant: 'warning', title: '¿Dónde está?', confirmLabel: 'Cerrar' });
      } catch (err) { showToast(err.message, 'error'); }
    } else if ((b = t('[data-prod-del]'))) {
      let u = null, force = false;
      try { u = await busy(b, () => j(`/api/inventory/products/${b.dataset.prodDel}/usage`)); } catch (err) { showToast(err.message, 'error'); return; }
      if (u.movements || u.novelties) {
        await showConfirm(`«${esc(b.dataset.name)}» ya tiene salidas, entradas o novedades de almacén registradas: por su historial no se puede eliminar y se queda archivado.` + whereHtml('', u, true), { variant: 'warning', title: 'No se puede eliminar', confirmLabel: 'Entendido' });
        return;
      }
      if (u.events.length || u.units) {
        force = true;
        if (!(await showConfirm(`«${esc(b.dataset.name)}» todavía está asignado. Si sigues, se quita de estos eventos${u.units ? ` y se eliminan sus ${u.units} objeto(s) con serial` : ''} y se elimina definitivamente (no se puede deshacer y queda registrado).` + whereHtml('', u, true), { confirmLabel: 'Quitar y eliminar' }))) return;
      } else if (!(await showConfirm(`¿Eliminar DEFINITIVAMENTE el producto «${esc(b.dataset.name)}»? No se puede deshacer y queda registrado.`, { confirmLabel: 'Eliminar definitivamente' }))) return;
      try { await busy(b, () => send(`/api/inventory/products/${b.dataset.prodDel}${force ? '?force=1' : ''}`, 'DELETE')); showToast('Producto eliminado', 'success'); load(); } catch (err) { showToast(err.message, 'error'); }
    }
  });

  // se carga al abrir la pestaña (no antes: no pega al servidor si nadie la mira)
  let loaded = false;
  const start = () => { if (!loaded) { loaded = true; load(); } };
  const tab = $('tab_inventario');
  if (tab) { tab.addEventListener('click', start); tab.addEventListener('gw:tabshow', start); }
  if (!root.hidden) start();
})();
