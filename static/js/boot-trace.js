/* Marcas de tiempo del ARRANQUE del quiosco, por fase (diagnóstico de la recarga sin red). Siempre registra (un arreglo en memoria, costo nulo); imprime en la consola con `?trace=1` en la URL.
   Uso, con la página ya cargada (también sin red):   copy(JSON.stringify(await GoldenTrace.report(), null, 1))
   Trae: `marks` (t = ms desde que empezó la navegación: page:*, contingency:*, directory:*), `navigation` (respuesta, DOMContentLoaded, load), `resources` (cada archivo: inicio, duración,
   tamaño transferido: 0 = salió del service worker/caché) y `sw` (lo que hizo el service worker con cada petición: red, timeout→copia, error→copia, sin copia; con sus ms). */
(function (root) {
  const t0 = () => (root.performance ? root.performance.now() : 0);            // performance.now() cuenta desde el inicio de la navegación
  const marks = [];
  const verbose = /[?&]trace=1\b/.test((root.location && root.location.search) || '');
  function mark(name, extra) {
    const m = Object.assign({ t: Math.round(t0()), name }, extra || {});
    marks.push(m);
    if (verbose && root.console) root.console.log('[trace] +' + m.t + ' ms ' + name + (extra ? ' ' + JSON.stringify(extra) : ''));
    return m;
  }
  function swLog() {                                    // pide al service worker su registro (null si no hay worker o no contesta en 1,5 s)
    const nav = root.navigator;
    const sw = nav && nav.serviceWorker && (nav.serviceWorker.controller);
    if (!sw) return Promise.resolve(null);
    return new Promise((resolve) => {
      const ch = new root.MessageChannel();
      const timer = root.setTimeout(() => resolve(null), 1500);
      ch.port1.onmessage = (e) => { root.clearTimeout(timer); resolve(e.data && e.data.log || null); };
      sw.postMessage({ type: 'trace' }, [ch.port2]);
    });
  }
  async function report() {
    const p = root.performance;
    const nav = p && p.getEntriesByType ? p.getEntriesByType('navigation')[0] : null;
    const r = (x) => Math.round(x);
    return {
      url: root.location && root.location.pathname, online: root.navigator && root.navigator.onLine, marks,
      navigation: nav ? { responseStart: r(nav.responseStart), responseEnd: r(nav.responseEnd), domInteractive: r(nav.domInteractive), domContentLoaded: r(nav.domContentLoadedEventEnd), load: r(nav.loadEventEnd) } : null,
      resources: ((p && p.getEntriesByType && p.getEntriesByType('resource')) || []).map((e) => ({ name: e.name.replace(root.location.origin, ''), type: e.initiatorType, start: r(e.startTime), ms: r(e.duration), bytes: e.transferSize })),
      sw: await swLog(),
    };
  }
  root.GoldenTrace = { mark, report, marks };
  mark('page:script-start');
  if (root.document) {
    root.document.addEventListener('DOMContentLoaded', () => mark('page:DOMContentLoaded'));
    root.addEventListener('load', () => mark('page:load'));
  }
})(typeof window !== 'undefined' ? window : globalThis);
