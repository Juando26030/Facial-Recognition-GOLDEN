/* Modo contingencia APAGADO (CONTINGENCY_ENABLED=0): en lugar de static/js/contingency.js la página trae este archivo, que deja el dispositivo limpio si antes lo tuvo encendido: desregistra el
   service worker del quiosco, borra sus cachés (`golden-kiosk-shell-*`) y vacía la copia local de la lista (stores `roster` y `meta` de cada `golden-contingency-*`). La cola de ingresos hechos sin red
   (`queue`/`review`) NO se toca: son datos reales aún sin sincronizar y se pierden solo si alguien los borra a propósito. No define `window.GoldenContingency`: el resto de la página ya lo trata como opcional. */
(function (root) {
  const nav = root.navigator;
  if (nav && nav.serviceWorker && nav.serviceWorker.getRegistrations) {
    nav.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => { if (/\/kiosk\/?$/.test(new URL(r.scope).pathname)) r.unregister(); })).catch(() => {});
  }
  if (root.caches && root.caches.keys) {
    root.caches.keys().then((ks) => ks.filter((k) => k.startsWith('golden-kiosk-shell-')).forEach((k) => root.caches.delete(k))).catch(() => {});
  }
  const idb = root.indexedDB;
  if (idb && idb.databases) {
    idb.databases().then((dbs) => dbs.filter((d) => d.name && d.name.startsWith('golden-contingency-')).forEach((d) => {
      const r = idb.open(d.name);
      r.onsuccess = () => {
        const db = r.result;
        const stores = ['roster', 'meta'].filter((s) => db.objectStoreNames.contains(s));
        if (!stores.length) return db.close();
        const t = db.transaction(stores, 'readwrite');
        stores.forEach((s) => t.objectStore(s).clear());
        t.oncomplete = t.onerror = t.onabort = () => db.close();
      };
    })).catch(() => {});
  }
})(typeof window !== 'undefined' ? window : globalThis);
