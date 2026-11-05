/* Registro touch AUTOMÁTICO (Plan 7): se activa solo en celular o tableta y queda apagado en un PC con mouse. Función pura (se prueba con Node inyectando matchMedia y userAgent).
   Señales: puntero principal grueso (pointer: coarse), sin hover (hover: none), userAgent de móvil/tableta, o iPadOS que se anuncia como Mac pero tiene pantalla táctil. */
(function (root) {
    'use strict';
    const UA_TOUCH = /Android|iPhone|iPad|iPod|Mobile|Tablet|Silk|Kindle|PlayBook/i;
    function detect(env) {
        env = env || {};
        const mm = typeof env.matchMedia === 'function' ? env.matchMedia : null;
        const q = (s) => { try { const r = mm && mm(s); return !!(r && r.matches); } catch (e) { return false; } };
        const ua = String(env.userAgent || '');
        if (q('(pointer: coarse)') || q('(hover: none)')) return true;
        if (UA_TOUCH.test(ua)) return true;
        if (/Macintosh/.test(ua) && (env.maxTouchPoints | 0) > 1) return true;       // iPad con «sitio de escritorio»
        return false;
    }
    function fromWindow(w) {
        w = w || (typeof window !== 'undefined' ? window : {});
        const nav = w.navigator || {};
        return detect({ matchMedia: w.matchMedia ? w.matchMedia.bind(w) : null, userAgent: nav.userAgent, maxTouchPoints: nav.maxTouchPoints });
    }
    const api = { detect, fromWindow };
    if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.GWTouchDetect = api;
})(typeof window !== 'undefined' ? window : this);
