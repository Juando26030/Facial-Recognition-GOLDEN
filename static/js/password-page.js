/* Contraseña: al enviar un formulario válido, el botón muestra la rueda (aria-busy) y no admite un segundo envío. */
(function () {
  "use strict";
  document.addEventListener("submit", function (e) {
    const form = e.target;
    if (!form.matches || !form.matches("form[data-gw-busy-form]")) return;
    const btn = form.querySelector('button[type="submit"]');
    if (!btn) return;
    if (btn.getAttribute("aria-busy") === "true") { e.preventDefault(); return; }
    // password-policy.js puede cancelar el envío (requisitos sin cumplir): se mira después de que corran todos los oyentes.
    setTimeout(function () { if (!e.defaultPrevented) btn.setAttribute("aria-busy", "true"); }, 0);
  });
  // Si el navegador vuelve a esta página desde el historial, el botón no debe quedar girando.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll('form[data-gw-busy-form] button[aria-busy]').forEach(function (b) { b.removeAttribute("aria-busy"); });
  });
})();
