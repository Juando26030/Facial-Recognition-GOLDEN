/* Orum — Lista desplegable con buscador (.gw-combobox). Reutilizable: cliente, país, ciudad, etc.
   Dos partes: (1) lógica PURA (normalizar, filtrar, mover la selección, resolver el texto) que se prueba con node
   (tests/js/gw_combobox_check.js) y (2) la parte de pantalla (teclado, aria, celular), que solo corre en el navegador.

   Uso en la plantilla:   <input class="gw-input" id="x" data-gw-combobox data-allow-free-text data-options='[{"value":"co","label":"Colombia"}]'>
   Uso desde JS:          const cb = GWCombobox.attach(input, { options: [{value, label, hint}], allowFreeText: false, placeholder: '' });
                          cb.setOptions(lista); cb.getValue(); cb.setValue(valor); cb.clear();
   Evento:                el <input> dispara 'gw:combobox-change' (burbujea) con detail { value, label, free } al elegir, escribir texto libre o vaciar.
   Valor:                 input.dataset.gwValue (vacío si no hay una opción elegida). Con data-allow-free-text, el texto escrito es el valor.
   Teclado:               flechas arriba/abajo mueven, Enter elige, Escape cierra (o vacía si ya estaba cerrada), Tab sale eligiendo lo marcado solo si hay una única coincidencia. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') { window.GWCombobox = api; if (typeof document !== 'undefined') { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { api._autoInit(document); }); else api._autoInit(document); } }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ---------- Lógica pura ----------
  function normalize(s) {
    return String(s == null ? '' : s).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  // Devuelve las opciones que contienen TODAS las palabras escritas (sin tildes ni mayúsculas), mejores primero:
  // 0 = empieza igual, 1 = una palabra empieza igual, 2 = lo contiene. Dentro de cada grupo se respeta el orden original.
  function filterOptions(options, query, limit) {
    var list = Array.isArray(options) ? options : [];
    var q = normalize(query);
    var out;
    if (!q) out = list.slice();
    else {
      var tokens = q.split(' ');
      var ranked = [];
      list.forEach(function (opt, i) {
        var label = normalize(opt && opt.label);
        var hay = opt && opt.hint ? label + ' ' + normalize(opt.hint) : label;
        for (var t = 0; t < tokens.length; t++) if (hay.indexOf(tokens[t]) === -1) return;
        var rank = 2;
        if (label.indexOf(q) === 0) rank = 0;
        else if (tokens.every(function (tok) { return (' ' + label).indexOf(' ' + tok) !== -1; })) rank = 1;
        ranked.push({ opt: opt, rank: rank, i: i });
      });
      ranked.sort(function (a, b) { return a.rank - b.rank || a.i - b.i; });
      out = ranked.map(function (r) { return r.opt; });
    }
    return limit > 0 ? out.slice(0, limit) : out;
  }

  // Mueve la opción marcada con las flechas, dando la vuelta en los extremos. current = -1 si ninguna.
  function moveIndex(current, delta, length) {
    if (!length) return -1;
    if (current < 0) return delta >= 0 ? 0 : length - 1;
    return (current + delta + length) % length;
  }

  // Qué significa el texto escrito: una opción exacta, texto libre (si se permite) o nada.
  function resolveText(options, text, allowFree) {
    var q = normalize(text);
    if (!q) return null;
    var list = Array.isArray(options) ? options : [];
    for (var i = 0; i < list.length; i++) if (normalize(list[i].label) === q) return { value: list[i].value, label: list[i].label, free: false };
    if (allowFree) return { value: String(text).trim(), label: String(text).trim(), free: true };
    return null;
  }

  // ---------- Pantalla ----------
  var seq = 0;

  function attach(input, config) {
    if (!input || input._gwCombobox) return input && input._gwCombobox;
    config = config || {};
    var allowFree = config.allowFreeText != null ? !!config.allowFreeText : input.hasAttribute('data-allow-free-text');
    var options = Array.isArray(config.options) ? config.options.slice() : [];
    var id = 'gwcb' + (++seq);
    var wrap = document.createElement('div');
    wrap.className = 'gw-combobox';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var list = document.createElement('ul');
    list.className = 'gw-combobox__list';
    list.id = id + '-list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    wrap.appendChild(list);
    var status = document.createElement('div');
    status.className = 'gw-sr-only';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    wrap.appendChild(status);

    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', list.id);
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('autocapitalize', 'off');
    input.setAttribute('spellcheck', 'false');
    if (config.placeholder && !input.getAttribute('placeholder')) input.setAttribute('placeholder', config.placeholder);

    var shown = [];          // opciones visibles ahora
    var active = -1;         // posición marcada con el teclado
    var chosen = null;       // { value, label, free }

    function emit() {
      input.dispatchEvent(new CustomEvent('gw:combobox-change', { bubbles: true, detail: chosen ? { value: chosen.value, label: chosen.label, free: !!chosen.free } : { value: '', label: '', free: false } }));
    }
    function setChosen(next, silent) {
      var same = (chosen && next && chosen.value === next.value && chosen.label === next.label) || (!chosen && !next);
      chosen = next;
      input.dataset.gwValue = next ? String(next.value) : '';
      if (next) input.removeAttribute('aria-invalid');
      if (!same && !silent) emit();
    }
    function isOpen() { return !list.hidden; }
    function close() {
      list.hidden = true; active = -1;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }
    function paintActive() {
      Array.prototype.forEach.call(list.children, function (li, i) {
        var on = i === active;
        li.classList.toggle('is-active', on);
        li.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on) { input.setAttribute('aria-activedescendant', li.id); if (li.scrollIntoView) li.scrollIntoView({ block: 'nearest' }); }
      });
      if (active < 0) input.removeAttribute('aria-activedescendant');
    }
    function render(query) {
      shown = filterOptions(options, query, config.limit || 200);
      list.textContent = '';
      shown.forEach(function (opt, i) {
        var li = document.createElement('li');
        li.className = 'gw-combobox__opt';
        li.id = id + '-o' + i;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        li.setAttribute('data-i', String(i));
        var name = document.createElement('span'); name.className = 'gw-combobox__name'; name.textContent = opt.label; li.appendChild(name);
        if (opt.hint) { var h = document.createElement('span'); h.className = 'gw-combobox__hint'; h.textContent = opt.hint; li.appendChild(h); }
        list.appendChild(li);
      });
      if (!shown.length) {
        var empty = document.createElement('li');
        empty.className = 'gw-combobox__empty'; empty.setAttribute('role', 'presentation');
        empty.textContent = allowFree && String(query).trim() ? 'Se usará el texto que escribes.' : 'Sin resultados. Prueba con otra palabra.';
        list.appendChild(empty);
      }
      status.textContent = shown.length ? shown.length + (shown.length === 1 ? ' resultado' : ' resultados') : 'Sin resultados';
      // marca la opción ya elegida o, si el texto coincide exacto, esa
      active = -1;
      var exact = resolveText(shown, query, false);
      if (exact) active = shown.findIndex(function (o) { return o.value === exact.value; });
      paintActive();
    }
    function open(query) {
      render(query == null ? '' : query);
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }
    function choose(i) {
      var opt = shown[i];
      if (!opt) return;
      input.value = opt.label;
      setChosen({ value: opt.value, label: opt.label, free: false });
      close();
    }
    // Al salir del campo: lo escrito se vuelve opción exacta / texto libre; si no es ninguna de las dos se devuelve lo último elegido (o se vacía).
    function settle() {
      var text = input.value;
      if (!String(text).trim()) { setChosen(null); input.value = ''; return; }
      var r = resolveText(options, text, allowFree);
      if (r) { input.value = r.label; setChosen(r); }
      else if (chosen && !chosen.free) input.value = chosen.label;
      else { input.value = ''; setChosen(null); }
    }

    input.addEventListener('input', function () {
      if (chosen && normalize(input.value) !== normalize(chosen.label)) setChosen(allowFree && input.value.trim() ? { value: input.value.trim(), label: input.value.trim(), free: true } : null);
      else if (!chosen && allowFree && input.value.trim()) setChosen({ value: input.value.trim(), label: input.value.trim(), free: true });
      open(input.value);
    });
    input.addEventListener('focus', function () { if (!input.readOnly && !input.disabled) open(chosen && !chosen.free && normalize(input.value) === normalize(chosen.label) ? '' : input.value); });
    input.addEventListener('click', function () { if (!isOpen() && !input.readOnly && !input.disabled) open(''); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!isOpen()) open(input.value);
        active = moveIndex(active, e.key === 'ArrowDown' ? 1 : -1, shown.length);
        paintActive();
      } else if (e.key === 'Enter') {
        if (isOpen() && active >= 0) { e.preventDefault(); e.stopPropagation(); choose(active); }
        else if (isOpen() && shown.length === 1 && normalize(input.value)) { e.preventDefault(); e.stopPropagation(); choose(0); }
      } else if (e.key === 'Escape') {
        if (isOpen()) { e.preventDefault(); e.stopPropagation(); close(); }
      } else if (e.key === 'Tab') {
        if (isOpen() && active < 0 && shown.length === 1 && normalize(input.value)) choose(0);
      }
    });
    input.addEventListener('blur', function () { close(); settle(); });
    // El clic en una opción no debe quitarle el foco al campo antes de elegir (mouse y tacto).
    list.addEventListener('mousedown', function (e) { e.preventDefault(); });
    list.addEventListener('click', function (e) {
      var li = e.target.closest ? e.target.closest('[data-i]') : null;
      if (li) choose(parseInt(li.getAttribute('data-i'), 10));
    });

    var api = {
      input: input,
      setOptions: function (next) {
        options = Array.isArray(next) ? next.slice() : [];
        if (chosen && !chosen.free) {            // si lo elegido ya no está en la lista, se suelta
          var still = options.some(function (o) { return o.value === chosen.value; });
          if (!still) { input.value = ''; setChosen(null); }
        }
        if (isOpen()) render(input.value);
      },
      getOptions: function () { return options.slice(); },
      getValue: function () { return chosen ? chosen.value : ''; },
      getLabel: function () { return chosen ? chosen.label : ''; },
      setValue: function (value, silent) {
        var found = options.filter(function (o) { return String(o.value) === String(value); })[0];
        if (found) { input.value = found.label; setChosen({ value: found.value, label: found.label, free: false }, silent); }
        else if (allowFree && value) { input.value = String(value); setChosen({ value: String(value), label: String(value), free: true }, silent); }
        else { input.value = ''; setChosen(null, silent); }
      },
      clear: function () { input.value = ''; setChosen(null); close(); }
    };
    input._gwCombobox = api;
    if (input.value) settle();
    return api;
  }

  function _autoInit(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll('input[data-gw-combobox]'), function (input) {
      if (input._gwCombobox) return;
      var options = [];
      try { options = JSON.parse(input.getAttribute('data-options') || '[]'); } catch (e) { options = []; }
      attach(input, { options: options });
    });
  }

  return { normalize: normalize, filterOptions: filterOptions, moveIndex: moveIndex, resolveText: resolveText, attach: attach, _autoInit: _autoInit };
}));
