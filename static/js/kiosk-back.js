/* «Volver al kiosco» (11-nov-2026): en toda pantalla de un evento (/kiosco/<id>/<sección>) el botón aparece a la izquierda del título,
   para volver al kiosco del evento de un clic. Se pone solo: busca el título principal de la página (h1) y lo envuelve en una fila. */
(function () {
  'use strict';
  var m = location.pathname.match(/^\/kiosk\/(\d+)\/[^/]+/);
  if (!m || !document.getElementById('gwSidebar') || document.querySelector('[data-gw-back]')) return;
  function run() {
    var main = document.querySelector('main') || document.body;
    var title = main.querySelector('h1') || main.querySelector('.golden-section-title h2') || main.querySelector('h2');
    if (!title || title.closest('[data-gw-back-row]')) return;
    var a = document.createElement('a');
    a.href = '/kiosk/' + m[1];
    a.className = 'gw-btn gw-btn--secondary gw-btn--sm gw-backbtn';
    a.setAttribute('data-gw-back', '');
    a.textContent = '← Volver al kiosco';
    var row = document.createElement('div');
    row.className = 'gw-backrow';
    row.setAttribute('data-gw-back-row', '');
    title.parentNode.insertBefore(row, title);
    row.appendChild(a);
    row.appendChild(title);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
})();
