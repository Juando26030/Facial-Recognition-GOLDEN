/* Widget «campo de inventario» de la plantilla de evento (Fase 2, entrega 4). Se enchufa en el gancho data-evf-enhance="inventory" de static/js/event-field-render.js:
       if (window.GWInventory) GWInventory.enhance(el, opts)      // opts: { field | fields{clave: campo}, value }
   Cómo se usa: el cliente pide «dos computadores, tres impresoras, cuatro digitadores…». El administrador define en la plantilla los TIPOS (config.inventory_types:
   [{key,label,refs[]}]); aquí se elige cuáles pidió el cliente y por cada uno se agregan líneas: cantidad (entero 1..100000) y referencia (lista desplegable si el tipo
   tiene referencias; texto libre opcional si no).
   Formato guardado (igual que la entrega 2 y que valida app/event_inventory.py): [{type, qty, ref|null}] o null si no hay líneas.
   API:  GWInventory.parse(value) -> {lines}   .serialize(state) -> lista|null   .summary(value, def) -> «Computadores ×2 — Dell; Impresoras ×3»
         .validate(value, def) -> [mensajes] (vacío = bien)   .enhance(el, opts) -> controlador {getValue, setValue, validate, summary}
   Emite «gw:inventory-change» (burbujea) con detail {key, value, summary, errors}.
   Los controles conservan data-evf-key/data-evf-part (type/qty/ref), así EventFields.readField sigue leyendo el campo sin cambios.
   Todo texto del administrador se ESCAPA. Enlace con el módulo operativo de Inventario (kiosk_inventario): pendiente de la Fase 5. */
(function (root) {
  'use strict';
  var MAX_LINES = 100, MAX_QTY = 100000, MAX_REF = 80;
  var esc = function (t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var BAD = /[<>\u0000-\u001f\u007f]/;

  /* ------------------------------------------------------------------------------------------------ lógica pura */
  function typesOf(def) {
    var raw = Array.isArray(def) ? def : def && (def.inventory_types || (def.config && def.config.inventory_types)) || [];
    return raw.filter(function (t) { return t && typeof t.key === 'string'; }).map(function (t) { return { key: t.key, label: String(t.label || t.key), refs: Array.isArray(t.refs) ? t.refs.map(String) : [] }; });
  }
  function typeByKey(types, key) { for (var i = 0; i < types.length; i++) if (types[i].key === key) return types[i]; return null; }
  function toInt(v) {                                   // entero estricto (acepta "5" y 5; rechaza "", "2.5", "abc")
    if (typeof v === 'number') return isFinite(v) && v % 1 === 0 ? v : null;
    var s = String(v == null ? '' : v).trim();
    return /^-?\d+$/.test(s) ? parseInt(s, 10) : null;
  }
  function parse(value) {
    var v = value;
    if (typeof v === 'string') { try { v = JSON.parse(v); } catch (e) { v = null; } }
    if (v && !Array.isArray(v) && Array.isArray(v.lines)) v = v.lines;
    var lines = (Array.isArray(v) ? v : []).filter(function (l) { return l && typeof l === 'object' && typeof l.type === 'string'; }).map(function (l) {
      var r = l.ref == null ? '' : String(l.ref).trim();
      return { type: l.type, qty: toInt(l.qty), ref: r || null };
    });
    return { lines: lines };
  }
  function linesOf(value) { return parse(value).lines; }
  function serialize(state) {
    var out = [];
    ((state && state.lines) || []).forEach(function (l) {
      if (!l || !l.type) return;
      var q = toInt(l.qty);
      if (q == null || q < 1) return;                  // la línea sin cantidad todavía no es un dato
      var r = l.ref == null ? '' : String(l.ref).trim();
      out.push({ type: l.type, qty: q, ref: r || null });
    });
    return out.length ? out : null;
  }
  function summary(value, def) {
    var types = typesOf(def);
    return linesOf(value).filter(function (l) { return toInt(l.qty) != null; }).map(function (l) {
      var t = typeByKey(types, l.type);
      return (t ? t.label : l.type) + ' ×' + l.qty + (l.ref ? ' — ' + l.ref : '');
    }).join('; ');
  }
  /* Un mensaje (o '') por línea, en el mismo orden. Mismas reglas que app/event_inventory.py. */
  function lineErrors(value, def) {
    var types = typesOf(def), lines = linesOf(value), seen = {};
    return lines.map(function (l) {
      var t = typeByKey(types, l.type);
      if (!t) return 'Este tipo de inventario ya no existe en la plantilla';
      var q = l.qty;
      if (q == null) return 'Escribe la cantidad (un número entero)';
      if (q < 1) return 'La cantidad mínima es 1';
      if (q > MAX_QTY) return 'La cantidad máxima es ' + MAX_QTY;
      if (t.refs.length) {
        if (!l.ref) return 'Elige la referencia de la lista';
        if (t.refs.indexOf(l.ref) < 0) return 'Esa referencia ya no está en la lista';
      } else if (l.ref) {
        if (l.ref.length > MAX_REF) return 'La referencia admite hasta ' + MAX_REF + ' caracteres';
        if (BAD.test(l.ref)) return 'La referencia no puede incluir «<», «>» ni caracteres de control';
      }
      var sig = l.type + '\u0000' + (l.ref || '').toLowerCase();
      if (seen[sig]) return 'Está repetido: suma las cantidades en una sola línea';
      seen[sig] = 1;
      return '';
    });
  }
  function validate(value, def) {
    var lines = linesOf(value), out = [];
    if (lines.length > MAX_LINES) out.push('Se admiten hasta ' + MAX_LINES + ' líneas');
    var types = typesOf(def);
    lineErrors(lines, def).forEach(function (m, i) {
      if (m) { var t = typeByKey(types, lines[i].type); out.push((t ? t.label : 'Línea ' + (i + 1)) + ': ' + m); }
    });
    return out;
  }
  /* Agrega una línea del tipo (cantidad 1). Con referencias: la primera que no esté usada; null si ya se usaron todas. Devuelve {lines, index} o null. */
  function addLine(lines, def, typeKey) {
    var types = typesOf(def), t = typeByKey(types, typeKey);
    if (!t || lines.length >= MAX_LINES) return null;
    var ref = null;
    if (t.refs.length) {
      var used = {}; lines.forEach(function (l) { if (l.type === typeKey && l.ref) used[l.ref] = 1; });
      if (t.refs.every(function (r) { return used[r]; })) return null;
    }
    var next = lines.concat([{ type: typeKey, qty: 1, ref: ref }]);
    return { lines: next, index: next.length - 1 };
  }
  /* Ordena por tipo (orden de la definición) sin alterar el orden dentro de cada tipo: lo que se ve en pantalla es lo que se guarda. */
  function sortLines(lines, def) {
    var order = {}; typesOf(def).forEach(function (t, i) { order[t.key] = i; });
    return lines.map(function (l, i) { return { l: l, i: i, o: order[l.type] == null ? 9999 : order[l.type] }; }).sort(function (a, b) { return a.o - b.o || a.i - b.i; }).map(function (x) { return x.l; });
  }
  function lastIndexOfType(lines, typeKey) { for (var i = lines.length - 1; i >= 0; i--) if (lines[i].type === typeKey) return i; return -1; }
  function removeLine(lines, index) { return lines.filter(function (_, i) { return i !== index; }); }
  function removeType(lines, typeKey) { return lines.filter(function (l) { return l.type !== typeKey; }); }
  /* Líneas ordenadas por tipo (el orden de la definición) conservando el orden dentro de cada tipo: así la pantalla y lo guardado coinciden. */
  function grouped(lines, def) {
    var types = typesOf(def), out = [];
    types.forEach(function (t) { var ls = []; lines.forEach(function (l, i) { if (l.type === t.key) ls.push({ line: l, index: i }); }); if (ls.length) out.push({ type: t, items: ls }); });
    var unknown = []; lines.forEach(function (l, i) { if (!typeByKey(types, l.type)) unknown.push({ line: l, index: i }); });
    if (unknown.length) out.push({ type: { key: '', label: 'Tipo que ya no existe', refs: [] }, items: unknown });
    return out;
  }

  /* ------------------------------------------------------------------------------------------------ pantalla (solo navegador) */
  var uid = 0;
  function enhance(el, opts) {
    opts = opts || {};
    if (!el || el.dataset.gwiReady) return el && el._gwInventory || null;
    var keyEl = el.querySelector('[data-evf-for],[data-evf-key]');
    var key = (keyEl && (keyEl.getAttribute('data-evf-for') || keyEl.getAttribute('data-evf-key'))) || (opts.field && opts.field.key) || '';
    var field = opts.field || (opts.fields && opts.fields[key]) || null;
    if (!field) return null;
    if (!key) key = field.key;
    var types = typesOf(field), title = field.title || 'Inventario', id = 'gwi' + (++uid);
    var state = { lines: parse(opts.value !== undefined ? opts.value : readExisting(el)).lines };
    var touched = {}, focusNext = null;
    state.lines = sortLines(state.lines, field);

    function readExisting(box) {                       // filas pintadas por event-field-render (inventoryRow): se conserva lo que ya traían
      var rows = box.querySelectorAll('[data-evf-line]'), out = [];
      Array.prototype.forEach.call(rows, function (r) {
        var g = function (p) { var c = r.querySelector('[data-evf-part="' + p + '"]'); return c ? c.value : ''; };
        if (g('type')) out.push({ type: g('type'), qty: g('qty'), ref: g('ref') });
      });
      return out;
    }
    function emit() {
      var value = serialize(state), errs = validate(state.lines, field);
      el.dispatchEvent(new CustomEvent('gw:inventory-change', { bubbles: true, detail: { key: key, value: value, summary: summary(state.lines, field), errors: errs } }));
    }
    function attrs(part) { return ' data-evf-key="' + esc(key) + '" data-evf-part="' + part + '"'; }
    function lineHtml(t, it, n) {
      var l = it.line, lid = id + '_' + it.index, err = touched[it.index] ? lineErrors(state.lines, field)[it.index] : '';
      var ref;
      if (t.refs.length) {
        var opts2 = '<option value="">Elige la referencia…</option>' + t.refs.map(function (r) { return '<option value="' + esc(r) + '"' + (l.ref === r ? ' selected' : '') + '>' + esc(r) + '</option>'; }).join('');
        if (l.ref && t.refs.indexOf(l.ref) < 0) opts2 += '<option value="' + esc(l.ref) + '" selected>' + esc(l.ref) + ' (ya no está en la lista)</option>';
        ref = '<select class="gw-select" id="' + lid + '_r"' + attrs('ref') + ' data-gwi-i="' + it.index + '" data-gwi-f="ref">' + opts2 + '</select>';
      } else {
        ref = '<input class="gw-input" type="text" id="' + lid + '_r" maxlength="' + MAX_REF + '" autocomplete="off"' + attrs('ref') + ' data-gwi-i="' + it.index + '" data-gwi-f="ref" value="' + esc(l.ref || '') + '" placeholder="Nombre o referencia (opcional)">';
      }
      return '<div class="gw-inv__line" data-gwi-line="' + it.index + '">' +
        '<input type="hidden"' + attrs('type') + ' value="' + esc(l.type) + '">' +
        '<div class="gw-field"><label class="gw-label" for="' + lid + '_q">Cantidad</label><input class="gw-input" type="number" inputmode="numeric" min="1" max="' + MAX_QTY + '" step="1" id="' + lid + '_q"' + attrs('qty') + ' data-gwi-i="' + it.index + '" data-gwi-f="qty" value="' + esc(l.qty == null ? '' : l.qty) + '"' + (err ? ' aria-invalid="true"' : '') + ' aria-describedby="' + lid + '_e"></div>' +
        '<div class="gw-field"><label class="gw-label" for="' + lid + '_r">' + (t.refs.length ? 'Referencia' : 'Referencia (opcional)') + '</label>' + ref + '</div>' +
        '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm gw-inv__del" data-gwi-act="del" data-gwi-i="' + it.index + '" aria-label="Quitar la línea ' + (n + 1) + ' de ' + esc(t.label) + (l.ref ? ', ' + esc(l.ref) : '') + '">Quitar</button>' +
        '<p class="gw-hint gw-inv__err" id="' + lid + '_e" data-gwi-err="' + it.index + '" role="alert"' + (err ? '' : ' hidden') + '>' + esc(err) + '</p></div>';
    }
    function render() {
      var counts = {}; state.lines.forEach(function (l) { counts[l.type] = (counts[l.type] || 0) + 1; });
      var html = '<div class="gw-inv" data-gwi-root>';
      if (!types.length) {
        html += '<div class="gw-alert"><div class="gw-alert__body">Este campo todavía no tiene tipos de inventario. Un administrador debe definirlos en la plantilla de eventos.</div></div></div>';
        el.innerHTML = html; return;
      }
      html += '<div class="gw-inv__types" role="group" aria-label="' + esc(title + ': tipos solicitados') + '">' + types.map(function (t) {
        var on = counts[t.key] > 0;
        return '<button type="button" class="gw-chip gw-inv__chip" data-gwi-act="toggle" data-gwi-type="' + esc(t.key) + '" aria-pressed="' + (on ? 'true' : 'false') + '">' + esc(t.label) + (on ? ' <span class="gw-inv__n">' + counts[t.key] + '</span>' : '') + '</button>';
      }).join('') + '</div>';
      var groups = grouped(state.lines, field);
      if (!groups.length) html += '<p class="gw-hint gw-inv__empty" data-gwi-empty>Todavía no se pidió inventario. Toca un tipo de arriba para agregarlo.</p>';
      groups.forEach(function (g) {
        var full = g.type.key && g.type.refs.length && g.type.refs.every(function (r) { return g.items.some(function (it) { return it.line.ref === r; }); });
        html += '<fieldset class="gw-inv__group"><legend class="gw-inv__legend">' + esc(g.type.label) + '</legend>' +
          g.items.map(function (it, n) { return lineHtml(g.type, it, n); }).join('') +
          (g.type.key ? '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-gwi-act="add" data-gwi-type="' + esc(g.type.key) + '"' + (full || state.lines.length >= MAX_LINES ? ' disabled' : '') + '>Agregar otra línea de ' + esc(g.type.label) + '</button>' + (full ? ' <span class="gw-hint">Ya usaste todas las referencias.</span>' : '') : '') + '</fieldset>';
      });
      html += '<p class="gw-inv__summary" data-gwi-summary aria-live="polite"></p></div>';
      el.innerHTML = html;
      paintSummary();
      if (focusNext) { var f = el.querySelector(focusNext); focusNext = null; if (f) f.focus(); }
    }
    function paintSummary() {
      var p = el.querySelector('[data-gwi-summary]'); if (!p) return;
      var s = summary(state.lines, field);
      p.innerHTML = s ? '<strong>Resumen:</strong> ' + esc(s) : '';
      p.hidden = !s;
    }
    function paintErrors(i) {
      var errs = lineErrors(state.lines, field);
      Array.prototype.forEach.call(el.querySelectorAll('[data-gwi-err]'), function (p) {
        var n = +p.getAttribute('data-gwi-err'), show = (i == null ? touched[n] : n === i || touched[n]) && errs[n];
        p.textContent = show ? errs[n] : ''; p.hidden = !show;
        var q = el.querySelector('[data-gwi-line="' + n + '"] [data-gwi-f="qty"]'); if (q) { if (show) q.setAttribute('aria-invalid', 'true'); else q.removeAttribute('aria-invalid'); }
      });
    }

    function addOne(tk) {
      var r = addLine(state.lines, field, tk); if (!r) return;
      state.lines = sortLines(r.lines, field); touched = {};
      focusNext = '[data-gwi-line="' + lastIndexOfType(state.lines, tk) + '"] [data-gwi-f="qty"]'; render(); emit();
    }
    el.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('[data-gwi-act]'); if (!b || !el.contains(b) || b.disabled) return;
      var act = b.getAttribute('data-gwi-act'), tk = b.getAttribute('data-gwi-type');
      if (act === 'toggle') {
        var mine = state.lines.filter(function (l) { return l.type === tk; }).length;
        if (!mine) { addOne(tk); return; }
        var t = typeByKey(types, tk), go = function () { state.lines = removeType(state.lines, tk); touched = {}; focusNext = '[data-gwi-type="' + tk + '"]'; render(); emit(); };
        if (mine > 1 && typeof root.showConfirm === 'function') Promise.resolve(root.showConfirm('¿Quitar «' + esc(t ? t.label : tk) + '» y sus ' + mine + ' líneas?', { confirmLabel: 'Sí, quitar' })).then(function (ok) { if (ok) go(); });
        else go();
      } else if (act === 'add') {
        addOne(tk);
      } else if (act === 'del') {
        var i = +b.getAttribute('data-gwi-i'), ty = state.lines[i] && state.lines[i].type, left = state.lines.filter(function (l) { return l.type === ty; }).length;
        state.lines = removeLine(state.lines, i); touched = {};
        focusNext = left > 1 ? '[data-gwi-act="add"][data-gwi-type="' + ty + '"]' : '[data-gwi-act="toggle"][data-gwi-type="' + ty + '"]';
        render(); emit();
      }
    });
    function onField(e) {
      var c = e.target; if (!c.getAttribute || !c.hasAttribute('data-gwi-f') || !el.contains(c)) return;
      var i = +c.getAttribute('data-gwi-i'), l = state.lines[i]; if (!l) return;
      if (c.getAttribute('data-gwi-f') === 'qty') l.qty = toInt(c.value); else { var r = String(c.value || '').trim(); l.ref = r || null; }
      touched[i] = true; paintErrors(i); paintSummary(); emit();
    }
    el.addEventListener('input', onField);
    el.addEventListener('change', function (e) { if (e.target.tagName === 'SELECT') onField(e); });

    el.dataset.gwiReady = '1';
    render();
    var ctl = {
      getValue: function () { return serialize(state); },
      setValue: function (v) { state = parse(v); state.lines = sortLines(state.lines, field); touched = {}; render(); emit(); },
      validate: function () { state.lines.forEach(function (_, i) { touched[i] = true; }); paintErrors(); return validate(state.lines, field); },
      summary: function () { return summary(state.lines, field); },
    };
    el._gwInventory = ctl;
    return ctl;
  }

  var api = { enhance: enhance, parse: parse, serialize: serialize, summary: summary, validate: validate, lineErrors: lineErrors, addLine: addLine, sortLines: sortLines, removeLine: removeLine, removeType: removeType, grouped: grouped, typesOf: typesOf, LIMITS: { lines: MAX_LINES, qty: MAX_QTY, ref: MAX_REF } };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
  root.GWInventory = api;
})(typeof window !== 'undefined' ? window : globalThis);
