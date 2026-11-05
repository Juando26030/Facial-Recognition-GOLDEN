/* Diseñador del FORMULARIO DE PERSONA (Parámetros del evento, solo admin+; app/personform.py). Edita la misma definición que usa el quiosco: grupos (sheets), filas con hasta 4 columnas (rows), obligatorio,
   «Texto al escribir» y una condición simple «mostrar solo si» (show_if). Lo más simple que reutiliza lo que ya existe: la lista de campos del evento (Parámetros) con sus nombres y tipos; aquí solo se
   decide DÓNDE va cada uno y cómo se escribe. Lo obligatorio se guarda en los parámetros del evento (una sola fuente de verdad). Funciones puras (toModel / fromModel / move) probadas en Node; la pantalla
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
          key, label: cfg.label, sheet: sheets.some((s) => s.id === row.sheet) ? row.sheet : sheets[0].id, joined: i > 0,
          required: ALWAYS_REQUIRED.includes(key) ? true : (NEVER_REQUIRED.includes(key) ? false : !!(f.required != null ? f.required : cfg.required)),
          canRequire: !ALWAYS_REQUIRED.includes(key) && !NEVER_REQUIRED.includes(key), canCase: canCase(cfg), text_case: f.text_case || '',
          showField: simpleCond(cond) ? cond.field : '', showValue: simpleCond(cond) ? String(cond.value == null ? '' : cond.value) : '', rawShowIf: cond && !simpleCond(cond) ? cond : null,
        });
      });
    });
    cfgs.forEach((cfg) => { if (!seen.has(cfg.key)) items.push({ key: cfg.key, label: cfg.label, sheet: sheets[sheets.length - 1].id, joined: false, required: !!cfg.required, canRequire: !ALWAYS_REQUIRED.includes(cfg.key) && !NEVER_REQUIRED.includes(cfg.key), canCase: canCase(cfg), text_case: '', showField: '', showValue: '', rawShowIf: null }); });
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

  /* ------------------------------------------------------------------------------------------------ pantalla */
  function mount(container, opts) {
    const doc = container.ownerDocument || root.document;
    const toast = opts.toast || root.showToast || (() => {});
    const eventId = opts.eventId, fetchFn = opts.fetch || root.fetch.bind(root);
    const el = (tag, cls, text, attrs) => { const n = doc.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; Object.keys(attrs || {}).forEach((k) => n.setAttribute(k, attrs[k])); return n; };
    const state = { model: null, loaded: false };
    // Guardado global de Parámetros (static/js/params-save.js): si existe, este bloque se registra como «personform» y el botón «Guardar» global lo guarda; si no, el botón propio guarda con su toast.
    const gw = opts.params || root.GWParams || null;
    const dirty = () => { if (gw) gw.markDirty('personform'); };
    const url = `/api/events/${eventId}/person-form`;

    function render() {
      const m = state.model; container.textContent = '';
      const status = el('p', 'gw-hint', `Versión del diseño: ${m.version}. Cada cambio sube la versión; los quioscos sin red usan la última que conocieron.`, { role: 'status' });
      const enabled = el('input', null, null, { type: 'checkbox', id: 'pfEnabled' }); enabled.checked = m.enabled;
      enabled.addEventListener('change', () => { m.enabled = enabled.checked; });
      const enabledLabel = el('label', 'gw-check'); enabledLabel.append(enabled, doc.createTextNode(' Usar este formulario en el quiosco (Registrar nuevo y Editar) de este evento'));
      container.append(enabledLabel, status);

      // Grupos
      const groups = el('div', 'gw-stack');
      groups.appendChild(el('h4', 'gw-subtitle', 'Grupos'));
      m.sheets.forEach((s) => {
        const hasRequired = m.items.some((it) => it.sheet === s.id && it.required);
        const row = el('div', 'gw-row');
        const title = el('input', 'gw-input', null, { type: 'text', maxlength: '60', 'aria-label': 'Nombre del grupo' }); title.value = s.title;
        title.addEventListener('input', () => { s.title = title.value; });
        const open = el('input', null, null, { type: 'checkbox' }); open.checked = s.open || hasRequired; open.disabled = hasRequired;
        open.addEventListener('change', () => { s.open = open.checked; });
        const openLabel = el('label', 'gw-check'); openLabel.append(open, doc.createTextNode(hasRequired ? ' Abierto (lleva obligatorios)' : ' Abierto al empezar'));
        const del = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Quitar', { type: 'button' });
        del.disabled = m.sheets.length < 2;
        del.addEventListener('click', () => { removeSheet(m, s.id); dirty(); render(); });
        row.append(title, openLabel, del); groups.appendChild(row);
      });
      const add = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Agregar grupo', { type: 'button' });
      add.addEventListener('click', () => { addSheet(m); dirty(); render(); });
      groups.appendChild(add);
      container.appendChild(groups);

      // Campos
      const wrap = el('div', 'gw-table-wrap gw-scroll-x');
      const table = el('table', 'gw-table');
      const head = el('tr'); ['Campo', 'Grupo', 'Fila', 'Obligatorio', 'Texto al escribir', 'Mostrar solo si', 'Orden'].forEach((h) => head.appendChild(el('th', null, h)));
      const thead = el('thead'); thead.appendChild(head); table.appendChild(thead);
      const tbody = el('tbody');
      const items = sortBySheet(m.items, m.sheets);
      items.forEach((it, i) => {
        const tr = el('tr', null, null, { 'data-key': it.key });
        tr.appendChild(el('td', null, it.label));
        const sel = el('select', 'gw-select', null, { 'aria-label': `Grupo de ${it.label}` });
        m.sheets.forEach((s) => { const o = el('option', null, s.title || s.id, { value: s.id }); if (s.id === it.sheet) o.selected = true; sel.appendChild(o); });
        sel.addEventListener('change', () => { it.sheet = sel.value; it.joined = false; render(); });
        const td2 = el('td'); td2.appendChild(sel); tr.appendChild(td2);
        const prev = items[i - 1];
        const joined = el('input', null, null, { type: 'checkbox' }); joined.checked = !!(it.joined && prev && prev.sheet === it.sheet); joined.disabled = !prev || prev.sheet !== it.sheet;
        joined.addEventListener('change', () => { it.joined = joined.checked; });
        const jl = el('label', 'gw-check'); jl.append(joined, doc.createTextNode(' Junto al anterior'));
        const td3 = el('td'); td3.appendChild(jl); tr.appendChild(td3);
        const req = el('input', null, null, { type: 'checkbox', 'aria-label': `${it.label} obligatorio` }); req.checked = !!it.required; req.disabled = !it.canRequire;
        req.addEventListener('change', () => { it.required = req.checked; if (req.checked) { it.showField = ''; it.showValue = ''; it.rawShowIf = null; } render(); });
        const td4 = el('td'); td4.appendChild(req); tr.appendChild(td4);
        const td5 = el('td');
        if (it.canCase) {
          const cs = el('select', 'gw-select', null, { 'aria-label': `Texto al escribir de ${it.label}` });
          [['', 'Como lo escriban'], ['upper', 'MAYÚSCULAS'], ['lower', 'minúsculas']].forEach(([v, t]) => { const o = el('option', null, t, { value: v }); if (v === it.text_case) o.selected = true; cs.appendChild(o); });
          cs.addEventListener('change', () => { it.text_case = cs.value; });
          td5.appendChild(cs);
        } else td5.appendChild(el('span', 'gw-hint', it.key === 'email' ? 'Siempre minúsculas' : '—'));
        tr.appendChild(td5);
        const td6 = el('td');
        if (it.required) td6.appendChild(el('span', 'gw-hint', 'Un obligatorio siempre se ve'));
        else if (it.rawShowIf) td6.appendChild(el('span', 'gw-hint', 'Condición avanzada (se conserva)'));
        else {
          const sf = el('select', 'gw-select', null, { 'aria-label': `Mostrar ${it.label} solo si` });
          sf.appendChild(el('option', null, 'Siempre', { value: '' }));
          items.filter((o) => o.key !== it.key).forEach((o) => { const op = el('option', null, o.label, { value: o.key }); if (o.key === it.showField) op.selected = true; sf.appendChild(op); });
          const sv = el('input', 'gw-input', null, { type: 'text', maxlength: '200', placeholder: 'es igual a…', 'aria-label': `Valor para mostrar ${it.label}` }); sv.value = it.showValue; sv.disabled = !it.showField;
          sf.addEventListener('change', () => { it.showField = sf.value; sv.disabled = !sf.value; });
          sv.addEventListener('input', () => { it.showValue = sv.value; });
          td6.append(sf, sv);
        }
        tr.appendChild(td6);
        const td7 = el('td');
        const up = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', '▲', { type: 'button', 'aria-label': `Subir ${it.label}` }), down = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', '▼', { type: 'button', 'aria-label': `Bajar ${it.label}` });
        up.addEventListener('click', () => { if (move(m, it.key, -1)) { dirty(); render(); } });
        down.addEventListener('click', () => { if (move(m, it.key, 1)) { dirty(); render(); } });
        td7.append(up, down); tr.appendChild(td7);
        tbody.appendChild(tr);
      });
      table.appendChild(tbody); wrap.appendChild(table); container.appendChild(wrap);

      const actions = el('div', 'gw-row gw-row--end');
      const reset = el('button', 'gw-btn gw-btn--secondary', 'Volver al diseño por defecto', { type: 'button', id: 'pfReset' });
      const save = el('button', 'gw-btn gw-btn--primary', 'Guardar formulario', { type: 'button', id: 'pfSave' });
      reset.addEventListener('click', async () => {
        const ok = root.showConfirm ? await root.showConfirm('¿Volver al diseño por defecto? Se pierde la disposición actual (los obligatorios de los campos se conservan).', { variant: 'warning', confirmLabel: 'Sí, volver' }) : true;
        if (!ok) return;
        await load(true); dirty();
      });
      save.addEventListener('click', async () => {
        if (gw) { await gw.saveKey('personform'); return; }
        save.disabled = true; save.setAttribute('aria-busy', 'true');
        try { await persist(); toast(`Formulario guardado (versión ${state.model.version}). Los quioscos lo toman al recargar o al volver la red.`, 'success'); }
        catch (e) { toast(e.message || 'Error de red', 'error'); } finally { save.disabled = false; save.removeAttribute('aria-busy'); }
      });
      if (gw) save.hidden = true;                    // con el Guardar global, el botón propio queda oculto (mismo guardado)
      actions.append(reset, save); container.appendChild(actions);
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
      const mk = (key, sheet, joined) => { const c = cfgs.find((x) => x.key === key); return { key, label: c.label, sheet, joined, required: ALWAYS_REQUIRED.includes(key) || !!c.required, canRequire: !ALWAYS_REQUIRED.includes(key) && !NEVER_REQUIRED.includes(key), canCase: canCase(c), text_case: '', showField: '', showValue: '', rawShowIf: null }; };
      const items = [];
      top.forEach((k, i) => items.push(mk(k, 'datos', k === 'last_name' && top[i - 1] === 'first_name')));
      rest.forEach((k, i) => items.push(mk(k, 'mas', i % 2 === 1)));
      return { enabled: prev ? prev.enabled : false, version: prev ? prev.version : 1, sheets, items };
    }
    load(false);
    return { state, render, load };
  }

  const api = { toModel, fromModel, move, addSheet, removeSheet, mount, canCase };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PersonFormDesigner = api;
})(typeof window !== 'undefined' ? window : globalThis);
