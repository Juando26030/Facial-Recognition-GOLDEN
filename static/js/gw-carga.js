/* GoldenWeb 2.0 — Carga visible en TODA la plataforma (9-nov-2026, orden de Juan David: «en ningún botón o acción se pueda pensar que no funcionó»). Guía: docs/ux/CARGAS_Y_ESQUELETOS.md.
   Se carga SIN defer y de primero en _gw_head.html (así envuelve fetch antes de que la pantalla pida sus datos). Sin dependencias. Tres piezas:
   1) Botón ocupado automático: toda petición (fetch o XMLHttpRequest) que arranca hasta 1 s después de pulsar un botón (`button`, `.gw-btn`, `[role=button]`, `input[type=submit|button]`,
      `a[data-gw-action]`) o de enviar un formulario marca ESE botón con aria-busy="true" (la rueda sale de design-system.css) hasta que terminan TODAS sus peticiones (contador por botón),
      con un mínimo visible de 300 ms. Mientras está ocupado, un segundo clic o Enter sobre él se ignora (no hay doble envío). Un botón sin red (abrir una ventana, alternar algo) nunca
      queda ocupado. No toca botones que ya maneja GW.busy / setButtonLoading / la propia pantalla (ya tienen aria-busy o su rueda) ni los marcados con data-gw-busy-off.
   2) Barra delgada arriba (`.gw-loadbar`, role=progressbar, oculta a lectores cuando no hay carga): peticiones nacidas de un gesto que no es un botón (Enter en un buscador, cambiar un
      filtro, escribir con autoguardado) o de la carga de la pantalla, cuando pasan de 400 ms; también al seguir un enlace o enviar un formulario clásico (navegación).
   3) Esqueletos: GW.skeleton(contenedor, { kind: 'table'|'cards'|'list'|'stats'|'block'|'text', rows, cols }) pinta la forma del contenido mientras llega; GW.skeleton.html(opts) da el
      marcado (el mismo de templates/_gw_skeleton.html); GW.skeleton.error(contenedor, { title, text }) deja `.gw-state--error` con «Reintentar». Red de seguridad: si una petición
      falla y queda algún esqueleto a la vista cuando ya no hay nada en curso, se cambia por el estado de error (nunca un esqueleto eterno).
   NUNCA se activa con los sondeos: lo que corre dentro de setInterval / GW.poll / GW.onResume o de un setTimeout de 2 s o más, las peticiones con encabezado X-Gw-Passive
   o keepalive, y /health, /ready, /api/session/*. Para callar algo a mano: GW.quiet(() => fetch(...)).
   La lógica (createTracker, skeletonHtml) se prueba con Node sin DOM: tests/js/gw_carga_check.js. */
(function (root) {
    'use strict';
    const GESTURE_MS = 1000, MIN_VISIBLE_MS = 300, BAR_DELAY_MS = 400, NAV_TIMEOUT_MS = 10000, PAGE_SETTLE_MS = 1500, ERROR_SETTLE_MS = 1500, POLL_TIMEOUT_MS = 2000;
    const ACTION_SEL = 'button, .gw-btn, [role="button"], input[type="submit"], input[type="button"], a[data-gw-action]';
    const QUIET_URL = /\/(health|ready|healthz|readyz)(\?|$)|\/api\/session\//;
    const FILE_URL = /\.(xlsx|xls|csv|pdf|zip|png|jpe?g|docx|txt|json|ics|vcf|pkpass)(\?|#|$)|\/(export|descargar|download)\b/i;

    function attr(el, k) { return el && el.getAttribute ? el.getAttribute(k) : null; }

    /* ------------------------------------------------------------------ lógica pura (inyectable) */
    function createTracker(d) {
        d = d || {};
        const now = d.now || (() => Date.now());
        const later = d.setTimeout || ((f, ms) => setTimeout(f, ms));
        const cancel = d.clearTimeout || ((t) => clearTimeout(t));
        const bar = d.bar || { show() {}, hide() {} };
        const t = { quietDepth: 0, gesture: null, pageLoading: true, inflight: 0, failed: false, onSettledFail: d.onSettledFail || null };
        const btns = new Map();                     // botón -> { n, at, timer }
        let barN = 0, barTimer = null, barShown = false, barAt = 0, barHideTimer = null, failTimer = null;

        t.quiet = function (fn, self, args) {
            t.quietDepth++;
            try { return fn.apply(self, args || []); } finally { t.quietDepth--; }
        };
        const gone = d.isGone || ((el) => el.isConnected === false);
        t.press = function (btn) {
            const g = t.gesture;
            const prev = g && g.btn && g.btn !== btn ? { btn: g.btn, at: g.at } : (g && g.prev) || null;
            t.gesture = { at: now(), btn: btn || null, prev };
        };
        // El botón pulsado ya no está (p. ej. «Sí, archivar» de una confirmación que se cerró): la rueda va al botón que abrió la confirmación, si sigue a la vista.
        function target(g) {
            if (!g.btn || !gone(g.btn)) return g.btn;
            const p = g.prev;
            return p && !gone(p.btn) && now() - p.at <= 120000 ? p.btn : null;
        }
        t.loaded = function () { t.pageLoading = false; };
        t.isBusy = function (btn) { return !!(btn && btns.has(btn) && btns.get(btn).n > 0) || !!(btn && attr(btn, 'data-gw-busy')); };

        function canMark(btn) {
            if (!btn || !btn.setAttribute) return false;
            if (btns.has(btn)) return true;                                                                   // ya es nuestro: suma al contador
            if (attr(btn, 'aria-busy') === 'true') return false;                                              // GW.busy o la pantalla ya lo manejan
            if (btn.closest ? btn.closest('[data-gw-busy-off]') : attr(btn, 'data-gw-busy-off') !== null) return false;
            if (btn.querySelector && btn.querySelector('.golden-btn-spinner, .gw-spinner')) return false;     // setButtonLoading ya puso su rueda
            return true;
        }
        /* Marca visual (la usa también GW.busy): aria-busy + data-gw-busy («static» si el botón no tiene posición propia, para centrar la rueda) + su color en --gw-busy-c
           (el texto se vuelve transparente y la rueda queda del color que tenía el texto; así el botón no cambia de tamaño). Solo atributos: nunca toca el contenido del botón. */
        t.decorate = function (btn) {
            let pos = 'static', color = '';
            try { if (d.styleOf) { const cs = d.styleOf(btn); pos = cs.position || 'static'; color = cs.color || ''; } } catch (e) { /* sin estilos */ }
            btn.setAttribute('data-gw-busy', pos === 'static' ? 'static' : '1');
            btn.setAttribute('aria-busy', 'true');
            if (color && btn.style && btn.style.setProperty) btn.style.setProperty('--gw-busy-c', color);
        };
        t.undecorate = function (btn) {
            btn.removeAttribute('data-gw-busy');
            btn.removeAttribute('aria-busy');
            if (btn.style && btn.style.removeProperty) btn.style.removeProperty('--gw-busy-c');
        };
        function mark(btn) {
            let s = btns.get(btn);
            if (!s) {
                s = { n: 0, at: now(), timer: null };
                btns.set(btn, s);
                t.decorate(btn);
            }
            if (s.timer) { cancel(s.timer); s.timer = null; }
            s.n++;
        }
        function unmark(btn) {
            const s = btns.get(btn);
            if (!s) return;
            s.n = Math.max(0, s.n - 1);
            if (s.n > 0 || s.timer) return;
            const clear = () => {
                s.timer = null;
                if (s.n > 0) return;
                btns.delete(btn);
                if (attr(btn, 'data-gw-busy') !== null) t.undecorate(btn);
            };
            const wait = MIN_VISIBLE_MS - (now() - s.at);
            if (wait > 0) s.timer = later(clear, wait); else clear();
        }
        function barUp() {
            barN++;
            if (barHideTimer) { cancel(barHideTimer); barHideTimer = null; }
            if (barShown || barTimer) return;
            barTimer = later(() => { barTimer = null; if (barN > 0) { barShown = true; barAt = now(); bar.show(); } }, BAR_DELAY_MS);
        }
        function barDown() {
            barN = Math.max(0, barN - 1);
            if (barN > 0) return;
            if (barTimer) { cancel(barTimer); barTimer = null; }                                              // rápida: nunca se vio
            if (!barShown || barHideTimer) return;
            const hide = () => { barHideTimer = null; if (barN === 0 && barShown) { barShown = false; bar.hide(); } };
            const wait = MIN_VISIBLE_MS - (now() - barAt);
            if (wait > 0) barHideTimer = later(hide, wait); else hide();
        }
        t.barVisible = () => barShown;

        /* info: { url, passive, keepalive }. Devuelve una ficha para end(), o null si la petición no se muestra. */
        t.begin = function (info) {
            info = info || {};
            t.inflight++;
            const tok = { counted: true, btn: null, bar: false };
            if (t.quietDepth > 0 || info.passive || info.keepalive || QUIET_URL.test(String(info.url || ''))) return tok;
            const g = t.gesture;
            if (g && now() - g.at <= GESTURE_MS) {
                const btn = target(g);
                if (btn && canMark(btn)) { mark(btn); tok.btn = btn; return tok; }
                if (btn && attr(btn, 'aria-busy') === 'true') return tok;                                    // ya tiene su rueda: sin barra extra
                barUp(); tok.bar = true; return tok;
            }
            if (t.pageLoading) { barUp(); tok.bar = true; }
            return tok;
        };
        t.end = function (tok, failed) {
            if (!tok || tok.done) return;
            tok.done = true;
            if (tok.btn) unmark(tok.btn);
            if (tok.bar) barDown();
            if (tok.counted) t.inflight = Math.max(0, t.inflight - 1);
            if (failed) t.failed = true;
            if (t.inflight === 0 && t.failed && t.onSettledFail) {
                if (failTimer) cancel(failTimer);
                failTimer = later(() => { failTimer = null; if (t.inflight === 0 && t.failed) { t.failed = false; try { t.onSettledFail(); } catch (e) { /* nada */ } } }, ERROR_SETTLE_MS);
            }
        };
        /* Navegación (enlace o formulario clásico): la página se va; botón ocupado y barra hasta que se vaya (o 10 s, por si era una descarga). */
        t.navigate = function (btn) {
            const tok = { counted: false, btn: null, bar: true };
            if (btn && canMark(btn)) { mark(btn); tok.btn = btn; }
            barUp();
            later(() => t.end(tok), NAV_TIMEOUT_MS);
            return tok;
        };
        t.reset = function () {
            btns.forEach((s, btn) => { s.n = 0; if (s.timer) cancel(s.timer); s.timer = null; s.at = -Infinity; btns.delete(btn); if (attr(btn, 'data-gw-busy') !== null) t.undecorate(btn); });
            barN = 0; if (barTimer) cancel(barTimer); barTimer = null; if (barShown) { barShown = false; bar.hide(); }
        };
        return t;
    }

    /* ------------------------------------------------------------------ esqueletos (marcado) */
    const LBL = (s) => String(s == null ? 'Cargando…' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const bone = (cls) => `<span class="gw-skeleton gw-sk__bone${cls ? ' ' + cls : ''}" aria-hidden="true"></span>`;
    function skeletonHtml(o) {
        o = o || {};
        const kind = o.kind || 'list';
        const n = Math.max(1, Math.min(24, Number(o.rows) || ({ table: 6, cards: 4, list: 5, stats: 4, block: 1, text: 3 }[kind] || 4)));
        const sr = `<span class="gw-sr-only" role="status">${LBL(o.label)}</span>`;
        const out = [];
        if (kind === 'table') {
            const cols = Math.max(1, Math.min(12, Number(o.cols) || 4));
            for (let i = 0; i < n; i++) {
                let tds = '';
                for (let c = 0; c < cols; c++) tds += `<td>${i === 0 && c === 0 ? sr : ''}${bone(c === 0 ? 'gw-sk__bone--w80' : (c % 2 ? 'gw-sk__bone--w60' : 'gw-sk__bone--w40'))}</td>`;
                out.push(`<tr class="gw-sk gw-sk--row" data-gw-sk>${tds}</tr>`);
            }
            return out.join('');
        }
        if (kind === 'cards') {
            for (let i = 0; i < n; i++) out.push(`<div class="gw-sk gw-sk--card" data-gw-sk>${i === 0 ? sr : ''}${bone('gw-sk__bone--title')}${bone('gw-sk__bone--w80')}${bone('gw-sk__bone--w60')}${bone('gw-sk__bone--btn')}</div>`);
            return out.join('');
        }
        if (kind === 'stats') {
            let tiles = '';
            for (let i = 0; i < n; i++) tiles += `<div class="gw-sk__tile">${bone('gw-sk__bone--w60')}${bone('gw-sk__bone--num')}</div>`;
            return `<div class="gw-sk gw-sk--stats" data-gw-sk>${sr}${tiles}</div>`;
        }
        if (kind === 'block') return `<div class="gw-sk gw-sk--block" data-gw-sk>${sr}${bone('gw-sk__bone--block')}</div>`;
        if (kind === 'text') {
            let lines = '';
            for (let i = 0; i < n; i++) lines += bone(i === n - 1 ? 'gw-sk__bone--w60' : 'gw-sk__bone--w100');
            return `<div class="gw-sk gw-sk--text" data-gw-sk>${sr}${lines}</div>`;
        }
        let items = '';
        for (let i = 0; i < n; i++) items += `<div class="gw-sk__item">${bone('gw-sk__bone--dot')}<span class="gw-sk__lines">${bone('gw-sk__bone--w80')}${bone('gw-sk__bone--w40')}</span></div>`;
        return `<div class="gw-sk gw-sk--list" data-gw-sk>${sr}${items}</div>`;
    }
    const ERR_ICON = '<svg class="gw-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/></svg>';
    function errorHtml(o) {
        o = o || {};
        const box = `<div class="gw-state gw-state--error" role="alert"><div class="gw-state__icon">${ERR_ICON}</div><p class="gw-state__title">${LBL(o.title || 'No se pudo cargar')}</p>` +
            `<p class="gw-state__text">${LBL(o.text || 'Revisa la conexión e inténtalo de nuevo.')}</p>${o.retry === false ? '' : '<button type="button" class="gw-btn gw-btn--secondary" data-gw-reload>Reintentar</button>'}</div>`;
        return o.cols ? `<tr><td colspan="${Number(o.cols) || 1}">${box}</td></tr>` : box;
    }
    function colsOf(el) {
        try {
            const table = el.closest && el.closest('table');
            const head = table && table.querySelector('thead tr');
            if (head) return Array.from(head.children).reduce((a, c) => a + (Number(c.getAttribute('colspan')) || 1), 0);
        } catch (e) { /* sin tabla */ }
        return 0;
    }
    function skeleton(el, o) {
        if (!el) return;
        o = Object.assign({}, o || {});
        const tag = String(el.tagName || '').toLowerCase();
        if (!o.kind) o.kind = (tag === 'tbody' || tag === 'table') ? 'table' : 'list';
        if (o.kind === 'table' && !o.cols) o.cols = colsOf(el) || 4;
        el.innerHTML = skeletonHtml(o);
    }
    skeleton.html = skeletonHtml;
    skeleton.error = function (el, o) {
        if (!el) return;
        o = Object.assign({}, o || {});
        const tag = String(el.tagName || '').toLowerCase();
        if ((tag === 'tbody' || tag === 'table') && !o.cols) o.cols = colsOf(el) || 1;
        el.innerHTML = errorHtml(o);
    };
    skeleton.errorHtml = errorHtml;

    const api = { createTracker, skeletonHtml, errorHtml, GESTURE_MS, MIN_VISIBLE_MS, BAR_DELAY_MS, ACTION_SEL, FILE_URL };
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

    /* ------------------------------------------------------------------ instalación en el navegador */
    root.GW = Object.assign(root.GW || {}, { skeleton });
    if (root.__gwCarga || typeof document === 'undefined') return;
    root.__gwCarga = true;

    let barEl = null;
    function barNode() {
        if (barEl) return barEl;
        barEl = document.createElement('div');
        barEl.className = 'gw-loadbar';
        barEl.setAttribute('role', 'progressbar');
        barEl.setAttribute('aria-label', 'Cargando');
        barEl.setAttribute('aria-valuetext', 'Cargando');
        barEl.setAttribute('aria-hidden', 'true');
        barEl.innerHTML = '<span class="gw-loadbar__fill"></span>';
        (document.body || document.documentElement).appendChild(barEl);
        return barEl;
    }
    function settleFail() {
        const boxes = new Set();
        document.querySelectorAll('[data-gw-sk]').forEach((sk) => { if (sk.parentElement && sk.getClientRects().length) boxes.add(sk.parentElement); });   // oculto (pestaña cerrada): se deja
        boxes.forEach((box) => {
            const only = Array.from(box.children).every((c) => c.hasAttribute('data-gw-sk') || c.classList.contains('gw-sr-only'));
            if (only) { skeleton.error(box); return; }
            const sks = box.querySelectorAll(':scope > [data-gw-sk]');                                     // hay más cosas en la caja: solo se cambia el esqueleto
            sks.forEach((sk, i) => { if (i === 0) sk.outerHTML = errorHtml({ cols: sk.tagName === 'TR' ? (colsOf(sk) || sk.children.length) : 0 }); else sk.remove(); });
        });
    }
    const tracker = createTracker({
        bar: { show() { const b = barNode(); b.setAttribute('aria-hidden', 'false'); b.setAttribute('data-active', ''); }, hide() { if (barEl) { barEl.setAttribute('aria-hidden', 'true'); barEl.removeAttribute('data-active'); } } },
        styleOf: (el) => getComputedStyle(el),
        isGone: (el) => !el.isConnected || !el.getClientRects().length,
        onSettledFail: settleFail,
    });
    root.GWLoad = tracker;
    root.GW.quiet = (fn) => tracker.quiet(fn);

    function describe(input, init) {
        let url = '', passive = false, keepalive = !!(init && init.keepalive);
        try { url = typeof input === 'string' ? input : (input && (input.url || input.href)) || String(input); } catch (e) { url = ''; }
        try {
            const h = (init && init.headers) || (input && typeof input === 'object' && input.headers);
            if (h) passive = String(typeof h.get === 'function' ? h.get('X-Gw-Passive') : (h['X-Gw-Passive'] || h['x-gw-passive'] || '')) === '1';
        } catch (e) { /* sin encabezados */ }
        return { url, passive, keepalive };
    }

    if (typeof root.fetch === 'function') {
        const orig = root.fetch;
        root.fetch = function (input, init) {
            let tok = null;
            try { tok = tracker.begin(describe(input, init)); } catch (e) { tok = null; }
            let p;
            try { p = orig.apply(this, arguments); } catch (e) { tracker.end(tok, true); throw e; }
            return p.then((r) => { tracker.end(tok, !!(r && r.status >= 500)); return r; }, (e) => { tracker.end(tok, !(e && e.name === 'AbortError')); throw e; });
        };
    }
    if (root.XMLHttpRequest && root.XMLHttpRequest.prototype) {
        const P = root.XMLHttpRequest.prototype, open = P.open, send = P.send;
        P.open = function (m, url) { this.__gwUrl = url; return open.apply(this, arguments); };
        P.send = function () {
            const tok = tracker.begin({ url: this.__gwUrl });
            this.addEventListener('loadend', () => tracker.end(tok, this.status === 0 || this.status >= 500));
            return send.apply(this, arguments);
        };
    }
    // Sondeos: lo que corre dentro de un setInterval no enciende nada (GW.poll lo usa por dentro); tampoco un setTimeout de 2 s o más (sondeos encadenados
    // como Turnos, TV o el turno público, y reintentos). Un setTimeout corto (buscador con espera de 300 ms) sí cuenta como parte del gesto.
    const si = root.setInterval, st = root.setTimeout;
    root.setInterval = function (fn) {
        const args = Array.prototype.slice.call(arguments);
        if (typeof fn === 'function') args[0] = function () { return tracker.quiet(fn, this, arguments); };
        return si.apply(root, args);
    };
    root.setTimeout = function (fn, ms) {
        const args = Array.prototype.slice.call(arguments);
        if (typeof fn === 'function' && Number(ms) >= POLL_TIMEOUT_MS) args[0] = function () { return tracker.quiet(fn, this, arguments); };
        return st.apply(root, args);
    };

    function actionOf(target) { return target && target.closest ? target.closest(ACTION_SEL) : null; }
    // Fase de captura en window: corre antes que cualquier manejador de la pantalla.
    root.addEventListener('click', (e) => {
        const el = actionOf(e.target);
        if (el && tracker.isBusy(el)) { e.preventDefault(); e.stopImmediatePropagation(); return; }    // ocupado: el segundo clic no hace nada
        tracker.press(el && !el.disabled ? el : null);
    }, true);
    ['keydown', 'change', 'input'].forEach((ev) => root.addEventListener(ev, (e) => {
        if (ev === 'keydown' && (e.key === 'Enter' || e.key === ' ') && actionOf(e.target)) return;      // la tecla sobre un botón termina en clic
        if (!tracker.gesture || Date.now() - tracker.gesture.at > 50) tracker.press(null);
    }, true));
    root.addEventListener('submit', (e) => {
        const sub = e.submitter && actionOf(e.submitter);
        if (sub && tracker.isBusy(sub)) { e.preventDefault(); e.stopImmediatePropagation(); return; }    // Enter otra vez mientras envía
        tracker.press(sub || null);
    }, true);
    // Fase de burbuja: si nadie lo detuvo, el navegador navega (formulario clásico o enlace).
    root.addEventListener('submit', (e) => {
        const f = e.target;
        if (e.defaultPrevented || !f || (attr(f, 'target') || '').toLowerCase() === '_blank' || (attr(f, 'method') || '').toLowerCase() === 'dialog') return;
        tracker.navigate(e.submitter && actionOf(e.submitter));
    });
    root.addEventListener('click', (e) => {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
        if (!a || a.hasAttribute('download') || (a.target && a.target !== '_self') || a.closest('[data-gw-busy-off]')) return;
        const href = a.getAttribute('href') || '';
        if (!href || href[0] === '#' || /^(javascript|mailto|tel|sms|blob|data):/i.test(href) || /^\/api\//.test(href) || FILE_URL.test(href)) return;     // /api/… desde un enlace = descarga
        try { const u = new URL(a.href, location.href); if (u.origin !== location.origin || (u.pathname === location.pathname && u.search === location.search && u.hash)) return; } catch (err) { return; }
        tracker.navigate(a.matches(ACTION_SEL) ? a : null);
    });
    root.addEventListener('pageshow', (e) => { if (e.persisted) tracker.reset(); });                        // volver con «Atrás»: nada queda girando
    const settle = () => setTimeout(() => tracker.loaded(), PAGE_SETTLE_MS);
    if (document.readyState === 'complete') settle(); else root.addEventListener('load', settle);
    document.addEventListener('click', (e) => { if (e.target.closest && e.target.closest('[data-gw-reload]')) location.reload(); });
})(typeof window !== 'undefined' ? window : globalThis);
