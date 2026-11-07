/* Papelera para vaciar un buscador (6-nov-2026, pedido de Juan David): en TODO campo donde se busca aparece, DENTRO del borde del campo y a la derecha, una papelera que lo vacía y vuelve a buscar.
   No cambia el tamaño ni el lugar del campo: el botón se coloca encima (position: absolute) usando el mismo contenedor posicionado que el campo, y solo se ve cuando hay texto.
   Campos que cubre: todo <input type="search"> y los que lleven data-gw-clearable (cédula, nombre, entidad, escáner, etc.). También los que se dibujan después (listas, ventanas). */
(function () {
  'use strict';
  if (window.__gwClearLoaded) return;
  window.__gwClearLoaded = true;
  var SELECTOR = 'input[type="search"], input[data-gw-clearable]';
  var wired = new WeakSet();

  function iconHref() {
    var u = document.querySelector('use[href*="icons.svg"]');
    var href = u && u.getAttribute('href');
    return href ? href.split('#')[0] + '#i-trash' : (window.GW_ICON_URL ? window.GW_ICON_URL + '#i-trash' : '');
  }

  function wire(input) {
    if (wired.has(input)) return;
    
    if (input.hasAttribute('data-gw-noclear') || !input.parentNode) return;
    wired.add(input);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'gw-clearbtn';
    btn.setAttribute('aria-label', 'Vaciar búsqueda');
    btn.title = 'Vaciar búsqueda';
    btn.hidden = true;
    var href = iconHref();
    btn.innerHTML = href ? '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="' + href + '"/></svg>' : '×';
    input.insertAdjacentElement('afterend', btn);
    input.classList.add('gw-has-clearbtn');

    function place() {
      if (btn.hidden) return;
      var h = btn.offsetHeight || 32, w = btn.offsetWidth || 32;
      btn.style.top = (input.offsetTop + Math.max(0, (input.offsetHeight - h) / 2)) + 'px';
      btn.style.left = (input.offsetLeft + input.offsetWidth - w - 6) + 'px';
    }
    function sync() {
      var show = !!input.value && input.offsetParent !== null;
      if (btn.hidden === !show) { place(); return; }
      btn.hidden = !show;
      place();
    }
    input.addEventListener('input', sync);
    input.addEventListener('change', sync);
    input.addEventListener('focus', sync);
    // Otro código vacía o llena el campo sin disparar eventos (p. ej. después de acreditar): se revisa al volver el foco o el ratón.
    document.addEventListener('pointerover', function (e) { if (e.target === input || e.target === btn) sync(); }, true);
    if (window.ResizeObserver) { var ro = new ResizeObserver(sync); ro.observe(input); if (input.parentNode.nodeType === 1) ro.observe(input.parentNode); }
    window.addEventListener('resize', sync);
    btn.addEventListener('mousedown', function (e) { e.preventDefault(); });         // el clic no le quita el foco al campo
    btn.addEventListener('click', function () {
      var own = document.getElementById(input.getAttribute('data-gw-clear-btn') || '');          // un botón de vaciado propio de la pantalla (hace más cosas que vaciar), si lo hay
      if (own) { own.click(); }
      else {
        input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      sync();
      input.focus();
    });
    sync();
  }

  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    if (root.matches && root.matches(SELECTOR)) wire(root);
    root.querySelectorAll(SELECTOR).forEach(wire);
  }
  function start() {
    scan(document);
    if (window.MutationObserver) new MutationObserver(function (list) {
      list.forEach(function (m) { m.addedNodes.forEach(function (n) { if (n.nodeType === 1) scan(n); }); });
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
