/* Service worker del quiosco con el modo contingencia APAGADO (CONTINGENCY_ENABLED=0): no intercepta nada; al activarse borra los cachés del caparazón (`golden-kiosk-shell-*`) y se desregistra. Así un navegador que lo
   tenía de antes (p. ej. del staging) queda limpio en su siguiente visita. `/kiosk/sw.js` sirve este archivo cuando la variable está apagada. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try { for (const k of await caches.keys()) if (k.startsWith('golden-kiosk-shell-')) await caches.delete(k); } catch (e) { /* sin cachés que borrar */ }
    await self.registration.unregister();
  })());
});
