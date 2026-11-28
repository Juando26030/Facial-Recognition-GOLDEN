/* Orum — logo que se adapta al fondo (28-nov-2026). Cada <img data-gw-orum data-src-claro="…" data-src-oscuro="…"> usa el logo de tinta azul sobre fondos claros y el blanco sobre fondos oscuros.
   Detecta el color de fondo REAL: sube por los contenedores hasta el primer fondo que no sea transparente (y si no hay, el de la página). Se vuelve a calcular al cambiar el tema
   (data-theme de <html>) y al redimensionar. Sin dependencias ni red. Sin JS queda el logo de tinta azul (el de fondos claros). */
(function () {
  'use strict';
  function rgba(str) {
    var m = /rgba?\(([^)]+)\)/.exec(str || '');
    if (!m) return null;
    var p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 && !isNaN(p[3]) ? p[3] : 1 };
  }
  function lin(c) { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
  function luminance(c) { return 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b); }
  function backgroundOf(el) {
    for (var n = el.parentElement; n; n = n.parentElement) {
      var c = rgba(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0.6) return c;
    }
    var root = rgba(getComputedStyle(document.body).backgroundColor);
    return root && root.a > 0.6 ? root : { r: 255, g: 255, b: 255, a: 1 };
  }
  function isDark(el) { return luminance(backgroundOf(el)) < 0.25; }
  function apply() {
    var imgs = document.querySelectorAll('img[data-gw-orum]');
    for (var i = 0; i < imgs.length; i++) {
      var img = imgs[i], want = isDark(img) ? img.getAttribute('data-src-oscuro') : img.getAttribute('data-src-claro');
      if (want && img.getAttribute('src') !== want) img.setAttribute('src', want);
    }
  }
  window.GWOrumLogo = { refresh: apply, isDark: isDark };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply); else apply();
  try { new MutationObserver(apply).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] }); } catch (e) { /* sin observador: queda el cálculo inicial */ }
  window.addEventListener('resize', apply);
})();
