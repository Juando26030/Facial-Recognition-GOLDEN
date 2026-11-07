/* Diseñador del FORMULARIO DE PERSONA (Parámetros del evento, solo admin+; app/personform.py). Edita la misma definición que usa el quiosco: grupos (sheets), filas con hasta 4 columnas (rows), obligatorio,
   «Texto al escribir» y una condición simple «mostrar solo si» (show_if). Misma dinámica que el diseñador de formularios web (kiosk_formulario_editor.html): lienzo con tarjetas que se ARRASTRAN (soltar
   a la izquierda/derecha de otra la pone en su fila, hasta 4; soltar en la franja entre filas crea una fila nueva), panel de detalles a la derecha al elegir un campo o un grupo, y «Previsualizar».
   Los campos salen de Parámetros › Campos; aquí solo se decide DÓNDE va cada uno y cómo se escribe. Lo obligatorio se guarda en los parámetros del evento (una sola fuente de verdad). Funciones puras (toModel / fromModel / move) probadas en Node; la pantalla
   (mount) solo usa clases .gw-* y toast.js. */
(function (root) {
  const ALWAYS_REQUIRED = ['id', 'first_name'], NEVER_REQUIRED = ['last_name', 'categories', 'birth_date'];
  const FIXED_TEXT = ['first_name', 'last_name', 'role', 'entity', 'opt_1'];
  const MAX_PER_ROW = 4;
  const canCase = (cfg) => ['text_short', 'text_long'].includes(cfg.field_type) && (FIXED_TEXT.includes(cfg.key) || /^opcional_\d+$/.test(cfg.key));
  const simpleCond = (c) => !!c && !c.rules && c.field && (c.op || 'equals') === 'equals' && !Array.isArray(c.value);

  /* GET /person-form → modelo plano para la pantalla: una lista ORDENADA de campos con su grupo y si van «junto al anterior» (misma fila). */
  function toModel(view) {
    const def = view.definition || { sheets: [], rows: [], fields: {} };
    const cfgs = view.fields || [];
    const byKey = {}; cfgs.forEach((c) => { byKey[c.key] = c; });
    const sheets = (def.sheets || []).map((s) => ({ id: s.id, title: s.title, open: s.open !== false }));
    if (!sheets.length) sheets.push({ id: 'datos', title: 'Datos principales', open: true });
    const items = [], seen = new Set();
    (def.rows || []).forEach((row) => {
      (row.items || []).forEach((key, i) => {
        if (!byKey[key] || seen.has(key)) return;
        seen.add(key);
        const f = (def.fields || {})[key] || {}, cfg = byKey[key], cond = f.show_if || null;
        items.push({
          key, label: cfg.label, type: cfg.field_type || 'text_short', sheet: sheets.some((s) => s.id === row.sheet) ? row.sheet : sheets[0].id, joined: i > 0,
          required: ALWAYS_REQUIRED.includes(key) ? true : (NEVER_REQUIRED.includes(key) ? false : !!(f.required != null ? f.required : cfg.required)),
          canRequire: !ALWAYS_REQUIRED.includes(key) && !NEVER_REQUIRED.includes(key), canCase: canCase(cfg), text_case: f.text_case || '',
          showField: simpleCond(cond) ? cond.field : '', showValue: simpleCond(cond) ? String(cond.value == null ? '' : cond.value) : '', rawShowIf: cond && !simpleCond(cond) ? cond : null,
        });
      });
    });
    cfgs.forEach((cfg) => { if (!seen.has(cfg.key)) items.push({ key: cfg.key, label: cfg.label, type: cfg.field_type || 'text_short', sheet: sheets[sheets.length - 1].id, joined: false, required: !!cfg.required, canRequire: !ALWAYS_REQUIRED.includes(cfg.key) && !NEVER_REQUIRED.includes(cfg.key), canCase: canCase(cfg), text_case: '', showField: '', showValue: '', rawShowIf: null }); });
    return { enabled: !!view.enabled, version: def.form_version || 1, sheets, items: sortBySheet(items, sheets) };
  }

  function sortBySheet(items, sheets) {
    const idx = {}; sheets.forEach((s, i) => { idx[s.id] = i; });
    return items.map((it, n) => [it, n]).sort((a, b) => (idx[a[0].sheet] - idx[b[0].sheet]) || (a[1] - b[1])).map((p) => p[0]);
  }

  /* Modelo → cuerpo de PUT /person-form. Filas: cada campo «junto al anterior» (del mismo grupo, máx. 4) comparte fila con él. */
  function fromModel(model) {
    const items = sortBySheet(model.items, model.sheets);
    const rows = [], fields = {};
    items.forEach((it) => {
      const last = rows[rows.length - 1];
      if (it.joined && last && last.sheet === it.sheet && last.items.length < MAX_PER_ROW) last.items.push(it.key);
      else rows.push({ sheet: it.sheet, items: [it.key] });
      const f = {};
      if (it.canRequire) f.required = !!it.required;
      if (it.canCase && it.text_case) f.text_case = it.text_case;
      if (it.rawShowIf) f.show_if = it.rawShowIf;
      else if (it.showField && String(it.showValue).trim() !== '') f.show_if = { field: it.showField, op: 'equals', value: String(it.showValue).trim() };
      fields[it.key] = f;
    });
    return { enabled: !!model.enabled, sheets: model.sheets.map((s) => ({ id: s.id, title: s.title, open: !!s.open })), rows, fields };
  }

  /* Mueve un campo una posición dentro de SU grupo (dir -1 arriba, +1 abajo). Devuelve true si cambió algo. */
  function move(model, key, dir) {
    const items = sortBySheet(model.items, model.sheets);
    const i = items.findIndex((it) => it.key === key);
    if (i < 0) return false;
    let j = i + dir;
    while (j >= 0 && j < items.length && items[j].sheet !== items[i].sheet) j += dir;
    if (j < 0 || j >= items.length) return false;
    [items[i], items[j]] = [items[j], items[i]];
    model.items = items;
    return true;
  }

  const newSheetId = (model) => { let n = model.sheets.length + 1, id; do { id = `g${n++}`; } while (model.sheets.some((s) => s.id === id)); return id; };
  function addSheet(model, title) { const s = { id: newSheetId(model), title: title || 'Grupo nuevo', open: false }; model.sheets.push(s); return s; }
  function removeSheet(model, id) {
    if (model.sheets.length < 2) return false;
    const to = model.sheets.find((s) => s.id !== id).id;
    model.items.forEach((it) => { if (it.sheet === id) it.sheet = to; });
    model.sheets = model.sheets.filter((s) => s.id !== id);
    return true;
  }


  /* ------------------------------------------------------------------------------------------------ filas (lienzo): funciones puras, probadas en Node */
  /* Modelo → filas visibles, en el orden de los grupos: [{ sheet, keys: [...] }]. Cada campo «junto al anterior» (mismo grupo, máx. 4) comparte fila con él. */
  function rowsOf(model) {
    const rows = [];
    sortBySheet(model.items, model.sheets).forEach((it) => {
      const last = rows[rows.length - 1];
      if (it.joined && last && last.sheet === it.sheet && last.keys.length < MAX_PER_ROW) last.keys.push(it.key);
      else rows.push({ sheet: it.sheet, keys: [it.key] });
    });
    return rows;
  }
  /* Filas → modelo (orden, grupo y «junto al anterior» de cada campo). Las filas deben seguir el orden de los grupos. */
  function commitRows(model, rows) {
    const byKey = {}; model.items.forEach((it) => { byKey[it.key] = it; });
    const out = [];
    rows.forEach((r) => r.keys.forEach((k, i) => { const it = byKey[k]; if (!it) return; it.sheet = r.sheet; it.joined = i > 0; out.push(it); }));
    model.items = out;
  }
  const locate = (rows, key) => { for (let r = 0; r < rows.length; r++) { const p = rows[r].keys.indexOf(key); if (p >= 0) return [r, p]; } return null; };
  const dropEmpty = (rows) => rows.filter((r) => r.keys.length);

  /* Suelta `key` en `target`: { beside: otraClave, side: 'left'|'right' } (misma fila que esa tarjeta; tope 4) o { sheet, index } (fila nueva en ese grupo, antes de su fila n.º `index`;
     index = cantidad de filas del grupo la deja al final). Devuelve 'ok', 'full' (la fila ya tiene 4), o 'noop' (nada cambió). */
  function dropAt(model, key, target) {
    const rows = rowsOf(model), at = locate(rows, key);
    if (!at) return 'noop';
    const before = JSON.stringify(rows);
    if (target.beside) {
      if (target.beside === key) return 'noop';
      const tr = locate(rows, target.beside); if (!tr) return 'noop';
      if (tr[0] !== at[0] && rows[tr[0]].keys.length >= MAX_PER_ROW) return 'full';
      const destRow = rows[tr[0]];
      rows[at[0]].keys.splice(at[1], 1);
      let pos = destRow.keys.indexOf(target.beside); if (target.side === 'right') pos += 1;
      destRow.keys.splice(pos, 0, key);
    } else {
      const sheetIdx = (id) => model.sheets.findIndex((s) => s.id === id);
      if (sheetIdx(target.sheet) < 0) return 'noop';
      const inSheet = rows.filter((r) => r.sheet === target.sheet);
      const ref = inSheet[Math.min(target.index, inSheet.length)];       // fila ANTES de la cual se inserta (undefined = al final del grupo)
      rows[at[0]].keys.splice(at[1], 1);
      const nr = { sheet: target.sheet, keys: [key] };
      let pos;
      if (ref) pos = rows.indexOf(ref);
      else if (inSheet.length) pos = rows.indexOf(inSheet[inSheet.length - 1]) + 1;
      else { pos = rows.findIndex((r) => sheetIdx(r.sheet) > sheetIdx(target.sheet)); if (pos < 0) pos = rows.length; }
      rows.splice(pos, 0, nr);
    }
    const clean = dropEmpty(rows);
    if (JSON.stringify(clean) === before) return 'noop';
    commitRows(model, clean);
    return 'ok';
  }

  /* Alternativa por TECLADO al arrastrar (Alt + flechas): izquierda/derecha cambia de columna dentro de la fila; arriba/abajo, si la fila tiene un solo campo, sube/baja la fila entera dentro de su grupo;
     si tiene varios, saca el campo a una fila nueva arriba/abajo. Devuelve true si cambió algo. */
  function moveKey(model, key, dir) {
    const rows = rowsOf(model), at = locate(rows, key);
    if (!at) return false;
    const [ri, pos] = at, row = rows[ri];
    if (dir === 'left' || dir === 'right') {
      const n = pos + (dir === 'left' ? -1 : 1);
      if (n < 0 || n >= row.keys.length) return false;
      [row.keys[pos], row.keys[n]] = [row.keys[n], row.keys[pos]];
    } else {
      const d = dir === 'up' ? -1 : 1;
      if (row.keys.length > 1) { row.keys.splice(pos, 1); rows.splice(d < 0 ? ri : ri + 1, 0, { sheet: row.sheet, keys: [key] }); }
      else { const t = ri + d; if (t < 0 || t >= rows.length || rows[t].sheet !== row.sheet) return false; [rows[ri], rows[t]] = [rows[t], rows[ri]]; }
    }
    commitRows(model, rows);
    return true;
  }
  /* Saca el campo de su fila y lo deja solo, justo debajo. */
  function separate(model, key) {
    const rows = rowsOf(model), at = locate(rows, key);
    if (!at || rows[at[0]].keys.length < 2) return false;
    rows[at[0]].keys.splice(at[1], 1);
    rows.splice(at[0] + 1, 0, { sheet: rows[at[0]].sheet, keys: [key] });
    commitRows(model, rows);
    return true;
  }
  /* Cambia un campo de grupo: queda en su propia fila, al final del grupo destino. */
  function sendToSheet(model, key, sheetId) {
    const it = model.items.find((x) => x.key === key);
    if (!it || it.sheet === sheetId) return false;
    return dropAt(model, key, { sheet: sheetId, index: Infinity }) === 'ok';
  }

  /* ------------------------------------------------------------------------------------------------ pantalla */
  const TYPE_LABEL = { text_short: 'Texto corto', text_long: 'Texto largo', email: 'Correo', phone: 'Teléfono', number: 'Número', date: 'Fecha', select: 'Lista', radio: 'Opciones', checkbox: 'Casilla', categories: 'Categorías' };

  function mount(container, opts) {
    const doc = container.ownerDocument || root.document;
    const toast = opts.toast || root.showToast || (() => {});
    const eventId = opts.eventId, fetchFn = opts.fetch || root.fetch.bind(root);
    const el = (tag, cls, text, attrs) => { const n = doc.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; Object.keys(attrs || {}).forEach((k) => n.setAttribute(k, attrs[k])); return n; };
    const state = { model: null, loaded: false, selected: null };       // selected: { kind: 'field', key } | { kind: 'sheet', id } | null
    // Guardado global de Parámetros (static/js/params-save.js): si existe, este bloque se registra como «personform» y el botón «Guardar» global lo guarda; si no, el botón propio guarda con su toast.
    const gw = opts.params || root.GWParams || null;
    const dirty = () => { if (gw) gw.markDirty('personform'); };
    const url = `/api/events/${eventId}/person-form`;
    const iconUrl = opts.icons || (doc.querySelector && (() => { const u = doc.querySelector('use[href*="icons.svg"]'); return u ? u.getAttribute('href').split('#')[0] : ''; })()) || '/static/img/icons.svg';
    const icon = (name) => { const ns = 'http://www.w3.org/2000/svg', s = doc.createElementNS(ns, 'svg'), u = doc.createElementNS(ns, 'use'); s.setAttribute('class', 'gw-icon gw-icon--sm'); s.setAttribute('aria-hidden', 'true'); u.setAttribute('href', `${iconUrl}#i-${name}`); s.appendChild(u); return s; };
    const sheetName = (s, i) => (s.title && s.title.trim()) || `Grupo ${i + 1}`;
    let focusKey = null;

    const select = (sel) => { state.selected = sel; render(); };
    const changed = () => { dirty(); render(); };

    function dropTarget(e, handler) {
      return (ev) => {
        ev.preventDefault(); ev.stopPropagation();
        let key = ''; try { key = JSON.parse(ev.dataTransfer.getData('text/plain')).key; } catch (x) { return; }
        handler(key, ev);
      };
    }
    function doDrop(key, target) {
      const res = dropAt(state.model, key, target);
      if (res === 'full') { toast(`Una fila admite hasta ${MAX_PER_ROW} campos. Suelta el campo entre dos filas para ponerlo en una fila nueva.`, 'warning'); return; }
      if (res === 'ok') { state.selected = { kind: 'field', key }; focusKey = key; changed(); }
    }

    function card(it, selectedKey) {
      const c = el('div', `gw-pf-card${selectedKey === it.key ? ' gw-pf-card--sel' : ''}`, null, { draggable: 'true', tabindex: '0', role: 'button', 'data-key': it.key,
        'aria-label': `${it.label}${it.required ? ', obligatorio' : ''}${selectedKey === it.key ? ' (seleccionado)' : ''}. Enter para editar; Alt y flechas para mover.` });
      const t = el('div', 'gw-pf-card__type'); t.append(icon(it.type === 'date' ? 'calendar' : 'form'), doc.createTextNode(` ${TYPE_LABEL[it.type] || 'Campo'}`));
      c.append(t, el('div', 'gw-pf-card__label', it.label));
      const tags = el('div', 'gw-pf-card__tags');
      if (it.required) tags.appendChild(el('span', null, 'obligatorio'));
      if (it.text_case) tags.appendChild(el('span', null, it.text_case === 'upper' ? 'MAYÚSCULAS' : 'minúsculas'));
      if (it.showField || it.rawShowIf) tags.appendChild(el('span', null, 'condicional'));
      if (tags.childNodes.length) c.appendChild(tags);
      c.addEventListener('click', () => select({ kind: 'field', key: it.key }));
      c.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); focusKey = it.key; select({ kind: 'field', key: it.key }); return; }
        if (!e.altKey) return;
        const dir = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' }[e.key];
        if (!dir) return;
        e.preventDefault();
        if (moveKey(state.model, it.key, dir)) { state.selected = { kind: 'field', key: it.key }; focusKey = it.key; changed(); }
      });
      c.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', JSON.stringify({ key: it.key })); e.dataTransfer.effectAllowed = 'move'; c.classList.add('gw-pf-card--drag'); });
      c.addEventListener('dragend', () => c.classList.remove('gw-pf-card--drag'));
      c.addEventListener('dragover', (e) => { e.preventDefault(); const r = c.getBoundingClientRect(), left = e.clientX < r.left + r.width / 2; c.classList.toggle('gw-pf-card--dl', left); c.classList.toggle('gw-pf-card--dr', !left); });
      c.addEventListener('dragleave', () => c.classList.remove('gw-pf-card--dl', 'gw-pf-card--dr'));
      c.addEventListener('drop', dropTarget(null, (key, ev) => { const r = c.getBoundingClientRect(), left = ev.clientX < r.left + r.width / 2; c.classList.remove('gw-pf-card--dl', 'gw-pf-card--dr'); doDrop(key, { beside: it.key, side: left ? 'left' : 'right' }); }));
      return c;
    }
    function gap(sheetId, index, label) {
      const g = el('div', 'gw-pf-gap', label || null, { 'data-sheet': sheetId, 'data-index': String(index) });
      g.addEventListener('dragover', (e) => { e.preventDefault(); g.classList.add('gw-pf-gap--over'); });
      g.addEventListener('dragleave', () => g.classList.remove('gw-pf-gap--over'));
      g.addEventListener('drop', dropTarget(null, (key) => { g.classList.remove('gw-pf-gap--over'); doDrop(key, { sheet: sheetId, index }); }));
      return g;
    }

    function renderCanvas(host) {
      const m = state.model, rows = rowsOf(m), byKey = {}; m.items.forEach((it) => { byKey[it.key] = it; });
      const selKey = state.selected && state.selected.kind === 'field' ? state.selected.key : null;
      m.sheets.forEach((s, si) => {
        const mine = rows.filter((r) => r.sheet === s.id), hasRequired = m.items.some((it) => it.sheet === s.id && it.required);
        const isSel = state.selected && state.selected.kind === 'sheet' && state.selected.id === s.id;
        const sec = el('section', `gw-pf-sheet${isSel ? ' gw-pf-sheet--sel' : ''}`, null, { 'data-sheet': s.id });
        const head = el('button', 'gw-pf-sheet__head', null, { type: 'button', 'aria-label': `Grupo ${sheetName(s, si)}: editar nombre y opciones`, 'aria-pressed': isSel ? 'true' : 'false' });
        head.append(el('span', 'gw-pf-sheet__title', sheetName(s, si)), el('span', 'gw-pf-sheet__meta', `${mine.reduce((n, r) => n + r.keys.length, 0)} campo(s) · ${s.open || hasRequired ? 'abierto al empezar' : 'cerrado al empezar'}`));
        head.addEventListener('click', () => select({ kind: 'sheet', id: s.id }));
        sec.appendChild(head);
        const body = el('div', 'gw-pf-sheet__body');
        if (!mine.length) body.appendChild(gap(s.id, 0, 'Arrastra campos aquí'));
        mine.forEach((r, ri) => {
          body.appendChild(gap(s.id, ri));
          const rowEl = el('div', `gw-pf-row gw-pf-row--${r.keys.length}`, null, { 'data-row': String(ri) });
          r.keys.forEach((k) => { if (byKey[k]) rowEl.appendChild(card(byKey[k], selKey)); });
          body.appendChild(rowEl);
        });
        if (mine.length) body.appendChild(gap(s.id, mine.length));
        sec.appendChild(body); host.appendChild(sec);
      });
    }

    /* Panel de detalles (a la derecha): lo mismo que antes iba en columnas de una tabla, ahora por campo. */
    function renderProps(host) {
      const m = state.model, sel = state.selected;
      host.textContent = '';
      if (sel && sel.kind === 'sheet') {
        const s = m.sheets.find((x) => x.id === sel.id);
        if (s) {
          const i = m.sheets.indexOf(s), hasRequired = m.items.some((it) => it.sheet === s.id && it.required);
          host.append(el('h4', 'gw-pf-props__title', 'Grupo'));
          const f = el('div', 'gw-field'); const lab = el('label', 'gw-label', 'Nombre del grupo', { for: 'pfSheetName' });
          const title = el('input', 'gw-input', null, { type: 'text', id: 'pfSheetName', maxlength: '60', placeholder: `Grupo ${i + 1}` }); title.value = s.title;
          title.addEventListener('input', () => { s.title = title.value; dirty(); const t = state.container.querySelector(`.gw-pf-sheet[data-sheet="${s.id}"] .gw-pf-sheet__title`); if (t) t.textContent = sheetName(s, i); });
          f.append(lab, title); host.appendChild(f);
          const open = el('input', null, null, { type: 'checkbox', id: 'pfSheetOpen' }); open.checked = s.open || hasRequired; open.disabled = hasRequired;
          open.addEventListener('change', () => { s.open = open.checked; changed(); });
          const ol = el('label', 'gw-check'); ol.append(open, doc.createTextNode(hasRequired ? ' Abierto al empezar (lleva campos obligatorios)' : ' Abierto al empezar'));
          host.appendChild(ol);
          host.appendChild(el('p', 'gw-hint', 'Un grupo cerrado se abre solo si alguno de sus campos queda mal llenado.'));
          const del = el('button', 'gw-btn gw-btn--danger-outline gw-btn--sm', 'Quitar este grupo', { type: 'button' });
          del.disabled = m.sheets.length < 2;
          del.addEventListener('click', () => { removeSheet(m, s.id); state.selected = null; changed(); });
          host.append(del, el('p', 'gw-hint', m.sheets.length < 2 ? 'Debe quedar al menos un grupo.' : 'Sus campos pasan a otro grupo: no se pierde ninguno.'));
          return;
        }
      }
      const it = sel && sel.kind === 'field' ? m.items.find((x) => x.key === sel.key) : null;
      if (!it) { host.appendChild(el('p', 'gw-hint', 'Selecciona un campo o un grupo del lienzo para editar sus detalles. Arrastra los campos para cambiar su lugar: suéltalos al lado de otro para ponerlos en la misma fila (hasta 4), o entre dos filas para una fila nueva.')); return; }
      const rows = rowsOf(m), at = locate(rows, it.key), alone = at && rows[at[0]].keys.length < 2;
      const h = el('h4', 'gw-pf-props__title'); h.append(icon('form'), doc.createTextNode(` ${it.label}`)); host.appendChild(h);
      host.appendChild(el('p', 'gw-hint', `${TYPE_LABEL[it.type] || 'Campo'}. El nombre y el tipo se cambian en «Campos», arriba.`));

      const fg = el('div', 'gw-field'); fg.appendChild(el('label', 'gw-label', 'Grupo', { for: 'pfGroup' }));
      const sel2 = el('select', 'gw-select', null, { id: 'pfGroup', 'aria-label': `Grupo de ${it.label}` });
      m.sheets.forEach((s, i) => { const o = el('option', null, sheetName(s, i), { value: s.id }); if (s.id === it.sheet) o.selected = true; sel2.appendChild(o); });
      sel2.addEventListener('change', () => { if (sendToSheet(m, it.key, sel2.value)) { focusKey = it.key; changed(); } });
      fg.appendChild(sel2); host.appendChild(fg);

      const place = el('div', 'gw-row gw-pf-props__move');
      [['left', '◀', 'Mover a la izquierda'], ['right', '▶', 'Mover a la derecha'], ['up', '▲', 'Subir'], ['down', '▼', 'Bajar']].forEach(([d, g, t]) => {
        const b = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', g, { type: 'button', 'aria-label': `${t}: ${it.label}`, title: t });
        b.addEventListener('click', () => { if (moveKey(m, it.key, d)) { focusKey = it.key; changed(); } });
        place.appendChild(b);
      });
      host.appendChild(place);
      const sep = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Poner en su propia fila', { type: 'button' });
      sep.disabled = alone; sep.addEventListener('click', () => { if (separate(m, it.key)) { focusKey = it.key; changed(); } });
      host.appendChild(sep);

      const rq = el('input', null, null, { type: 'checkbox', id: 'pfReq', 'aria-label': `${it.label} obligatorio` }); rq.checked = !!it.required; rq.disabled = !it.canRequire;
      rq.addEventListener('change', () => { it.required = rq.checked; if (rq.checked) { it.showField = ''; it.showValue = ''; it.rawShowIf = null; } changed(); });
      const rl = el('label', 'gw-check gw-pf-props__check'); rl.append(rq, doc.createTextNode(' Obligatorio'));
      host.appendChild(rl);
      if (!it.canRequire) host.appendChild(el('p', 'gw-hint', ALWAYS_REQUIRED.includes(it.key) ? 'Este dato siempre es obligatorio.' : 'Este dato nunca se exige.'));

      const fc = el('div', 'gw-field'); fc.appendChild(el('label', 'gw-label', 'Texto al escribir', { for: 'pfCase' }));
      if (it.canCase) {
        const cs = el('select', 'gw-select', null, { id: 'pfCase', 'aria-label': `Texto al escribir de ${it.label}` });
        [['', 'Como lo escriban'], ['upper', 'MAYÚSCULAS'], ['lower', 'minúsculas']].forEach(([v, t]) => { const o = el('option', null, t, { value: v }); if (v === it.text_case) o.selected = true; cs.appendChild(o); });
        cs.addEventListener('change', () => { it.text_case = cs.value; changed(); });
        fc.appendChild(cs);
      } else fc.appendChild(el('span', 'gw-hint', it.key === 'email' ? 'Siempre minúsculas.' : 'No aplica a este campo.'));
      host.appendChild(fc);

      const fs = el('div', 'gw-field'); fs.appendChild(el('label', 'gw-label', 'Mostrar solo si', { for: 'pfShowField' }));
      if (it.required) fs.appendChild(el('span', 'gw-hint', 'Un campo obligatorio siempre se ve.'));
      else if (it.rawShowIf) fs.appendChild(el('span', 'gw-hint', 'Tiene una condición avanzada (se conserva tal cual).'));
      else {
        const sf = el('select', 'gw-select', null, { id: 'pfShowField', 'aria-label': `Mostrar ${it.label} solo si` });
        sf.appendChild(el('option', null, 'Siempre', { value: '' }));
        m.items.filter((o) => o.key !== it.key).forEach((o) => { const op = el('option', null, o.label, { value: o.key }); if (o.key === it.showField) op.selected = true; sf.appendChild(op); });
        const sv = el('input', 'gw-input', null, { type: 'text', maxlength: '200', placeholder: 'es igual a…', 'aria-label': `Valor para mostrar ${it.label}` }); sv.value = it.showValue; sv.disabled = !it.showField;
        sf.addEventListener('change', () => { it.showField = sf.value; sv.disabled = !sf.value; dirty(); });
        sv.addEventListener('input', () => { it.showValue = sv.value; dirty(); });
        fs.append(sf, sv);
      }
      host.appendChild(fs);
    }

    /* Vista previa: así se ve «Registrar nuevo» / «Editar» en el quiosco con este diseño (campos apagados). */
    function preview() {
      const m = state.model, rows = rowsOf(m), byKey = {}; m.items.forEach((it) => { byKey[it.key] = it; });
      const back = el('div', 'gw-modal-backdrop gw-pf-preview', null, { 'data-open': 'true', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Vista previa del formulario de persona' });
      const box = el('div', 'gw-modal'), headEl = el('div', 'gw-modal__head');
      const close = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Cerrar vista previa', { type: 'button', id: 'pfPreviewClose' });
      headEl.append(el('h3', 'gw-modal__title', 'Vista previa'), close);
      const body = el('div', 'gw-modal__body');
      body.appendChild(el('p', 'gw-hint', 'Así lo verá quien registre o edite una persona. Los campos están apagados en esta vista.'));
      m.sheets.forEach((s, si) => {
        const mine = rows.filter((r) => r.sheet === s.id); if (!mine.length) return;
        const hasRequired = m.items.some((it) => it.sheet === s.id && it.required);
        const d = el('details', 'gw-form-group'); if (s.open || hasRequired) d.open = true;
        if (s.title && s.title.trim()) d.appendChild(el('summary', 'gw-form-group__summary', s.title.trim()));
        const b = el('div', 'gw-form-group__body');
        mine.forEach((r) => {
          const rw = el('div', `gw-fields-row gw-fields-row--${r.keys.length}`);
          r.keys.forEach((k) => {
            const it = byKey[k]; if (!it) return;
            const f = el('div', 'gw-field'), lb = el('label', 'gw-label', it.label); if (it.required) lb.appendChild(el('span', 'gw-req', ' *', { 'aria-hidden': 'true' }));
            let ctl;
            if (it.type === 'text_long') ctl = el('textarea', 'gw-textarea', null, { rows: '2' });
            else if (['select', 'radio', 'categories'].includes(it.type)) { ctl = el('select', 'gw-select'); ctl.appendChild(el('option', null, 'Selecciona…')); }
            else if (it.type === 'checkbox') ctl = el('input', null, null, { type: 'checkbox' });
            else ctl = el('input', 'gw-input', null, { type: it.type === 'date' ? 'date' : 'text' });
            ctl.disabled = true; ctl.setAttribute('aria-label', it.label);
            f.append(lb, ctl);
            if (it.showField || it.rawShowIf) { const o = byKey[it.showField]; f.appendChild(el('span', 'gw-hint', it.rawShowIf ? 'Aparece según una condición.' : `Aparece solo si «${o ? o.label : it.showField}» es «${it.showValue}».`)); }
            rw.appendChild(f);
          });
          b.appendChild(rw);
        });
        d.appendChild(b); body.appendChild(d);
      });
      box.append(headEl, body); back.appendChild(box); doc.body.appendChild(back);
      const done = () => { back.remove(); doc.removeEventListener('keydown', onKey); };
      const onKey = (e) => { if (e.key === 'Escape') done(); };
      doc.addEventListener('keydown', onKey);
      close.addEventListener('click', done);
      back.addEventListener('click', (e) => { if (e.target === back) done(); });
      close.focus();
    }

    function render() {
      const m = state.model; container.textContent = ''; state.container = container;
      const status = el('p', 'gw-hint', `Versión del diseño: ${m.version}. Cada cambio sube la versión; los quioscos sin red usan la última que conocieron.`, { role: 'status' });
      const enabled = el('input', null, null, { type: 'checkbox', id: 'pfEnabled' }); enabled.checked = m.enabled;
      enabled.addEventListener('change', () => { m.enabled = enabled.checked; dirty(); });
      const enabledLabel = el('label', 'gw-check'); enabledLabel.append(enabled, doc.createTextNode(' Usar este formulario en el quiosco (Registrar nuevo y Editar) de este evento'));
      container.append(enabledLabel, status);

      const tools = el('div', 'gw-row gw-pf-tools');
      const pv = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', null, { type: 'button', id: 'pfPreview' }); pv.append(icon('eye'), doc.createTextNode(' Previsualizar'));
      pv.addEventListener('click', preview);
      const add = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', null, { type: 'button', id: 'pfAddGroup' }); add.append(icon('plus'), doc.createTextNode(' Agregar grupo'));
      add.addEventListener('click', () => { const s = addSheet(m); state.selected = { kind: 'sheet', id: s.id }; changed(); });
      tools.append(pv, add); container.appendChild(tools);

      const grid = el('div', 'gw-pf-grid');
      const canvas = el('div', 'gw-pf-canvas', null, { id: 'pfCanvas' });
      renderCanvas(canvas);
      canvas.appendChild(el('p', 'gw-hint gw-pf-canvas__hint', 'Arrastra un campo y suéltalo al lado de otro (misma fila, hasta 4) o en la franja entre filas (fila nueva). Con teclado: Enter para elegirlo y Alt + flechas para moverlo.'));
      const props = el('aside', 'gw-pf-props', null, { id: 'pfProps', 'aria-live': 'polite' });
      renderProps(props);
      grid.append(canvas, props); container.appendChild(grid);

      const actions = el('div', 'gw-row gw-row--end');
      const reset = el('button', 'gw-btn gw-btn--secondary', 'Volver al diseño por defecto', { type: 'button', id: 'pfReset' });
      const save = el('button', 'gw-btn gw-btn--primary', 'Guardar formulario', { type: 'button', id: 'pfSave' });
      reset.addEventListener('click', async () => {
        const ok = root.showConfirm ? await root.showConfirm('¿Volver al diseño por defecto? Se pierde la disposición actual (los obligatorios de los campos se conservan).', { variant: 'warning', confirmLabel: 'Sí, volver' }) : true;
        if (!ok) return;
        state.selected = null; await load(true); dirty();
      });
      save.addEventListener('click', async () => {
        if (gw) { await gw.saveKey('personform'); return; }
        save.disabled = true; save.setAttribute('aria-busy', 'true');
        try { await persist(); toast(`Formulario guardado (versión ${state.model.version}). Los quioscos lo toman al recargar o al volver la red.`, 'success'); }
        catch (e) { toast(e.message || 'Error de red', 'error'); } finally { save.disabled = false; save.removeAttribute('aria-busy'); }
      });
      if (gw) save.hidden = true;                    // con el Guardar global, el botón propio queda oculto (mismo guardado)
      actions.append(reset, save); container.appendChild(actions);
      if (focusKey) { const c = container.querySelector(`.gw-pf-card[data-key="${focusKey}"]`); focusKey = null; if (c && c.focus) { try { c.focus({ preventScroll: true }); } catch (e) { /* sin foco */ } } }
    }

    // Guarda el diseño (PUT). Lanza Error(mensaje) si falla; no avisa por su cuenta (lo hace el Guardar global o el botón propio).
    async function persist() {
      let res, data;
      try {
        res = await fetchFn(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fromModel(state.model)) });
        data = await res.json().catch(() => ({}));
      } catch (e) { throw new Error('Error de red'); }
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo guardar el formulario');
      state.model = toModel(data); render();
    }
    if (gw) gw.register({ key: 'personform', label: 'Formulario de persona', order: 85, save: async () => { if (state.loaded) await persist(); } });

    async function load(defaults) {
      try {
        const res = await fetchFn(url, { cache: 'no-store' });
        const view = await res.json();
        if (!view.env_enabled) { container.textContent = 'El formulario de persona no está habilitado en este entorno.'; return; }
        if (defaults) view.definition = null;          // el servidor arma el diseño por defecto al guardar con filas vacías
        state.model = defaults ? defaultModel(view, state.model) : toModel(view); state.loaded = true; render();
      } catch (e) { container.textContent = 'No se pudo cargar el formulario de persona.'; }
    }
    // Diseño por defecto en el cliente (mismo criterio que app/personform.py::default_design): identidad y obligatorios en el grupo abierto; el resto en «Más datos».
    function defaultModel(view, prev) {
      const cfgs = view.fields || [], top = ['id', 'first_name', 'last_name'].filter((k) => cfgs.some((c) => c.key === k));
      cfgs.forEach((c) => { if (c.required && !top.includes(c.key)) top.push(c.key); });
      const rest = cfgs.map((c) => c.key).filter((k) => !top.includes(k));
      const sheets = [{ id: 'datos', title: 'Datos principales', open: true }];
      if (rest.length) sheets.push({ id: 'mas', title: 'Más datos', open: false });
      const mk = (key, sheet, joined) => { const c = cfgs.find((x) => x.key === key); return { key, label: c.label, type: c.field_type || 'text_short', sheet, joined, required: ALWAYS_REQUIRED.includes(key) || !!c.required, canRequire: !ALWAYS_REQUIRED.includes(key) && !NEVER_REQUIRED.includes(key), canCase: canCase(c), text_case: '', showField: '', showValue: '', rawShowIf: null }; };
      const items = [];
      top.forEach((k, i) => items.push(mk(k, 'datos', k === 'last_name' && top[i - 1] === 'first_name')));
      rest.forEach((k, i) => items.push(mk(k, 'mas', i % 2 === 1)));
      return { enabled: prev ? prev.enabled : false, version: prev ? prev.version : 1, sheets, items };
    }
    load(false);
    return { state, render, load, preview };
  }

  const api = { toModel, fromModel, move, addSheet, removeSheet, mount, canCase, rowsOf, dropAt, moveKey, separate, sendToSheet };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PersonFormDesigner = api;
})(typeof window !== 'undefined' ? window : globalThis);
