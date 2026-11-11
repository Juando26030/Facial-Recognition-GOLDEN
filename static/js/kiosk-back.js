/* «Volver al kiosco» (11-nov-2026): en toda pantalla de un evento (/kiosk/<id>/<sección>) un botón dorado, distinto de los demás, vive en la franja azul
   «Cliente · Evento · Código» (a la izquierda), así no mueve el título. Si la pantalla no tiene esa franja, queda en una fila propia sobre el contenido. Se pone solo. */
(function () {
  'use strict';
  var m = location.pathname.match(/^\/kiosk\/(\d+)\/[^/]+/);
  if (!m || !document.getElementById('gwSidebar') || document.querySelector('[data-gw-back]')) return;
  function run() {
    var a = document.createElement('a');
    a.href = '/kiosk/' + m[1];
    a.className = 'gw-backchip';
    a.setAttribute('data-gw-back', '');
    a.setAttribute('aria-label', 'Volver al kiosco del evento');
    a.textContent = '← Volver al kiosco';
    var inner = document.querySelector('.golden-event-strip-inner');
    if (inner) { inner.insertBefore(a, inner.firstChild); return; }
    var main = document.querySelector('main') || document.body;
    var row = document.createElement('div');
    row.className = 'gw-backrow';
    row.appendChild(a);
    main.insertBefore(row, main.firstChild);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
})();
