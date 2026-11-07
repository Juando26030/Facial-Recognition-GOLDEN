/* GoldenWeb 2.0 — comportamiento de la base visual (static/css/design-system.css). Sin dependencias, sin red: sirve igual en el quiosco sin conexión.
   Todo por DELEGACIÓN de eventos sobre `document` (sirve para HTML generado después) y por atributos `data-gw-*`; no muta el subárbol del elemento que recibe el evento.
   - Tema:       [data-gw-theme-toggle]  claro <-> oscuro POR DISPOSITIVO (localStorage 'gw_theme', con try/catch). La clase del <html> la pone antes de pintar templates/_gw_head.html.
   - Menú:       [data-gw-nav-toggle] dentro de .gw-nav (celular).
   - Ayuda «?»:  .gw-help > [data-gw-help-btn] + .gw-popover ; «Entendido» = [data-gw-help-close]. Foco atrapado, Esc cierra y devuelve el foco.
   - Modal:      [data-gw-open="id"] abre .gw-modal-backdrop#id ; [data-gw-close] lo cierra (Esc también; clic afuera NO: los formularios de datos no se cierran así).
   - Recorrido:  elementos [data-gw-tour-step="n" data-gw-tour-title data-gw-tour-text] dentro de un contenedor con [data-gw-tour="clave"]; se muestra UNA vez por dispositivo
                 (localStorage 'gw_tour_<clave>'); [data-gw-tour-restart="clave"] lo repite. API: window.GW.tour.start(clave, {force:true}).
   - Asistente:  [data-gw-wizard] con [data-gw-wizard-panel], [data-gw-wizard-next], [data-gw-wizard-prev], [data-gw-wizard-count], [data-gw-wizard-bar].
   - Celular (<= 640 px): el botón [data-gw-tour-restart] pasa a ser el 4.º chip («Guía») del `.gw-steps` de su pantalla y los subtítulos largos llevan su texto completo en title;
                 al ensanchar la ventana todo vuelve a su sitio. No cambia ids ni atributos.
   - Vaciar búsqueda (M8): a todo campo de búsqueda (input type=search, inputs dentro de .gw-search o con placeholder «Buscar…»/«Escribe o escanea…», incluso los generados por JS) se le agrega a la derecha un botón
                 .gw-search__clear--in con la papelera (aria-label «Vaciar búsqueda»), visible solo con texto: vacía el campo, devuelve el foco y dispara `input`. Excluye [data-gw-no-clear] y los que ya traen su papelera.
   - Buscador «¿qué quieres hacer?» (Fase 2): NO está construido; el hueco es [data-gw-search-slot] y los data-gw-keywords. */
(function () {
  'use strict';
  var KEY_THEME = 'gw_theme';
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function store(get, key, value) {                       // localStorage puede fallar (ventana privada, datos bloqueados): la página funciona igual
    try { if (get) return window.localStorage.getItem(key); window.localStorage.setItem(key, value); } catch (e) { /* sin preferencia guardada */ }
    return null;
  }
  function reducedMotion() { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
  function visible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }
  function focusables(root) { return Array.prototype.filter.call(root.querySelectorAll(FOCUSABLE), visible); }
  function trapTab(e, root) {                             // Tab y Shift+Tab giran dentro del panel
    if (e.key !== 'Tab') return;
    var f = focusables(root);
    if (!f.length) { e.preventDefault(); return; }
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!root.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  }

  /* ----------------------------------------------------------------- Tema */
  function currentTheme() { return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; }
  function applyTheme(theme) {
    if (theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark'); else document.documentElement.removeAttribute('data-theme');
    Array.prototype.forEach.call(document.querySelectorAll('[data-gw-theme-toggle]'), function (b) {
      b.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
      var label = b.querySelector('[data-gw-theme-label]');
      var name = theme === 'dark' ? 'Tema claro' : 'Tema oscuro';
      if (label) label.textContent = name;
      b.setAttribute('aria-label', name); b.setAttribute('title', name);       // en celular el botón es solo ícono: el nombre accesible y el tooltip salen de aquí
    });
  }
  function toggleTheme() { var next = currentTheme() === 'dark' ? 'light' : 'dark'; applyTheme(next); store(false, KEY_THEME, next); }

  /* ----------------------------------------------------------------- Ayuda «?» */
  var openHelp = null;                                    // {root, btn, pop}
  function closeHelp(returnFocus) {
    if (!openHelp) return;
    var h = openHelp; openHelp = null;
    h.pop.hidden = true; h.btn.setAttribute('aria-expanded', 'false');
    if (returnFocus) h.btn.focus();
  }
  function showHelp(root) {
    var btn = root.querySelector('[data-gw-help-btn]'), pop = root.querySelector('.gw-popover');
    if (!btn || !pop) return;
    closeHelp(false);
    pop.hidden = false; btn.setAttribute('aria-expanded', 'true'); openHelp = { root: root, btn: btn, pop: pop };
    var ok = pop.querySelector('[data-gw-help-close]') || focusables(pop)[0];
    if (ok) ok.focus();
  }

  /* ----------------------------------------------------------------- Modal */
  var openModal = null;                                   // {el, opener}
  function showModal(el, opener) {
    if (!el) return;
    el.setAttribute('data-open', 'true'); openModal = { el: el, opener: opener || null };
    var f = focusables(el); if (f.length) f[0].focus();
  }
  function hideModal() {
    if (!openModal) return;
    var m = openModal; openModal = null; m.el.removeAttribute('data-open');
    if (m.opener && m.opener.focus) m.opener.focus();
  }

  /* ----------------------------------------------------------------- Asistente por pasos */
  function wizardGo(wiz, index) {
    var panels = wiz.querySelectorAll('[data-gw-wizard-panel]'), total = panels.length;
    if (!total) return;
    index = Math.max(0, Math.min(total - 1, index)); wiz.setAttribute('data-gw-step', String(index));
    Array.prototype.forEach.call(panels, function (p, i) { p.hidden = i !== index; });
    var count = wiz.querySelector('[data-gw-wizard-count]'); if (count) count.textContent = 'Paso ' + (index + 1) + ' de ' + total;
    var bar = wiz.querySelector('[data-gw-wizard-bar]'); if (bar) { bar.style.width = ((index + 1) / total * 100) + '%'; if (bar.parentNode) { bar.parentNode.setAttribute('aria-valuenow', String(index + 1)); bar.parentNode.setAttribute('aria-valuemax', String(total)); } }
    var prev = wiz.querySelector('[data-gw-wizard-prev]'); if (prev) prev.hidden = index === 0;
    var next = wiz.querySelector('[data-gw-wizard-next]'); if (next) { var last = index === total - 1; var t = next.getAttribute(last ? 'data-label-last' : 'data-label'); if (t) next.textContent = t; next.setAttribute('data-last', last ? 'true' : 'false'); }
  }

  /* ----------------------------------------------------------------- Recorrido de primera vez */
  var tour = null;                                        // estado del recorrido abierto
  function setToursOff(off) {                                // guarda en la cuenta (no en el dispositivo): PUT /api/me/tours-auto-off
    window.GW_TOURS_OFF = !!off;
    try { fetch('/api/me/tours-auto-off', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ off: !!off }) }).then(function (r) { if (!r.ok) throw new Error(); if (window.showToast) window.showToast(off ? 'Guías automáticas desactivadas en tu cuenta. El botón «Guía» sigue disponible.' : 'Guías automáticas activadas.', 'success'); }).catch(function () { if (window.showToast) window.showToast('No se pudo guardar la preferencia.', 'error'); }); } catch (e) { /* sin red */ }
  }
  function tourSeen(key) { return store(true, 'gw_tour_' + key) === 'done'; }
  function tourClose(key, finished) {
    if (!tour) return;
    var t = tour; tour = null;
    if (t.root.parentNode) t.root.parentNode.removeChild(t.root);
    window.removeEventListener('resize', t.onMove); window.removeEventListener('scroll', t.onMove, true);
    store(false, 'gw_tour_' + key, 'done');                // omitir o terminar: no vuelve a salir solo en este dispositivo
    if (t.opener && t.opener.focus) t.opener.focus();
    void finished;
  }
  function tourPlace(t) {
    var s = t.steps[t.i], el = s.el, r = el.getBoundingClientRect(), pad = 6;
    t.spot.style.top = (r.top - pad) + 'px'; t.spot.style.left = (r.left - pad) + 'px'; t.spot.style.width = (r.width + 2 * pad) + 'px'; t.spot.style.height = (r.height + 2 * pad) + 'px';
    var card = t.card, ch = card.offsetHeight, cw = card.offsetWidth, vh = window.innerHeight, vw = window.innerWidth;
    var top = r.bottom + 14; if (top + ch > vh - 8) top = Math.max(8, r.top - ch - 14);
    var left = Math.min(Math.max(8, r.left), Math.max(8, vw - cw - 8));
    card.style.top = top + 'px'; card.style.left = left + 'px';
  }
  function tourShow(t, i) {
    t.i = Math.max(0, Math.min(t.steps.length - 1, i));
    var s = t.steps[t.i];
    s.el.scrollIntoView({ block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' });
    t.count.textContent = 'Paso ' + (t.i + 1) + ' de ' + t.steps.length;
    t.title.textContent = s.title; t.text.textContent = s.text;
    t.back.hidden = t.i === 0; t.next.textContent = t.i === t.steps.length - 1 ? 'Listo' : 'Siguiente';
    t.skip.hidden = t.i === t.steps.length - 1;
    tourPlace(t); window.setTimeout(function () { if (tour === t) tourPlace(t); }, reducedMotion() ? 0 : 350);   // tras el desplazamiento suave
    t.next.focus();
  }
  function mk(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }
  function startTour(key, opts) {
    opts = opts || {};
    if (tour) return;
    var host = document.querySelector('[data-gw-tour="' + key + '"]') || document;
    var steps = Array.prototype.map.call(host.querySelectorAll('[data-gw-tour-step]'), function (el) {
      return { el: el, n: parseInt(el.getAttribute('data-gw-tour-step'), 10) || 0, title: el.getAttribute('data-gw-tour-title') || '', text: el.getAttribute('data-gw-tour-text') || '' };
    }).filter(function (s) { return visible(s.el); }).sort(function (a, b) { return a.n - b.n; });
    if (!steps.length || (!opts.force && tourSeen(key))) return;
    var root = mk('div', 'gw-tour'), spot = mk('div', 'gw-tour__spot'), card = mk('div', 'gw-tour__card');
    card.setAttribute('role', 'dialog'); card.setAttribute('aria-modal', 'true'); card.setAttribute('aria-labelledby', 'gwTourTitle'); card.setAttribute('aria-describedby', 'gwTourText');
    var count = mk('p', 'gw-tour__count'), title = mk('h2', 'gw-tour__title'), text = mk('p', 'gw-tour__text'), foot = mk('div', 'gw-tour__foot');
    title.id = 'gwTourTitle'; text.id = 'gwTourText'; count.setAttribute('aria-live', 'polite');
    var skip = mk('button', 'gw-btn gw-btn--ghost gw-btn--sm gw-tour__skip', 'Omitir'), back = mk('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Atrás'), next = mk('button', 'gw-btn gw-btn--primary gw-btn--sm', 'Siguiente');
    [skip, back, next].forEach(function (b) { b.type = 'button'; });
    skip.setAttribute('data-gw-tour-skip', ''); back.setAttribute('data-gw-tour-back', ''); next.setAttribute('data-gw-tour-next', '');
    foot.appendChild(skip); foot.appendChild(back); foot.appendChild(next);
    card.appendChild(count); card.appendChild(title); card.appendChild(text);
    if (document.querySelector('meta[name="gw-staff"]') || window.GW_TOURS_OFF !== undefined) {            // no mostrar más las guías solas (preferencia de la cuenta)
      var off = mk('label', 'gw-tour__off'), chk = mk('input'); chk.type = 'checkbox'; chk.setAttribute('data-gw-tour-off', ''); chk.checked = !!window.GW_TOURS_OFF;
      off.appendChild(chk); off.appendChild(document.createTextNode(' No mostrar guías automáticas')); card.appendChild(off);
    }
    card.appendChild(foot);
    root.appendChild(spot); root.appendChild(card); document.body.appendChild(root);
    var t = { key: key, root: root, spot: spot, card: card, count: count, title: title, text: text, back: back, next: next, skip: skip, steps: steps, i: 0, opener: document.activeElement,
              onMove: function () { if (tour) tourPlace(tour); } };
    tour = t;
    window.addEventListener('resize', t.onMove); window.addEventListener('scroll', t.onMove, true);
    tourShow(t, 0);
  }

  /* ----------------------------------------------------------------- Bloques plegables (pantallas de configuración)
     Todo `.gw-group__item` cuyo primer hijo es `.gw-item-head` se puede plegar/desplegar (botón con chevron o clic en el título). Se pliega con una CLASE (`gw-is-folded`) y CSS:
     no se mueve ni envuelve ningún nodo, así que ids, selectores y los campos pendientes de guardar siguen igual. El estado se recuerda en este dispositivo (localStorage). */
  function foldKey(item, i) { return 'gw_fold_' + location.pathname + '#' + (item.id || ('i' + i)); }
  function foldSet(item, folded) {
    item.classList.toggle('gw-is-folded', folded);
    var b = item.querySelector(':scope > .gw-item-head > [data-gw-fold-btn]');
    if (b) { b.setAttribute('aria-expanded', folded ? 'false' : 'true'); b.setAttribute('aria-label', (folded ? 'Desplegar «' : 'Plegar «') + ((item.querySelector(':scope > .gw-item-head h4') || {}).textContent || 'bloque') + '»'); }
  }
  function foldInit() {
    var panels = document.querySelectorAll('.gw-tabpanel, .gw-config__wrap, main');
    var seen = [];
    Array.prototype.forEach.call(document.querySelectorAll('.gw-group__item'), function (item, i) {
      var head = item.firstElementChild;
      if (!head || !head.classList.contains('gw-item-head') || item.children.length < 2 || item.hasAttribute('data-gw-nofold')) return;
      var btn = mk('button', 'gw-fold__btn'); btn.type = 'button'; btn.setAttribute('data-gw-fold-btn', '');
      btn.innerHTML = '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="/static/img/icons.svg#i-chevron"></use></svg>';
      head.appendChild(btn); head.classList.add('gw-fold__head'); item.setAttribute('data-gw-foldable', '');
      item.setAttribute('data-gw-fold-key', foldKey(item, i));
      foldSet(item, store(true, foldKey(item, i)) === '1');
    });
    void panels; void seen;
    Array.prototype.forEach.call(document.querySelectorAll('.gw-tabpanel'), function (panel) {
      if (panel.querySelectorAll('[data-gw-foldable]').length < 2) return;
      var bar = mk('div', 'gw-fold__bar'), a = mk('button', 'gw-btn gw-btn--ghost gw-btn--sm', 'Plegar todo'), z = mk('button', 'gw-btn gw-btn--ghost gw-btn--sm', 'Desplegar todo');
      a.type = z.type = 'button'; a.setAttribute('data-gw-fold-all', '1'); z.setAttribute('data-gw-fold-all', '0');
      bar.appendChild(a); bar.appendChild(z);
      var lead = panel.querySelector(':scope > .gw-tabpanel__head');
      if (lead && lead.nextSibling) panel.insertBefore(bar, lead.nextSibling); else panel.insertBefore(bar, panel.firstChild);
    });
  }
  function foldToggle(item) {
    var f = !item.classList.contains('gw-is-folded');
    foldSet(item, f); store(false, item.getAttribute('data-gw-fold-key'), f ? '1' : '0');
  }

  /* ----------------------------------------------------------------- Introducción compacta en celular */
  var moved = [];                                         // {btn, home, next, li}
  var mqMobile = window.matchMedia ? window.matchMedia('(max-width: 640px)') : null;
  function stepsFor(btn) {
    var key = btn.getAttribute('data-gw-tour-restart'), host = key ? document.querySelector('[data-gw-tour="' + key + '"]') : null;
    return (host && host.querySelector('.gw-steps')) || document.querySelector('.gw-steps');
  }
  function compactIntro() {
    var mobile = !!(mqMobile && mqMobile.matches);
    if (mobile) {
      Array.prototype.forEach.call(document.querySelectorAll('[data-gw-tour-restart]'), function (btn) {
        if (!btn.classList.contains('gw-btn') || btn.closest('.gw-steps')) return;
        var ol = stepsFor(btn); if (!ol) return;
        var li = document.createElement('li'); li.className = 'gw-steps__guide';
        moved.push({ btn: btn, home: btn.parentNode, next: btn.nextSibling, li: li });
        ol.appendChild(li); li.appendChild(btn);
      });
      Array.prototype.forEach.call(document.querySelectorAll('.gw-page-head__sub, .gw-page .gw-stack-lg > .gw-stack:first-child > .gw-lead'), function (el) {
        if (!el.getAttribute('title')) el.setAttribute('title', (el.textContent || '').replace(/\s+/g, ' ').trim());
      });
    } else {
      while (moved.length) {
        var m = moved.pop();
        if (m.home && m.home.isConnected) m.home.insertBefore(m.btn, m.next && m.next.parentNode === m.home ? m.next : null);
        if (m.li.parentNode) m.li.parentNode.removeChild(m.li);
      }
    }
  }


  /* ----------------------------------------------------------------- Vaciar búsqueda (papelera dentro de todo campo de búsqueda) */
  var CLEAR_LABEL = 'Vaciar búsqueda';
  var SEARCH_PLACEHOLDER = /^\s*(buscar|busca|filtrar|escribe o escanea|escanea o escribe)/i;
  var SKIP_TAGS = { TR: 1, TD: 1, TH: 1, TBODY: 1, THEAD: 1, OPTION: 1, SCRIPT: 1, STYLE: 1, SVG: 1 };
  var iconBase = null;
  function iconUrl() {
    if (iconBase) return iconBase;
    var u = window.GW_ICON_URL, use;
    if (!u) { use = document.querySelector('use[href*="icons.svg"]'); u = use ? use.getAttribute('href') : ''; }
    iconBase = (u || '/static/img/icons.svg').split('#')[0];
    return iconBase;
  }
  function isSearchInput(el) {
    if (!el || el.tagName !== 'INPUT' || el.hasAttribute('data-gw-clear-on') || el.hasAttribute('data-gw-no-clear') || el.readOnly) return false;
    var t = (el.getAttribute('type') || 'text').toLowerCase();
    if (t !== 'search' && t !== 'text') return false;
    if (el.closest('.sp-kbd-wrap')) return false;                                       // el lector/teclado del Registro con el modo touch lleva su propio botón
    var row = el.closest('.gw-search__row');
    if (row && row.querySelector('.gw-search__clear:not(.gw-search__clear--in):not(.gw-search__clear--proxy)')) return false;       // ya trae su papelera visible; las «proxy» (Registro: #searchClearBtn, Respuestas) están ocultas y guardan la lógica de la pantalla
    if (t === 'search' || el.hasAttribute('data-gw-clearable') || el.closest('.gw-search')) return true;
    return SEARCH_PLACEHOLDER.test(el.getAttribute('placeholder') || '');
  }
  function syncClear(input) { if (input._gwClear) input._gwClear.hidden = !input.value; }
  function installClear(input) {
    if (!isSearchInput(input) || !input.parentNode) return;
    input.setAttribute('data-gw-clear-on', '');
    var host = input.parentNode, hadFocus = document.activeElement === input;
    if (!(host.classList && (host.classList.contains('gw-search__field') || host.classList.contains('gw-clearable')))) {
      var wrap = document.createElement('span'); wrap.className = 'gw-clearable';
      host.insertBefore(wrap, input); wrap.appendChild(input); host = wrap;
    }
    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'gw-btn gw-search__clear gw-search__clear--in'; btn.setAttribute('data-gw-clear', '');
    btn.setAttribute('aria-label', CLEAR_LABEL); btn.title = CLEAR_LABEL; btn.hidden = !input.value;
    btn.innerHTML = '<svg class="gw-icon" aria-hidden="true"><use href="' + iconUrl() + '#i-trash"></use></svg>';
    btn._gwInput = input; input._gwClear = btn;
    input.classList.add('gw-input--clearable');
    host.appendChild(btn);
    if (hadFocus) { try { input.focus({ preventScroll: true }); } catch (e) { /* sin foco */ } }
  }
  function scanClear(root) {
    if (!root || root.nodeType !== 1 || SKIP_TAGS[root.tagName]) return;
    if (root.tagName === 'INPUT') { installClear(root); return; }
    Array.prototype.forEach.call(root.querySelectorAll('input'), installClear);
  }
  function runClear(btn) {
    var input = btn._gwInput; if (!input || input.disabled || input.readOnly) return;
    var own = document.getElementById(input.getAttribute('data-gw-clear-btn') || '');          // botón oculto de la pantalla que hace más que vaciar (vuelve a buscar, reinicia filtros…)
    if (own) { own.click(); btn.hidden = !input.value; try { input.focus(); } catch (e0) { /* sin foco */ } return; }
    input.value = '';
    btn.hidden = true;
    try { input.dispatchEvent(new Event('input', { bubbles: true })); if ((input.getAttribute('type') || '') === 'search') input.dispatchEvent(new Event('search', { bubbles: true })); } catch (e) { /* navegadores sin Event() */ }
    try { input.focus(); } catch (e2) { /* sin foco */ }
  }
  document.addEventListener('input', function (e) { if (e.target && e.target._gwClear) syncClear(e.target); }, true);
  document.addEventListener('change', function (e) { if (e.target && e.target._gwClear) syncClear(e.target); }, true);
  document.addEventListener('focusin', function (e) { if (e.target && e.target._gwClear) syncClear(e.target); });
  document.addEventListener('pointerover', function (e) { if (e.target && e.target._gwClear) syncClear(e.target); }, true);          // otro código vacía el campo sin avisar (p. ej. al acreditar): se revisa al pasar el ratón
  document.addEventListener('mousedown', function (e) { if (e.target && e.target.closest && e.target.closest('[data-gw-clear]')) e.preventDefault(); });          // el clic en la papelera no le quita el foco a la caja (ni cierra el teclado del celular)
  function watchClear() {
    scanClear(document.body);
    if (!window.MutationObserver) return;
    new MutationObserver(function (muts) {
      muts.forEach(function (m) { Array.prototype.forEach.call(m.addedNodes, scanClear); });
    }).observe(document.body, { childList: true, subtree: true });
  }

  /* ----------------------------------------------------------------- Obligatorio: asterisco naranja en TODA pantalla del personal (6-nov-2026)
     Todo campo con `required` lleva en su etiqueta un asterisco naranja (.gw-req); un « *» escrito a mano al final de una etiqueta se convierte en ese mismo asterisco. Si `required` se quita después
     (p. ej. la base del Excel pasa a ser opcional), el asterisco que puso este código se quita. Etiquetas con data-gw-noreq no se tocan. Las páginas públicas no cargan este archivo: allí no hay asteriscos. */
  var REQ_SKIP_TYPES = { hidden: 1, submit: 1, button: 1, reset: 1, image: 1 };
  function cssEsc(v) { return (window.CSS && CSS.escape) ? CSS.escape(v) : String(v).replace(/["\\]/g, '\\$&'); }
  function labelOf(ctl) {
    var lab = null;
    if (ctl.id) lab = document.querySelector('label[for="' + cssEsc(ctl.id) + '"]');
    if (!lab) lab = ctl.closest('label');
    if (!lab) { var box = ctl.closest('.gw-field, .badge-input-group, .gw-registro__editfield, [data-field-key]'); if (box) lab = box.querySelector('label'); }
    return lab;
  }
  function hasStar(lab) { return !!lab.querySelector('.gw-req'); }
  function addStar(lab, auto) {
    if (!lab || lab.hasAttribute('data-gw-noreq') || hasStar(lab)) return;
    var last = lab.lastChild;
    while (last && last.nodeType === 3 && !last.nodeValue.trim()) { lab.removeChild(last); last = lab.lastChild; }
    if (last && last.nodeType === 3) last.nodeValue = last.nodeValue.replace(/\s*\*\s*$/, '');
    var sp = document.createElement('span'); sp.className = 'gw-req'; sp.setAttribute('aria-hidden', 'true'); sp.textContent = ' *';
    if (auto) sp.setAttribute('data-gw-auto', '');
    lab.appendChild(sp);
  }
  function handStars(root) {            // « *» escrito a mano al final de una etiqueta (sin control `required` que lo respalde) → el mismo asterisco naranja
    var labs = root.tagName === 'LABEL' ? [root] : Array.prototype.slice.call(root.querySelectorAll('label'));
    labs.forEach(function (lab) {
      if (lab.hasAttribute('data-gw-noreq') || hasStar(lab)) return;
      var last = lab.lastChild;
      if (last && last.nodeType === 3 && /\s\*\s*$/.test(last.nodeValue)) addStar(lab, false);
    });
  }
  function reqControl(ctl) {
    if (!ctl || ctl.tagName === 'LABEL' || !/^(INPUT|SELECT|TEXTAREA)$/.test(ctl.tagName)) return;
    if (REQ_SKIP_TYPES[(ctl.getAttribute('type') || '').toLowerCase()]) return;
    var lab = labelOf(ctl); if (!lab) return;
    if (ctl.hasAttribute('required')) addStar(lab, true);
    else { var st = lab.querySelector('.gw-req[data-gw-auto]'); if (st) st.remove(); }
  }
  function scanReq(root) {
    if (!root || root.nodeType !== 1 || SKIP_TAGS[root.tagName]) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(root.tagName)) { reqControl(root); return; }
    handStars(root);
    Array.prototype.forEach.call(root.querySelectorAll('input[required], select[required], textarea[required]'), reqControl);
  }
  function watchReq() {
    scanReq(document.body);
    if (!window.MutationObserver) return;
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        if (m.type === 'attributes') { reqControl(m.target); return; }
        Array.prototype.forEach.call(m.addedNodes, scanReq);
      });
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['required'] });
  }

  /* ----------------------------------------------------------------- Eventos (delegados) */
  document.addEventListener('click', function (e) {
    var tgt = e.target; if (!tgt || !tgt.closest) return;
    var el;
    if ((el = tgt.closest('[data-gw-theme-toggle]'))) { toggleTheme(); return; }
    if ((el = tgt.closest('[data-gw-nav-toggle]'))) {
      var nav = el.closest('.gw-nav'); if (nav) { var open = nav.getAttribute('data-open') !== 'true'; nav.setAttribute('data-open', open ? 'true' : 'false'); el.setAttribute('aria-expanded', open ? 'true' : 'false'); }
      return;
    }
    if (tour) {
      if (tgt.closest('[data-gw-tour-next]')) { if (tour.i >= tour.steps.length - 1) tourClose(tour.key, true); else tourShow(tour, tour.i + 1); return; }
      if (tgt.closest('[data-gw-tour-back]')) { tourShow(tour, tour.i - 1); return; }
      if (tgt.closest('[data-gw-tour-skip]')) { tourClose(tour.key, false); return; }
      return;
    }
    if ((el = tgt.closest('[data-gw-clear]'))) { e.preventDefault(); runClear(el); return; }
    if ((el = tgt.closest('[data-gw-fold-btn]'))) { foldToggle(el.closest('[data-gw-foldable]')); return; }
    if ((el = tgt.closest('.gw-fold__head h4'))) { foldToggle(el.closest('[data-gw-foldable]')); return; }
    if ((el = tgt.closest('[data-gw-fold-all]'))) {
      var fold = el.getAttribute('data-gw-fold-all') === '1', pnl = el.closest('.gw-tabpanel');
      Array.prototype.forEach.call(pnl.querySelectorAll('[data-gw-foldable]'), function (it) { foldSet(it, fold); store(false, it.getAttribute('data-gw-fold-key'), fold ? '1' : '0'); });
      return;
    }
    if (tgt.matches && tgt.matches('[data-gw-tour-off]')) { setToursOff(tgt.checked); return; }
    if ((el = tgt.closest('[data-gw-tour-restart]'))) { e.preventDefault(); startTour(el.getAttribute('data-gw-tour-restart'), { force: true }); return; }
    if ((el = tgt.closest('[data-gw-help-btn]'))) {
      var root = el.closest('.gw-help'); if (!root) return;
      if (openHelp && openHelp.root === root) closeHelp(true); else showHelp(root);
      return;
    }
    if (tgt.closest('[data-gw-help-close]')) { closeHelp(true); return; }
    if (openHelp && !tgt.closest('.gw-help')) closeHelp(false);          // clic afuera cierra la ayuda (no es un formulario de datos)
    if ((el = tgt.closest('[data-gw-open]'))) { showModal(document.getElementById(el.getAttribute('data-gw-open')), el); return; }
    if (tgt.closest('[data-gw-close]')) { hideModal(); return; }
    if ((el = tgt.closest('[data-gw-wizard-next]'))) {
      var w = el.closest('[data-gw-wizard]'); if (w) { var i = parseInt(w.getAttribute('data-gw-step') || '0', 10); if (el.getAttribute('data-last') === 'true') w.dispatchEvent(new CustomEvent('gw:wizard-finish', { bubbles: true })); else wizardGo(w, i + 1); }
      return;
    }
    if ((el = tgt.closest('[data-gw-wizard-prev]'))) { var w2 = el.closest('[data-gw-wizard]'); if (w2) wizardGo(w2, parseInt(w2.getAttribute('data-gw-step') || '0', 10) - 1); return; }
  });

  document.addEventListener('keydown', function (e) {
    if (tour) {
      if (e.key === 'Escape') { e.preventDefault(); tourClose(tour.key, false); return; }
      trapTab(e, tour.card); return;
    }
    if (openHelp) {
      if (e.key === 'Escape') { e.preventDefault(); closeHelp(true); return; }
      if (e.key === 'Tab') { trapTab(e, openHelp.pop); return; }
    }
    if (openModal) {
      if (e.key === 'Escape') { e.preventDefault(); hideModal(); return; }
      trapTab(e, openModal.el);
    }
  });

  window.GW = Object.assign(window.GW || {}, { tour: { start: startTour, seen: tourSeen, setOff: setToursOff }, theme: { get: currentTheme, set: function (t) { applyTheme(t); store(false, KEY_THEME, t); } }, help: { close: closeHelp }, wizard: { go: wizardGo } });

  function init() {
    applyTheme(currentTheme());
    compactIntro();
    watchClear();
    watchReq();
    foldInit();
    if (mqMobile) { if (mqMobile.addEventListener) mqMobile.addEventListener('change', compactIntro); else if (mqMobile.addListener) mqMobile.addListener(compactIntro); }
    Array.prototype.forEach.call(document.querySelectorAll('[data-gw-wizard]'), function (w) { wizardGo(w, 0); });
    var auto = document.querySelector('[data-gw-tour][data-gw-tour-auto]');          // recorrido de primera vez: solo si la página lo pide
    if (auto && !window.GW_TOURS_OFF) window.setTimeout(function () { startTour(auto.getAttribute('data-gw-tour')); }, 400);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
