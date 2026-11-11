/* Configuración del autorregistro (templates/kiosk_autoregistro.html) leída de los data-* de <main>: reemplaza el <script> en línea (CSP, tests/test_csp_trinquete.py). Va antes de selfreg.js. */
(function () {
  'use strict';
  var box = document.querySelector('[data-selfreg-event]');
  if (!box) return;
  var id = box.getAttribute('data-selfreg-event');
  window.SELFREG = { eventId: Number(id), backUrl: '/kiosk/' + id + '/registro' };
})();
