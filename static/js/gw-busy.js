/* GoldenWeb 2.0 — «Trabajando…» en cualquier botón que dispara una petición (Fase 1.5, regla R2).
   GW.busy(boton, trabajo[, { slowMs, slowText }]) → promesa con lo que devuelva `trabajo` (una función que devuelve promesa, o una promesa).
   - Mientras trabaja: aria-busy="true" (la rueda girando sale de design-system.css: `.gw-btn[aria-busy="true"]::before`) y el botón no admite un segundo clic (devuelve la misma promesa).
   - Si pasa de `slowMs` (8 s): el texto del botón (si es solo texto) pasa a «Sigue trabajando…» y vuelve al terminar.
   - Siempre se limpia al terminar, con éxito o con error (el error se vuelve a lanzar: quien llama decide qué mostrar).
   Sin dependencias; la lógica no toca nada más que el botón recibido (se prueba con Node: tests/js/gw_busy_check.js). */
(function (root) {
    'use strict';
    const pending = new WeakMap();

    function busy(btn, work, opts) {
        opts = opts || {};
        if (!btn) return Promise.resolve(typeof work === 'function' ? work() : work);
        if (pending.has(btn)) return pending.get(btn);                          // doble clic: no se lanza otra petición
        const slowMs = opts.slowMs === undefined ? 8000 : opts.slowMs;
        const slowText = opts.slowText || 'Sigue trabajando…';
        const textOnly = !btn.children || btn.children.length === 0;
        const original = textOnly ? btn.textContent : null;
        const deco = root.GWLoad && root.GWLoad.decorate;                        // misma rueda centrada que la carga automática (static/js/gw-carga.js)
        if (deco) deco(btn); else btn.setAttribute('aria-busy', 'true');
        const timer = slowMs > 0 ? setTimeout(() => { if (textOnly) btn.textContent = slowText; btn.setAttribute('data-gw-slow', '1'); }, slowMs) : null;
        let p;
        try { p = Promise.resolve(typeof work === 'function' ? work() : work); } catch (e) { p = Promise.reject(e); }
        const done = () => {
            if (timer) clearTimeout(timer);
            pending.delete(btn);
            if (deco) root.GWLoad.undecorate(btn); else btn.removeAttribute('aria-busy');
            if (btn.hasAttribute('data-gw-slow')) { btn.removeAttribute('data-gw-slow'); if (textOnly) btn.textContent = original; }
        };
        const tracked = p.then((v) => { done(); return v; }, (e) => { done(); throw e; });
        pending.set(btn, tracked);
        return tracked;
    }

    const api = { busy };
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
    root.GW = Object.assign(root.GW || {}, api);
})(typeof window !== 'undefined' ? window : globalThis);
