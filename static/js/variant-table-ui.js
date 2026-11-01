/* Pantalla de la «Tabla de variantes» (P11) del diseñador de formularios. Se monta en un contenedor con un contexto que da el diseñador (así se prueba con jsdom):
     VariantTableUI.mount(host, ctx) -> { destroy, state }
   ctx = { design(), optionsOf(fieldId) -> lista|null, fieldLabel(fieldId), propsOf(fieldId) -> [propiedades], propLabel(prop), fields() -> [{id,label}] con variantes posibles,
           url (base de /variant-table), apply(built) -> deshacer(), toast(msg, tipo), confirm(msg, opts) -> Promise<bool>, richEdit(html) -> Promise<string|null>, assetUrl(p) }
   La lógica (celdas, filas, conversión a variantes, pegar, imágenes) está en static/js/variant-table.js; aquí solo la pantalla.
   Fechas y números se guardan como TEXTO de presentación (no como datos consultables).                                                     */
(function () {
  if (typeof window === 'undefined') return;
  const VT = window.VariantTable, esc = (t) => String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const TYPE_LABEL = { text: 'Texto', image: 'Imagen', date: 'Fecha', number: 'Número', options: 'Lista de opciones' };
  const WARNING = 'No escribas aquí información confidencial: todo el contenido de las variantes es visible para quien abra el formulario, aunque no se le muestre.';

  function mount(host, ctx) {
    const st = { varFields: [], subsets: [], columns: [], rows: [], images: {}, uploaded: {}, undo: null, sel: { r: 0, c: 0 }, notInTable: 0, seq: 0, editing: null };
    const uidCol = () => 'k' + (++st.seq);

    // ---------------------------------------------------------------- estado → definición para VariantTable
    const choice = () => ctx.fields().filter((f) => ctx.optionsOf(f.id));
    const spec = () => ({
      variables: st.varFields.map((id, i) => ({ field: id, label: ctx.fieldLabel(id), options: (st.subsets[i] || ctx.optionsOf(id) || []) })),
      columns: st.columns.map((c) => ({ id: c.id, name: c.name || ctx.propLabel(c.prop), field: c.field, prop: c.prop, type: c.type, options: c.type === 'options' ? c.options : undefined })),
      rows: st.rows, images: st.images,
    });
    function regen() {   // filas = combinaciones de las variables; lo ya escrito se conserva por valor (sin tildes ni mayúsculas)
      const prev = new Map(st.rows.map((r) => [r.keys.map(VT.norm).join('\u0001'), r.cells]));
      const vars = st.varFields.map((id, i) => ({ field: id, options: st.subsets[i] || ctx.optionsOf(id) || [] }));
      if (!vars.length) { st.rows = []; st.tooMany = ''; return; }
      const r = VT.rowsFromVariables(vars);
      st.tooMany = r.error || '';
      st.rows = r.rows ? r.rows.map((row) => ({ keys: row.keys, cells: prev.get(row.keys.map(VT.norm).join('\u0001')) || {} })) : [];
    }
    const outsideCount = () => {   // variantes del formulario que esta tabla NO reemplaza
      const mine = new Set(st.columns.map((c) => c.field + '\u0000' + c.prop));
      return Object.values(ctx.design().fields).reduce((a, f) => a + Object.entries(f.variants || {}).reduce((b, [prop, v]) => b + (mine.has(f.id + '\u0000' + prop) ? 0 : (v.items || []).length), 0), 0);
    };
    // Una variante solo puede usar campos de SU hoja o de las anteriores (P12): si una columna apunta a un elemento de una hoja anterior a la de un campo que decide, no se puede aplicar.
    const sheetProblem = () => {
      if (!ctx.sheetOf) return '';
      for (const c of st.columns) {
        if (!c.field) continue;
        const bad = st.varFields.find((id) => ctx.sheetOf(id) > ctx.sheetOf(c.field));
        if (bad) return `«${ctx.fieldLabel(bad)}» está en una hoja posterior a «${ctx.fieldLabel(c.field)}»: una variante solo puede usar campos de su hoja o de las anteriores.`;
      }
      return '';
    };
    const missing = (c) => !!c.field && !!ctx.exists && !ctx.exists(c.field);   // el elemento de la columna se borró desde que se armó (o la plantilla venía de otro formulario)
    const autoName = (field, prop, skip) => {   // nombre de columna = nombre corto del elemento (y la propiedad si no es la principal); único: el Excel no admite dos iguales
      let base = (ctx.shortName ? ctx.shortName(field) : '') || ctx.propLabel(prop);
      if (!['content', 'src'].includes(prop)) base += ' · ' + ctx.propLabel(prop);
      let name = base, k = 2;
      while (st.columns.some((c) => c !== skip && VT.norm(c.name) === VT.norm(name))) name = `${base} (${k++})`;
      return name;
    };
    const cellInfo = (c, raw) => { const col = spec().columns.find((x) => x.id === c.id); return VT.parseCell(c.type, raw, col); };

    // ---------------------------------------------------------------- pintado
    function paint() {
      const flds = ctx.fields(), ch = choice();
      host.innerHTML = `<div class="vt-warn" style="background:#fff8e1; border:1px solid #f0ad4e; color:#7a5b00; border-radius:8px; padding:6px 8px; font-size:.8rem;"><b>Variantes.</b> ${esc(WARNING)}</div>
        <p class="hint" style="margin:6px 0;">Cada fila es una combinación de lo que decide; cada columna cambia un elemento del formulario. Las fechas y los números se guardan como <b>texto de presentación</b> (dd/mm/aaaa; 1.234,56), no como datos que se puedan consultar. Aplicar <b>reemplaza</b> las variantes de las propiedades de las columnas elegidas.</p>
        <div class="vt-sec"><b>1. Qué decide</b> <span class="hint">(1 a ${VT.MAX_VARS} campos con opciones)</span>
          <div style="display:flex; gap:6px; flex-wrap:wrap; margin:4px 0;">${[0, 1, 2].map((i) => `<select data-vt-var="${i}" aria-label="Campo que decide ${i + 1}"><option value="">${i === 0 ? '— elige un campo —' : '— ninguno —'}</option>${ch.map((f) => `<option value="${esc(f.id)}" ${st.varFields[i] === f.id ? 'selected' : ''}>${esc(f.label)}</option>`).join('')}</select>`).join('')}</div>
          ${st.varFields.map((id, i) => `<details data-vt-sub="${i}" ${st.tooMany ? 'open' : ''}><summary class="hint" style="cursor:pointer;">Valores de «${esc(ctx.fieldLabel(id))}» (${(st.subsets[i] || ctx.optionsOf(id) || []).length} de ${(ctx.optionsOf(id) || []).length})</summary><div style="max-height:130px; overflow:auto; display:flex; flex-wrap:wrap; gap:2px 12px;">${(ctx.optionsOf(id) || []).map((o) => `<label style="font-size:.76rem;"><input type="checkbox" data-vt-subset="${i}" value="${esc(o)}" ${!st.subsets[i] || st.subsets[i].includes(o) ? 'checked' : ''}> ${esc(o)}</label>`).join('')}</div></details>`).join('')}
          ${st.tooMany ? `<div class="vt-err" role="alert" style="color:#a1261b; font-size:.8rem;">${esc(st.tooMany)}</div>` : ''}</div>
        <div class="vt-sec" style="margin-top:8px;"><b>2. Qué cambia</b> <span class="hint">(1 a ${VT.MAX_COLS} columnas)</span>
          ${st.columns.map((c, i) => colHtml(c, i, flds)).join('')}${sheetProblem() ? `<div class="vt-err" role="alert" style="color:#a1261b; font-size:.8rem;">${esc(sheetProblem())}</div>` : ''}
          <button type="button" class="small-btn" data-vt-act="addcol" ${st.columns.length >= VT.MAX_COLS ? 'disabled' : ''}>+ Agregar columna</button> <button type="button" class="small-btn" data-vt-act="savetpl" ${st.columns.length ? '' : 'disabled'} title="Guarda el nombre, el tipo y las opciones de las columnas en un archivo .json para reusarlas en otro formulario">Guardar columnas como plantilla (.json)</button> <label class="small-btn" style="cursor:pointer;">Usar una plantilla (.json)…<input type="file" data-vt-tpl accept=".json,application/json" style="display:none;"></label> <button type="button" class="small-btn" data-vt-act="load" ${st.columns.length && st.rows.length ? '' : 'disabled'} title="Trae a la tabla las variantes que el formulario ya tiene en estas columnas">Cargar lo que ya tiene el formulario</button></div>
        <div class="vt-sec" style="margin-top:8px;"><b>3. La tabla</b> <span class="hint">Haz clic en una celda para escribir, o pega un bloque copiado de Excel.</span>
          <div style="display:flex; gap:6px; flex-wrap:wrap; margin:4px 0;"><button type="button" class="small-btn" data-vt-act="dlempty" ${st.rows.length && st.columns.length ? '' : 'disabled'} title="Las columnas y una fila por cada valor, sin datos">Descargar plantilla vacía</button><button type="button" class="small-btn" data-vt-act="dlform" ${st.rows.length && st.columns.length ? '' : 'disabled'} title="Las variantes que ya están guardadas en el formulario">Descargar lo que tiene el formulario</button><label class="small-btn" style="cursor:pointer;">Subir Excel…<input type="file" data-vt-upload accept=".xlsx" style="display:none;"></label>${st.columns.some((c) => c.type === 'image') ? '<label class="small-btn" style="cursor:pointer;" title="Se empareja por el nombre del archivo ANTES de subir nada; solo se suben las que emparejan">Imágenes…<input type="file" data-vt-images accept="image/png,image/jpeg,image/webp,image/gif" multiple style="display:none;"></label>' : ''}</div>
          <div class="hint" style="margin:2px 0 6px;"><b>Plantilla vacía</b>: las columnas y una fila por cada valor, sin datos (con hojas «Instrucciones» y «Valores válidos»). <b>Lo que tiene el formulario</b>: las variantes ya guardadas en el diseño (lo que apenas escribiste en esta pantalla no va hasta que lo apliques). <b>Subir Excel</b>: se revisa todo y ves una vista previa antes de cambiar nada.</div>
          <div class="vt-assignbox"></div>
          <div class="vt-gridwrap" tabindex="0" aria-label="Tabla de variantes" style="max-height:340px; overflow:auto; border:1px solid #ddd; border-radius:8px;">${gridHtml()}</div>
          <div class="vt-status hint" role="status" aria-live="polite" style="margin-top:4px;"></div></div>
        <div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; justify-content:flex-end;"><button type="button" class="small-btn" data-vt-act="undo" ${st.undo ? '' : 'disabled'}>Deshacer la tabla aplicada</button><button type="button" class="small-btn primary" data-vt-act="apply" ${st.rows.length && st.columns.length ? '' : 'disabled'}>Vista previa y aplicar…</button></div>`;
      validateAll(); paintAssign();
    }
    function colHtml(c, i, flds) {
      const f = flds.find((x) => x.id === c.field), props = f ? ctx.propsOf(f.id) : (c.prop ? [c.prop] : []);
      const types = c.prop === 'src' ? ['image'] : ['text', 'date', 'number', 'options'];
      return `<div class="vt-col" style="display:flex; gap:4px; flex-wrap:wrap; align-items:center; margin:4px 0; padding:4px; border:1px solid #e3e5ec; border-radius:8px;">
        <input type="text" data-vt-colname="${i}" maxlength="60" value="${esc(c.name)}" placeholder="Nombre de la columna" aria-label="Nombre de la columna ${i + 1}" style="width:170px;">
        <select data-vt-colfield="${i}" aria-label="Elemento de la columna ${i + 1}"><option value="">— elemento —</option>${flds.map((x) => `<option value="${esc(x.id)}" ${c.field === x.id ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select>
        <select data-vt-colprop="${i}" aria-label="Propiedad de la columna ${i + 1}">${props.map((p) => `<option value="${p}" ${c.prop === p ? 'selected' : ''}>${esc(ctx.propLabel(p))}</option>`).join('')}</select>
        <select data-vt-coltype="${i}" aria-label="Tipo de la columna ${i + 1}">${types.map((t) => `<option value="${t}" ${c.type === t ? 'selected' : ''}>${TYPE_LABEL[t]}</option>`).join('')}</select>
        ${c.type === 'options' ? `<textarea data-vt-colopts="${i}" rows="2" placeholder="Una opción por línea" aria-label="Opciones de la columna ${i + 1}" style="width:150px;">${esc((c.options || []).join('\n'))}</textarea>` : ''}
        <button type="button" class="small-btn danger" data-vt-act="delcol" data-vt-i="${i}" aria-label="Quitar la columna ${i + 1}">✕</button>${missing(c) ? '<div class="vt-err" role="alert" style="flex-basis:100%; color:#a1261b; font-size:.78rem;">El elemento de esta columna ya no existe: elige otro para volver a usarla.</div>' : ''}</div>`;
    }
    function gridHtml() {
      if (!st.rows.length || !st.columns.length) return '<p class="hint" style="padding:10px;">Elige qué decide y agrega al menos una columna para ver la tabla.</p>';
      const head = st.varFields.map((id) => `<th scope="col" style="position:sticky; top:0; background:#f3f5ff;">${esc(ctx.fieldLabel(id))}</th>`).join('') + st.columns.map((c) => `<th scope="col" style="position:sticky; top:0; background:#f3f5ff;">${esc(c.name || ctx.propLabel(c.prop))}<div class="hint" style="font-weight:400;" title="${esc(c.field && !missing(c) ? ctx.fieldLabel(c.field) : '')}">${TYPE_LABEL[c.type]}${missing(c) ? ' · ⚠ sin elemento' : ''}</div></th>`).join('');
      const body = st.rows.map((r, ri) => `<tr>${r.keys.map((k) => `<th scope="row" style="text-align:left; background:#fafafa; white-space:nowrap;">${esc(k)}</th>`).join('')}${st.columns.map((c, ci) => `<td data-vt-r="${ri}" data-vt-c="${ci}" tabindex="-1" style="min-width:110px; max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; border:1px solid #eee; cursor:text;">${esc(showCell(c, r.cells[c.id]))}</td>`).join('')}</tr>`).join('');
      return `<table class="vt-grid" style="border-collapse:collapse; font-size:.8rem; width:100%;"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    }
    const showCell = (c, raw) => { if (raw == null || raw === '') return ''; const p = cellInfo(c, raw); return p.error ? String(raw) : (c.type === 'text' ? RichTextPlain(p.value) : p.value); };
    const RichTextPlain = (v) => (window.RichText ? window.RichText.toPlain(v).replace(/\s+/g, ' ') : v);
    function validateAll() {
      let bad = 0;
      host.querySelectorAll('td[data-vt-r]').forEach((td) => {
        const c = st.columns[+td.dataset.vtC], raw = st.rows[+td.dataset.vtR].cells[c.id];
        const p = raw ? cellInfo(c, raw) : {};
        td.style.background = p.error ? '#fdecea' : ''; td.title = p.error || ''; td.setAttribute('aria-invalid', p.error ? 'true' : 'false');
        if (p.error) bad += 1;
      });
      st.bad = bad;
      const s = host.querySelector('.vt-status');
      if (s && bad) s.textContent = `${bad} ${bad === 1 ? 'celda inválida' : 'celdas inválidas'} (en rojo): corrígelas antes de aplicar.`;
    }
    const status = (msg) => { const s = host.querySelector('.vt-status'); if (s) s.textContent = msg; };

    // ---------------------------------------------------------------- edición de una celda (un solo editor, solo al hacer clic)
    function beginEdit(td) {
      endEdit();
      const ri = +td.dataset.vtR, ci = +td.dataset.vtC, c = st.columns[ci], raw = st.rows[ri].cells[c.id] || '';
      st.sel = { r: ri, c: ci };
      let el;
      if (c.type === 'options') {
        el = document.createElement('select');
        el.innerHTML = '<option value=""></option>' + (c.options || []).map((o) => `<option value="${esc(o)}" ${VT.norm(o) === VT.norm(raw) ? 'selected' : ''}>${esc(o)}</option>`).join('');
      } else { el = document.createElement('input'); el.type = 'text'; el.value = raw; if (c.type === 'date') el.placeholder = 'dd/mm/aaaa'; if (c.type === 'number') el.placeholder = '1.234,56'; if (c.type === 'image') el.placeholder = 'nombre-del-archivo.jpg'; }
      el.style.cssText = 'width:100%; box-sizing:border-box;'; el.setAttribute('aria-label', `${c.name || 'Celda'}: ${st.rows[ri].keys.join(' · ')}`);
      td.textContent = ''; td.appendChild(el);
      if (c.type === 'text') { const b = document.createElement('button'); b.type = 'button'; b.className = 'small-btn'; b.textContent = 'Formato…'; b.dataset.vtRich = '1'; b.addEventListener('mousedown', (e) => e.preventDefault()); b.addEventListener('click', () => richEdit(td, ri, c)); td.appendChild(b); }
      st.editing = { td, el, ri, c };
      el.focus();
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); endEdit(); } else if (e.key === 'Escape') { e.preventDefault(); endEdit(true); } });
      el.addEventListener('blur', () => setTimeout(() => { if (st.editing && st.editing.el === el && !st.richOpen) endEdit(); }, 0));
    }
    function endEdit(cancel) {
      const e = st.editing; if (!e) return;
      st.editing = null;
      if (!cancel) { const v = e.el.value; if (v) st.rows[e.ri].cells[e.c.id] = v; else delete st.rows[e.ri].cells[e.c.id]; }
      e.td.textContent = showCell(e.c, st.rows[e.ri].cells[e.c.id]);
      validateAll();
    }
    async function richEdit(td, ri, c) {
      const e = st.editing; const cur = e ? e.el.value : (st.rows[ri].cells[c.id] || '');
      st.richOpen = true;
      const out = await ctx.richEdit(cur);
      st.richOpen = false;
      if (out != null) { if (out) st.rows[ri].cells[c.id] = out; else delete st.rows[ri].cells[c.id]; if (st.editing) st.editing.el.value = out; }
      endEdit(true); td.textContent = showCell(c, st.rows[ri].cells[c.id]); validateAll();
    }

    // ---------------------------------------------------------------- pegar desde Excel
    function onPaste(e) {
      const text = (e.clipboardData && e.clipboardData.getData('text/plain')) || '';
      const inInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT';
      if (!text || (inInput && !/[\t\n]/.test(text))) return;                 // una sola cosa en una celda: pegado normal
      if (!e.target.closest('.vt-gridwrap')) return;
      e.preventDefault();
      endEdit(true);
      const grid = VT.parsePaste(text);
      if (!grid.length) return;
      // ¿el bloque trae las columnas de las variables (se empareja por valor) o son solo datos (empiezan en la celda elegida)?
      const nv = st.varFields.length, opts = (k) => st.subsets[k] || ctx.optionsOf(st.varFields[k]) || [];
      const byKeys = nv > 0 && grid[0].length > nv && (grid[0].slice(0, nv).every((v, k) => opts(k).some((o) => VT.norm(o) === VT.norm(v))) || VT.norm(grid[0][0]) === VT.norm(ctx.fieldLabel(st.varFields[0])));
      const res = VT.pasteInto(spec(), grid, byKeys ? { byKeys: true } : { startRow: st.sel.r, startCol: st.sel.c });       // spec().rows son las filas reales
      st.notInTable += res.unmatched.length;
      host.querySelector('.vt-gridwrap').innerHTML = gridHtml(); validateAll();
      status(`Se pegaron ${res.applied} celdas${res.unmatched.length ? `; ${res.unmatched.length} ${res.unmatched.length === 1 ? 'fila no está en la tabla y se ignoró' : 'filas no están en la tabla y se ignoraron'}` : ''}.`);
    }

    // ---------------------------------------------------------------- Excel: bajar y subir
    const baseSpec = () => { const s = spec(); return { variables: s.variables.map((v) => ({ label: v.label, field: v.field, options: v.options })), columns: s.columns.map((c) => ({ id: c.id, name: c.name, type: c.type, options: c.options })), rows: st.rows.map((r) => ({ keys: r.keys, cells: r.cells })) }; };
    async function download(kind) {   // 'empty' = sin datos; 'form' = lo que ya tiene el formulario (variantes guardadas en el diseño)
      try {
        const body = baseSpec();
        if (kind === 'empty') body.rows.forEach((r) => { r.cells = {}; });
        else { const cur = VT.fromDesign(ctx.design(), spec()); body.rows.forEach((r, i) => { r.cells = cur.rows[i].cells; }); }
        const r = await fetch(ctx.url + '/template', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!r.ok) { const d = await r.json().catch(() => ({})); ctx.toast(d.detail || 'No se pudo generar el Excel', 'error'); return; }
        const blob = await r.blob(), a = document.createElement('a');
        a.href = URL.createObjectURL(blob); a.download = kind === 'empty' ? 'plantilla-vacia-tabla-de-variantes.xlsx' : 'tabla-de-variantes-actual.xlsx'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      } catch (e) { ctx.toast('No se pudo descargar el Excel', 'error'); }
    }
    async function upload(file, mapping) {   // `mapping`: la asignación de columnas de ESTA subida (no se recuerda)
      if (!file) return;
      if (!/\.xlsx$/i.test(file.name)) { ctx.toast('Sube un archivo .xlsx', 'error'); return; }
      if (file.size > 2 * 1024 * 1024) { ctx.toast('El archivo pesa más de 2 MB', 'error'); return; }
      const fd = new FormData(); fd.append('file', file); fd.append('spec', JSON.stringify(baseSpec()));
      if (mapping) fd.append('mapping', JSON.stringify(mapping));
      try {
        const r = await fetch(ctx.url + '/parse', { method: 'POST', credentials: 'same-origin', body: fd });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { ctx.toast(d.detail || 'No se pudo leer el Excel', 'error'); return; }
        if (d.needs_mapping) { startAssign(file, d.headers); return; }       // los encabezados no coinciden con las columnas: la persona decide a qué corresponde cada uno
        st.assign = null; paintAssign();
        d.matched_rows.forEach((i) => { st.rows[i].cells = d.rows[i].cells; });
        st.notInTable += d.unmatched_rows.length;
        host.querySelector('.vt-gridwrap').innerHTML = gridHtml(); validateAll();
        const parts = [`Se leyeron ${d.matched_rows.length} filas`];
        if (d.problems.length) parts.push(`${d.problems.length} celdas con problemas (en rojo)`);
        if (d.unmatched_rows.length) parts.push(`${d.unmatched_rows.length} filas del Excel no están en la tabla`);
        if (d.duplicated_rows.length) parts.push(`${d.duplicated_rows.length} repetidas`);
        if (d.ignored_columns.length) parts.push(`${d.ignored_columns.length} columnas se ignoraron: ${d.ignored_columns.join(', ')}`);
        if (d.missing_rows) parts.push(`${d.missing_rows} filas de la tabla no venían en el Excel (no se tocaron)`);
        status(parts.join('; ') + '.');
        d.problems.forEach((p) => { const td = host.querySelector(`td[data-vt-r="${p.row}"][data-vt-c="${st.columns.findIndex((c) => c.id === p.col)}"]`); if (td) { td.style.background = '#fdecea'; td.title = p.message; } });
      } catch (e) { ctx.toast('No se pudo leer el Excel', 'error'); }
    }

    // ---------------------------------------------------------------- «Asignar columnas»: encabezados del Excel → variables / columnas de la tabla (vale solo para esta subida)
    function guess(header) {
      const h = VT.norm(header);
      const vi = st.varFields.findIndex((id) => [ctx.fieldLabel(id), ctx.shortName ? ctx.shortName(id) : ''].some((n) => n && VT.norm(n) === h));
      if (vi >= 0) return 'v' + vi;
      const c = st.columns.find((x) => x.field && !missing(x) && [x.name, ctx.shortName ? ctx.shortName(x.field) : '', ctx.fieldLabel(x.field)].some((n) => n && VT.norm(n) === h));
      return c ? 'c:' + c.id : 'ignore';
    }
    function startAssign(file, headers) {
      st.assign = { file, headers, choice: Object.fromEntries(headers.map((x) => [x.header, x.suggested || guess(x.header)])) };
      paintAssign();
    }
    function assignProblem() {
      const a = st.assign, picked = Object.values(a.choice).filter((t) => t !== 'ignore'), seen = new Set();
      for (const t of picked) { if (seen.has(t)) return 'Dos columnas del Excel están asignadas al mismo destino.'; seen.add(t); }
      const lost = st.varFields.findIndex((_, i) => !seen.has('v' + i));
      return lost >= 0 ? `Falta asignar la columna de «${ctx.fieldLabel(st.varFields[lost])}»: es la que dice a qué fila va cada dato.` : '';
    }
    function paintAssign() {
      const box = host.querySelector('.vt-assignbox'); if (!box) return;
      const a = st.assign;
      if (!a) { box.innerHTML = ''; return; }
      const opt = (v, label, cur) => `<option value="${esc(v)}" ${cur === v ? 'selected' : ''}>${esc(label)}</option>`;
      const problem = assignProblem();
      box.innerHTML = `<div class="vt-assign" role="region" aria-label="Asignar columnas" style="border:2px solid #9fb0ff; border-radius:10px; padding:8px; margin:6px 0; background:#f7f8ff;">
        <b>Asignar columnas</b> <span class="hint">Las cabeceras del Excel no coinciden con las columnas de la tabla. Elige a qué corresponde cada una, o «Ignorar». Esta asignación vale solo para esta subida.</span>
        <table style="font-size:.8rem; margin-top:4px;"><tbody>${a.headers.map((x, i) => `<tr><td style="padding:2px 8px 2px 0;"><b>${esc(x.header)}</b></td><td><select data-vt-assign="${i}" aria-label="Destino de la columna ${esc(x.header)} del Excel">
          ${opt('ignore', 'Ignorar esta columna', a.choice[x.header])}${st.varFields.map((id, k) => opt('v' + k, `Decide: ${ctx.fieldLabel(id)}`, a.choice[x.header])).join('')}${st.columns.map((c) => opt('c:' + c.id, `${c.name || ctx.propLabel(c.prop)} — ${c.field && !missing(c) ? ctx.fieldLabel(c.field) : 'sin elemento'} · ${ctx.propLabel(c.prop)}`, a.choice[x.header])).join('')}</select></td></tr>`).join('')}</tbody></table>
        ${problem ? `<div class="vt-err" role="alert" style="color:#a1261b; font-size:.8rem;">${esc(problem)}</div>` : ''}
        <div style="display:flex; gap:6px; justify-content:flex-end; margin-top:6px;"><button type="button" class="small-btn" data-vt-act="assigncancel">Cancelar</button><button type="button" class="small-btn primary" data-vt-act="assigngo" ${problem ? 'disabled' : ''}>Continuar</button></div></div>`;
    }

    // ---------------------------------------------------------------- plantillas de columnas (.json): solo nombre, tipo, propiedad y opciones; nada de ids de campos
    function saveTemplate() {
      const json = VT.exportTemplate(st.columns, st.varFields.map(ctx.fieldLabel), (id) => (id ? ctx.fieldLabel(id) : ''));
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' })); a.download = 'plantilla-de-tabla.json'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }
    function loadTemplate(file) {
      if (!file) return;
      if (!/\.json$/i.test(file.name) || file.size > 100000) { ctx.toast('Sube una plantilla .json (máximo 100 KB)', 'error'); return; }
      const rd = new FileReader();
      rd.onload = async () => {
        const t = VT.parseTemplate(String(rd.result));
        if (t.error) { ctx.toast(t.error, 'error'); return; }
        if (st.columns.length && !(await ctx.confirm('La plantilla reemplaza las columnas actuales de la tabla (lo escrito en ellas se pierde). ¿Continuar?', { confirmLabel: 'Usar la plantilla' }))) return;
        const flds = ctx.fields();
        const pick = (c) => {   // por id (el elemento sigue siendo el mismo aunque lo hayan renombrado o movido); si no, por el nombre que tenía; si no, queda para reasignar
          const byId = flds.find((x) => x.id === c.elementId && ctx.propsOf(x.id).includes(c.prop));
          const f = byId || flds.find((x) => (VT.norm(x.label) === VT.norm(c.element) || (ctx.shortName && VT.norm(ctx.shortName(x.id)) === VT.norm(c.element))) && ctx.propsOf(x.id).includes(c.prop));
          return f ? f.id : '';
        };
        st.columns = t.columns.map((c) => ({ id: uidCol(), name: c.name, field: pick(c), prop: c.prop, type: c.type, options: c.options }));
        if (!st.varFields.length && t.variables.length) {   // si la plantilla recuerda qué decidía, se proponen los campos con ese nombre
          st.varFields = t.variables.map((l) => choice().find((f) => VT.norm(f.label) === VT.norm(l))).filter(Boolean).map((f) => f.id).filter((id, i, a) => a.indexOf(id) === i); st.subsets = []; regen();
        }
        st.rows.forEach((r) => { r.cells = {}; });
        paint();
        const loose = st.columns.filter((c) => !c.field).length;
        status(`Se cargaron ${st.columns.length} columnas${loose ? `; ${loose} sin elemento (ya no existe o es de otro formulario): elige a cuál se aplica cada una` : ''}.`);
      };
      rd.onerror = () => ctx.toast('No se pudo leer la plantilla', 'error');
      rd.readAsText(file);
    }

    // ---------------------------------------------------------------- imágenes: se empareja por nombre EN EL NAVEGADOR y solo lo que empareja se sube (lo subido nunca se borra)
    const MAX_IMG_BYTES = 8000000, MAX_IMG_FILES = 200;
    async function pickImages(fileList) {
      const files = Array.from(fileList || []);
      if (!files.length) return;
      if (files.length > MAX_IMG_FILES) { ctx.toast(`Elige hasta ${MAX_IMG_FILES} imágenes por vez`, 'error'); return; }
      const m = VT.matchImages(spec(), files.map((f) => f.name));
      const byName = new Map(files.map((f) => [f.name, f]));
      const big = m.matches.filter((x) => byName.get(x.file).size > MAX_IMG_BYTES);
      const ok = m.matches.filter((x) => byName.get(x.file).size <= MAX_IMG_BYTES);
      const list = (arr) => arr.slice(0, 8).map((x) => esc(typeof x === 'string' ? x : x.file)).join(', ') + (arr.length > 8 ? ` y ${arr.length - 8} más` : '');
      const lines = [`<b>${ok.length}</b> de ${files.length} imágenes emparejaron con una fila y se subirán.`];
      if (m.unmatched.length) lines.push(`<b>${m.unmatched.length}</b> no emparejaron y <b>no se subirán</b>: ${list(m.unmatched)}.`);
      if (m.duplicated.length) lines.push(`${m.duplicated.length} repetidas para la misma fila (no se suben): ${list(m.duplicated)}.`);
      if (big.length) lines.push(`${big.length} pesan más de 8 MB (no se suben): ${list(big)}.`);
      lines.push(`${m.rowsWithout} filas quedarán sin imagen.`);
      if (!ok.length) { ctx.toast('Ninguna imagen emparejó con una fila: no se sube nada', 'error'); status(m.unmatched.slice(0, 5).map((x) => `${x.file}: ${x.reason}`).join('. ')); return; }
      if (!(await ctx.confirm(lines.join('<br>'), { confirmLabel: `Subir ${ok.length} ${ok.length === 1 ? 'imagen' : 'imágenes'}` }))) return;
      let done = 0, failed = [];
      const queue = ok.slice();
      const worker = async () => {
        while (queue.length) {
          const x = queue.shift(), f = byName.get(x.file), prev = st.uploaded[x.file];
          try {
            const path = prev && prev.size === f.size && prev.mtime === f.lastModified ? prev.path : await ctx.uploadImage(f);   // la misma imagen no se sube dos veces
            st.uploaded[x.file] = { size: f.size, mtime: f.lastModified, path }; st.images[x.file] = path;
            st.rows[x.row].cells[x.col] = x.file; done += 1;
          } catch (err) { failed.push(x.file); }
          status(`Subiendo imágenes… ${done + failed.length} de ${ok.length}`);
        }
      };
      await Promise.all([worker(), worker(), worker()]);
      host.querySelector('.vt-gridwrap').innerHTML = gridHtml(); validateAll();
      status(`Se subieron ${done} ${done === 1 ? 'imagen' : 'imágenes'}${failed.length ? `; fallaron ${failed.length}: ${failed.slice(0, 5).join(', ')}` : ''}.`);
      if (failed.length) ctx.toast(`No se pudieron subir ${failed.length} imágenes`, 'error');
    }

    // ---------------------------------------------------------------- vista previa y aplicar
    async function apply() {
      endEdit();
      const s = spec();
      const loose = st.columns.find((c) => !c.field || !c.prop || missing(c));
      if (loose) { ctx.toast(`La columna «${loose.name || 'sin nombre'}» no tiene elemento: elige a cuál se aplica`, 'error'); return; }
      if (sheetProblem()) { ctx.toast(sheetProblem(), 'error'); return; }
      const built = VT.build(s, ctx.design().fields, { otherVariants: outsideCount() });
      if (built.error) { ctx.toast(built.error, 'error'); return; }
      validateAll();
      if (st.bad) { ctx.toast(`Hay ${st.bad} celdas inválidas (en rojo). Corrígelas antes de aplicar.`, 'error'); return; }
      const m = built.summary;
      const msg = `Se crearán ${m.variants} variantes en ${m.elements} ${m.elements === 1 ? 'elemento' : 'elementos'}. Se reemplazarán ${m.replaced} variantes existentes. ${m.rowsWithoutImage} filas sin imagen, ${m.notInList + st.notInTable} valores que no están en la lista, ${m.invalid} celdas inválidas.`;
      if (!(await ctx.confirm(esc(msg), { confirmLabel: 'Aplicar la tabla' }))) return;
      st.undo = ctx.apply(built);
      st.notInTable = 0;
      ctx.toast('Tabla aplicada. Puedes deshacerla hasta guardar el diseño.', 'success');
      paint();
    }

    // ---------------------------------------------------------------- eventos (delegados: el contenedor se repinta)
    const onChange = (e) => {
      const t = e.target;
      if (t.dataset.vtAssign !== undefined) { const x = st.assign.headers[+t.dataset.vtAssign]; st.assign.choice[x.header] = t.value; paintAssign(); }
      else if (t.dataset.vtVar !== undefined) {
        st.varFields = [0, 1, 2].map((i) => (host.querySelector(`[data-vt-var="${i}"]`) || {}).value).filter(Boolean);
        st.varFields = st.varFields.filter((id, i, a) => a.indexOf(id) === i); st.subsets = []; regen(); paint();
      } else if (t.dataset.vtSubset !== undefined) {
        const i = +t.dataset.vtSubset, all = ctx.optionsOf(st.varFields[i]) || [];
        const picked = Array.from(host.querySelectorAll(`[data-vt-subset="${i}"]:checked`)).map((x) => x.value);
        st.subsets[i] = picked.length === all.length ? null : picked; regen(); paint();
      } else if (t.dataset.vtColfield !== undefined) {
        const c = st.columns[+t.dataset.vtColfield]; c.field = t.value; const props = c.field ? ctx.propsOf(c.field) : []; c.prop = props.includes(c.prop) ? c.prop : (props[0] || ''); c.type = c.prop === 'src' ? 'image' : (c.type === 'image' ? 'text' : c.type); if (c.field && (!c.name || c.nameAuto)) { c.name = autoName(c.field, c.prop, c); c.nameAuto = true; } paint();
      } else if (t.dataset.vtColprop !== undefined) {
        const c = st.columns[+t.dataset.vtColprop]; c.prop = t.value; c.type = c.prop === 'src' ? 'image' : (c.type === 'image' ? 'text' : c.type); if (c.nameAuto) c.name = autoName(c.field, c.prop, c); paint();
      } else if (t.dataset.vtColtype !== undefined) { st.columns[+t.dataset.vtColtype].type = t.value; paint(); }
      else if (t.dataset.vtColopts !== undefined) { st.columns[+t.dataset.vtColopts].options = t.value.split('\n').map((x) => x.trim()).filter(Boolean); host.querySelector('.vt-gridwrap').innerHTML = gridHtml(); validateAll(); }
      else if (t.dataset.vtTpl !== undefined) { const f = t.files[0]; t.value = ''; loadTemplate(f); }
      else if (t.dataset.vtImages !== undefined) { const fl = Array.from(t.files || []); t.value = ''; pickImages(fl); }
      else if (t.dataset.vtUpload !== undefined) { const f = t.files[0]; t.value = ''; upload(f); }
    };
    const onInput = (e) => { const t = e.target; if (t.dataset.vtColname !== undefined) { const c = st.columns[+t.dataset.vtColname]; c.name = t.value; c.nameAuto = false; } };
    const onClick = (e) => {
      const td = e.target.closest('td[data-vt-r]');
      if (td && !td.querySelector('input,select')) { beginEdit(td); return; }
      const b = e.target.closest('[data-vt-act]'); if (!b || b.disabled) return;
      const act = b.dataset.vtAct;
      if (act === 'addcol') { st.columns.push({ id: uidCol(), name: '', field: '', prop: '', type: 'text', options: [] }); paint(); }
      else if (act === 'delcol') { st.columns.splice(+b.dataset.vtI, 1); paint(); }
      else if (act === 'load') {
        const r = VT.fromDesign(ctx.design(), spec());
        r.rows.forEach((row, i) => { st.rows[i].cells = row.cells; });
        host.querySelector('.vt-gridwrap').innerHTML = gridHtml(); validateAll();
        status(r.skipped ? `Se cargó lo que tiene forma de tabla. ${r.skipped} ${r.skipped === 1 ? 'variante' : 'variantes'} de estas columnas (por ejemplo con «alguno de» o varios grupos) no se pueden mostrar aquí y se reemplazarán al aplicar.` : 'Se cargó lo que ya tiene el formulario.');
      } else if (act === 'dlempty') download('empty');
      else if (act === 'dlform') download('form');
      else if (act === 'savetpl') saveTemplate();
      else if (act === 'assigncancel') { st.assign = null; paintAssign(); }
      else if (act === 'assigngo') { const a = st.assign; if (a && !assignProblem()) { const mapping = Object.fromEntries(Object.entries(a.choice)); st.assign = null; paintAssign(); upload(a.file, mapping); } }
      else if (act === 'apply') apply();
      else if (act === 'undo') { if (st.undo) { const ok = st.undo(); st.undo = null; ctx.toast(ok === false ? 'El diseño ya se guardó: la tabla no se puede deshacer' : 'Se deshizo la tabla aplicada', ok === false ? 'error' : 'success'); paint(); } }
    };
    host.addEventListener('change', onChange); host.addEventListener('input', onInput); host.addEventListener('click', onClick); host.addEventListener('paste', onPaste);
    paint();
    return { state: st, spec, paint, regen, destroy: () => { host.removeEventListener('change', onChange); host.removeEventListener('input', onInput); host.removeEventListener('click', onClick); host.removeEventListener('paste', onPaste); host.innerHTML = ''; } };
  }
  window.VariantTableUI = { mount };
})();
