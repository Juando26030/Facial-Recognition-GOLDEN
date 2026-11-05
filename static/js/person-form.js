/* Formulario de PERSONA diseñado por el admin (Fase 1A, pieza 5; app/personform.py). Reutiliza el motor de los formularios web sin su parte pública:
   - La DISPOSICIÓN (grupos = `sheets`, filas con hasta 4 columnas = `rows`, `show_if`) viene en la definición. Los CAMPOS no se dibujan aquí: ya están en la página (el alta, que trae el servidor) o los arma
     el modal de Editar (directory.js); `mount` solo MUEVE esos nodos (`[data-field-key]`) a sus grupos y filas, así no se pierde ningún `name`, `id` ni oyente de los demás scripts.
   - «Texto al escribir» (MAYÚSCULAS / minúsculas) se aplica MIENTRAS se escribe (nunca a cédula, teléfono ni fecha: solo a los campos que la definición marca) y el servidor lo repite al guardar.
   - Obligatorios a la vista: lo obligatorio se marca con `*` y `required`; un grupo cerrado se abre solo si tiene un campo inválido. Apellidos nunca se exigen.
   - `show_if` usa FormRender.computeVisible (static/js/form-render.js, el mismo motor del formulario web): un campo oculto no se envía y no se exige.
   - VERSIONADA: la definición trae `form_version` y `form_sig`; `pick` elige la más nueva entre la que vino con la página y la guardada en IndexedDB (contingency.js), para que alta y edición sin red usen
     la última que el dispositivo conoció. La bandeja (outbox.js) manda esa versión con cada alta o edición. Sin definición, este archivo no hace nada. */
(function (root) {
  const CASE = { upper: (s) => s.toUpperCase(), lower: (s) => s.toLowerCase() };
  const TEXT_INPUT_TYPES = ['text', 'search', ''];
  const ALWAYS_REQUIRED = ['id', 'first_name'], NEVER_REQUIRED = ['last_name'];

  const convert = (value, mode) => (typeof value === 'string' && CASE[mode] ? CASE[mode](value) : value);
  const NEVER_CASE = ['id', 'phone', 'email', 'birth_date'];          // nunca se convierten (cédula, teléfono, correo —siempre minúsculas en el servidor— y fecha), aunque una definición lo pidiera
  const rulesOf = (def) => { const out = {}; Object.keys((def && def.fields) || {}).forEach((k) => { const m = def.fields[k].text_case; if (CASE[m] && !NEVER_CASE.includes(k)) out[k] = m; }); return out; };

  /* Igual que app/personform.py::apply_case: convierte EN EL LUGAR los textos de `values` (y de `values.extra_fields`) y deja el correo en minúsculas. Devuelve `values`. */
  function applyCase(values, def) {
    if (!def || !values) return values;
    const rules = rulesOf(def);
    Object.keys(rules).forEach((k) => {
      if (k.startsWith('opcional_')) { if (values.extra_fields && typeof values.extra_fields[k] === 'string') values.extra_fields[k] = convert(values.extra_fields[k], rules[k]); }
      else if (typeof values[k] === 'string') values[k] = convert(values[k], rules[k]);
    });
    if (typeof values.email === 'string' && values.email) values.email = values.email.trim().toLowerCase();
    return values;
  }

  const version = (def) => (def && Number.isFinite(Number(def.form_version)) ? Number(def.form_version) : 0);
  /* La más nueva de dos definiciones (la inyectada en la página y la guardada en el dispositivo); a igual versión, la primera. */
  function pick(a, b) { if (!a) return b || null; if (!b) return a; return version(b) > version(a) ? b : a; }

  function requiredOf(def, key) {
    if (ALWAYS_REQUIRED.includes(key)) return true;
    if (NEVER_REQUIRED.includes(key)) return false;
    return !!(def && def.fields && def.fields[key] && def.fields[key].required);
  }

  function el(doc, tag, cls, text) { const n = doc.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }

  function markRequired(node, key, required) {
    const label = node.querySelector('label');
    if (label && label.children.length === 0) label.textContent = label.textContent.replace(/\s*\*\s*$/, '') + (required ? ' *' : '');
    node.querySelectorAll('input, select, textarea').forEach((c) => {
      if (c.name !== key || ['checkbox', 'radio', 'file', 'hidden', 'submit', 'button'].includes(c.type)) return;
      if (c.getAttribute('data-pf-hidden')) return;           // oculto por una condición: no se exige
      if (required) c.setAttribute('required', ''); else c.removeAttribute('required');
    });
  }

  /* Dibuja la disposición dentro de `container` (que solo contiene los nodos de campo). `opts.disableKeys`: claves que no se pueden editar en este modo (p. ej. sin red) y el motivo en `opts.disabledHint`.
     Devuelve el controlador {def, relayout(def), applyAll(), refresh(), destroy()}. */
  function mount(container, def, opts) {
    opts = opts || {};
    const doc = container.ownerDocument || root.document;
    const ctl = { def: null };
    let rules = {};

    function collect() {
      const map = {};
      container.querySelectorAll('[data-field-key]').forEach((n) => { map[n.getAttribute('data-field-key')] = n; });
      return map;
    }

    function layout(newDef) {
      ctl.def = newDef; rules = rulesOf(newDef);
      const nodes = collect();
      const sheets = (newDef.sheets && newDef.sheets.length) ? newDef.sheets : [{ id: 'datos', title: '', open: true }];
      const sheetIds = sheets.map((s) => s.id), placed = new Set();
      const rows = [];
      (newDef.rows || []).forEach((r) => {
        const items = (r.items || []).filter((k) => nodes[k] && !placed.has(k));
        if (!items.length) return;
        items.forEach((k) => placed.add(k));
        rows.push({ sheet: sheetIds.includes(r.sheet) ? r.sheet : sheetIds[0], items });
      });
      Object.keys(nodes).forEach((k) => { if (!placed.has(k)) rows.push({ sheet: sheetIds[sheetIds.length - 1], items: [k] }); });      // un campo que la definición no conoce nunca se pierde: va al final
      const frag = doc.createDocumentFragment();
      sheets.forEach((sheet) => {
        const mine = rows.filter((r) => r.sheet === sheet.id);
        if (!mine.length) return;
        const needs = mine.some((r) => r.items.some((k) => requiredOf(newDef, k)));
        const group = el(doc, 'details', 'gw-form-group'); group.setAttribute('data-group', sheet.id);
        if (sheet.open !== false || needs) group.open = true;
        if (sheet.title) group.appendChild(el(doc, 'summary', 'gw-form-group__summary', sheet.title));
        const body = el(doc, 'div', 'gw-form-group__body');
        mine.forEach((r) => {
          const row = el(doc, 'div', `gw-fields-row gw-fields-row--${Math.min(r.items.length, 4)}`);
          r.items.forEach((k) => row.appendChild(nodes[k]));
          body.appendChild(row);
        });
        group.appendChild(body); frag.appendChild(group);
      });
      while (container.firstChild) container.removeChild(container.firstChild);          // los nodos de campo ya están en el fragmento (se movieron)
      container.appendChild(frag);
      Object.keys(nodes).forEach((k) => markRequired(nodes[k], k, requiredOf(newDef, k)));
      (opts.disableKeys || []).forEach((k) => {
        const n = nodes[k]; if (!n) return;
        n.querySelectorAll('input, select, textarea, button').forEach((c) => { c.disabled = true; });
        if (!n.querySelector('.gw-hint')) n.appendChild(el(doc, 'p', 'gw-hint', opts.disabledHint || 'Requiere conexión'));
      });
      ctl.refresh();
    }

    function readValues(nodes) {
      const values = {};
      Object.keys(nodes).forEach((k) => {
        nodes[k].querySelectorAll('[name]').forEach((c) => {
          if (['checkbox', 'radio'].includes(c.type)) { if (c.checked) values[c.name] = [].concat(values[c.name] || [], c.value); return; }
          if (c.type === 'file') return;
          values[c.name] = c.value;
        });
      });
      return values;
    }

    /* Muestra u oculta los campos con `show_if`. Un campo oculto queda deshabilitado (no viaja ni se exige) y vuelve a habilitarse al mostrarse. */
    ctl.refresh = () => {
      const d = ctl.def; if (!d) return;
      const withRules = Object.keys(d.fields || {}).filter((k) => d.fields[k].show_if);
      if (!withRules.length || !(root.FormRender && root.FormRender.computeVisible)) return;
      const nodes = collect();
      const design = { fields: {}, rows: [], sheets: [] };
      Object.keys(nodes).forEach((k) => { design.fields[k] = { show_if: (d.fields[k] || {}).show_if || null }; });
      const visible = root.FormRender.computeVisible(design, readValues(nodes), Object.keys(nodes));
      Object.keys(nodes).forEach((k) => {
        if (!(d.fields[k] && d.fields[k].show_if)) return;
        const show = visible.has(k), n = nodes[k];
        n.hidden = !show;
        n.querySelectorAll('input, select, textarea').forEach((c) => {
          if (!show) { if (!c.disabled) { c.disabled = true; c.setAttribute('data-pf-hidden', '1'); } }
          else if (c.getAttribute('data-pf-hidden')) { c.disabled = false; c.removeAttribute('data-pf-hidden'); }
        });
      });
    };

    function convertInput(c) {
      const mode = rules[c.name]; if (!mode) return false;
      if (c.tagName !== 'TEXTAREA' && !(c.tagName === 'INPUT' && TEXT_INPUT_TYPES.includes(c.type))) return false;
      const v = c.value, nv = convert(v, mode);
      if (nv === v) return false;
      const a = c.selectionStart, b = c.selectionEnd;
      c.value = nv;
      try { if (a != null) c.setSelectionRange(a, b); } catch (e) { /* sin selección */ }
      return true;
    }
    const onInput = (e) => { if (e.isComposing) return; if (e.target && e.target.name) convertInput(e.target); ctl.refresh(); };
    const onBlur = (e) => { if (e.target && e.target.name) convertInput(e.target); };
    const onInvalid = (e) => { const g = e.target && e.target.closest && e.target.closest('details'); if (g && !g.open) g.open = true; };          // un campo inválido dentro de un grupo cerrado: se abre
    container.addEventListener('input', onInput);
    container.addEventListener('change', () => ctl.refresh());
    container.addEventListener('focusout', onBlur);
    container.addEventListener('invalid', onInvalid, true);

    /* Convierte ya todo lo escrito (antes de guardar o encolar): por si un campo se llenó por código (lector, MRZ) y no por teclado. */
    ctl.applyAll = () => { container.querySelectorAll('input[name], textarea[name]').forEach(convertInput); };
    ctl.relayout = layout;
    ctl.destroy = () => { container.removeEventListener('input', onInput); container.removeEventListener('focusout', onBlur); container.removeEventListener('invalid', onInvalid, true); };
    layout(def);
    return ctl;
  }

  /* Pone de acuerdo la definición de la página con la guardada en el dispositivo (contingency.js): si la guardada es MÁS NUEVA se usa esa (página en caché de un día anterior sin red); si la de la página es
     más nueva o no hay guardada, se guarda la de la página. `GC` puede ser null (sin soporte de almacenamiento). Devuelve la definición que quedó vigente. */
  async function sync(GC, injected) {
    let stored = null;
    try { stored = GC && GC.personForm ? await GC.personForm() : null; } catch (e) { stored = null; }
    const chosen = pick(injected, stored);
    if (chosen && chosen !== stored && GC && GC.savePersonForm) { try { await GC.savePersonForm(chosen); } catch (e) { /* sin almacenamiento: se usa la de la página */ } }
    return chosen;
  }

  const api = { mount, sync, pick, convert, applyCase, rulesOf, requiredOf, version, current: null };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PersonForm = api;
})(typeof window !== 'undefined' ? window : globalThis);
