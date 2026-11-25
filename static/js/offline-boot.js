/* Arranque del trabajo SIN RED en Control de áreas y Control de inventario (25-nov-2026, docs/28_CONTINGENCIA_COMPLETA.md): la misma contingencia del Registro (copia cifrada, bandeja de
   salida y service worker). Lo carga templates/_offline_boot.html ANTES del script de la pantalla; el rol viene en data-staff-role de su propia etiqueta. */
(function () {
  'use strict';
  if (!window.GoldenContingency || !window.EVENT_ID) return;
  const me = document.currentScript;
  window.STAFF_ROLE = window.STAFF_ROLE || (me && me.dataset.staffRole) || '';
  window.GoldenContingency.init({ eventId: window.EVENT_ID });
  const gc = window.GoldenContingency.instance;
  if (window.GoldenOutbox) window.GoldenOutbox.init({ eventId: window.EVENT_ID }).then((box) => {
    if (!box.supported || !window.GoldenOutboxUI) return;
    const ui = window.GoldenOutboxUI.mount({ outbox: box });
    gc.onChange((st) => { if (st === 'normal') Promise.resolve(gc.syncQueue ? gc.syncQueue(true) : null).catch(() => {}).then(() => ui.sync(false)); });          // primero los ingresos, después la bandeja
    ui.tick();
  });
  if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/kiosk/sw.js').then(() => navigator.serviceWorker.ready).then((reg) => {
    const Q = window.QrScanner || {};
    const urls = [location.origin + location.pathname, ...performance.getEntriesByType('resource').map((e) => e.name).filter((n) => n.startsWith(location.origin + '/static/')),
      ...[Q.JSQR_URL, Q.READERS_URL, Q.FOTO_URL].filter(Boolean).map((u) => location.origin + u)];
    const send = () => { const sw = navigator.serviceWorker.controller || reg.active; if (sw) sw.postMessage({ type: 'precache', urls }); };
    send();
    navigator.serviceWorker.addEventListener('controllerchange', send);
  }).catch(() => {}));
})();
