/* GoldenWeb 2.0 — comportamiento de la base visual (static/css/design-system.css). Sin dependencias, sin red: sirve igual en el quiosco sin conexión.
   Todo por DELEGACIÓN de eventos sobre `document` (sirve para HTML generado después) y por atributos `data-gw-*`; no muta el subárbol del elemento que recibe el evento.
   - Tema:       [data-gw-theme-toggle]  claro <-> oscuro POR DISPOSITIVO (localStorage 'gw_theme', con try/catch). La clase del <html> la pone antes de pintar templates/_gw_head.html.
   - Menú:       [data-gw-nav-toggle] dentro de .gw-nav (celular).
   - Ayuda «?»:  .gw-help > [data-gw-help-btn] + .gw-popover ; «Entendido» = [data-gw-help-close]. Foco atrapado, Esc cierra y devuelve el foco.
   - Modal:      [data-gw-open="id"] abre .gw-modal-backdrop#id ; [data-gw-close] lo cierra (Esc también; clic afuera NO: los formularios de datos no se cierran así).
   - Recorrido:  elementos [data-gw-tour-step="n" data-gw-tour-title data-gw-tour-text] dentro de un contenedor con [data-gw-tour="clave"]; se muestra UNA vez por dispositivo
                 (localStorage 'gw_tour_<clave>'); [data-gw-tour-restart="clave"] lo repite. API: window.GW.tour.start(clave, {force:true}).
   - Asistente:  [data-gw-wizard] con [data-gw-wizard-panel], [data-gw-wizard-next], [data-gw-wizard-prev], [data-gw-wizard-count], [data-gw-wizard-bar].
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
      if (label) label.textContent = theme === 'dark' ? 'Tema claro' : 'Tema oscuro';
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
    card.appendChild(count); card.appendChild(title); card.appendChild(text); card.appendChild(foot);
    root.appendChild(spot); root.appendChild(card); document.body.appendChild(root);
    var t = { key: key, root: root, spot: spot, card: card, count: count, title: title, text: text, back: back, next: next, skip: skip, steps: steps, i: 0, opener: document.activeElement,
              onMove: function () { if (tour) tourPlace(tour); } };
    tour = t;
    window.addEventListener('resize', t.onMove); window.addEventListener('scroll', t.onMove, true);
    tourShow(t, 0);
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

  window.GW = { tour: { start: startTour, seen: tourSeen }, theme: { get: currentTheme, set: function (t) { applyTheme(t); store(false, KEY_THEME, t); } }, help: { close: closeHelp }, wizard: { go: wizardGo } };

  function init() {
    applyTheme(currentTheme());
    Array.prototype.forEach.call(document.querySelectorAll('[data-gw-wizard]'), function (w) { wizardGo(w, 0); });
    var auto = document.querySelector('[data-gw-tour][data-gw-tour-auto]');          // recorrido de primera vez: solo si la página lo pide
    if (auto) window.setTimeout(function () { startTour(auto.getAttribute('data-gw-tour')); }, 400);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
