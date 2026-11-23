/* CRM - «Plegar todo / Desplegar todo» también para lo que cada pantalla pinta DESPUÉS de cargar (gw-ui.js hace el trabajo; aquí solo se le avisa cuando cambia la pantalla).
   Es una espera de ~0,2 s tras un cambio de la pantalla (para agrupar varios): no hay sondeos ni nada que se repita solo. No depende de crm_common.js. */
(function () {
  "use strict";
  const main = document.querySelector("main[data-gw-fold]"); if (!main || !window.MutationObserver) return;
  let t = null;
  new MutationObserver(() => { clearTimeout(t); t = setTimeout(() => { if (window.GW && window.GW.fold) window.GW.fold.refresh(); }, 200); }).observe(main, { childList: true, subtree: true });
})();
