/* Guardado global de «Parámetros del evento» (Plan 6). Un solo botón «Guardar» para todo lo pendiente.
   - Cada bloque de la pantalla se REGISTRA con GWParams.register({ key, label, order, save, reload }); `save()` usa el endpoint de siempre y lanza Error(mensaje) si falla.
   - Cualquier cambio en un campo dentro de [data-psave="clave"] deja esa clave PENDIENTE (GWParams.markDirty). Lo que esté dentro de [data-pnodirty] (campos de prueba, buscadores, "agregar") no cuenta.
   - saveAll() corre los bloques pendientes en orden, sigue aunque uno falle y reporta cuáles fallaron; los que salieron bien quedan limpios. Si alguno pide recargar (reload:true) y no hubo fallos, recarga al final.
   - Acciones destructivas (borrar campo, purgar, borrar puesto...) NO pasan por aquí: siguen inmediatas con showConfirm.
   - La pestaña (sección) que se estaba viendo se recuerda por dispositivo solo como comodidad (localStorage dentro de try/catch; sin él, todo funciona).
   La lógica (createController) no toca el DOM: se prueba con Node (tests/js/params_save_check.js). */
(function (root) {
    'use strict';

    function createController(opts) {
        opts = opts || {};
        const mods = new Map();                 // key -> { key, label, order, save, reload }
        const dirty = new Set();
        const rev = new Map();                  // key -> contador de ediciones (si se edita mientras se guarda, queda pendiente)
        let busy = false;
        let state = 'idle';                     // idle | dirty | saving | saved | error
        let failed = [];
        let wantReload = false;

        function sortedDirty() {
            return Array.from(dirty).map((k) => mods.get(k)).filter(Boolean).sort((a, b) => a.order - b.order);
        }
        function snapshot() {
            const list = sortedDirty();
            return { state, busy, dirty: list.map((m) => m.key), labels: list.map((m) => m.label), failed: failed.slice() };
        }
        const emit = () => { if (typeof opts.onChange === 'function') opts.onChange(snapshot()); };

        function register(m) {
            if (!m || !m.key || typeof m.save !== 'function') throw new Error('módulo inválido');
            mods.set(m.key, { key: m.key, label: m.label || m.key, order: typeof m.order === 'number' ? m.order : 100, save: m.save, reload: !!m.reload });
        }
        function markDirty(key) {
            if (!mods.has(key)) return;
            rev.set(key, (rev.get(key) || 0) + 1);
            dirty.add(key);
            if (!busy) { state = 'dirty'; failed = []; }
            emit();
        }
        function markClean(key) {
            dirty.delete(key);
            if (!busy && dirty.size === 0 && state === 'dirty') state = 'idle';
            emit();
        }
        const hasDirty = () => dirty.size > 0;
        const requestReload = () => { wantReload = true; };

        async function run(list) {
            if (busy || !list.length) return { saved: [], failed: [] };
            busy = true; state = 'saving'; failed = []; emit();
            const done = [];
            for (const m of list) {
                const before = rev.get(m.key) || 0;
                try {
                    await m.save();
                    if ((rev.get(m.key) || 0) === before) dirty.delete(m.key);       // si lo editaron mientras guardaba, sigue pendiente
                    done.push(m);
                } catch (e) {
                    failed.push({ key: m.key, label: m.label, error: (e && e.message) || 'error' });
                    dirty.add(m.key);
                }
            }
            busy = false;
            state = failed.length ? 'error' : (dirty.size ? 'dirty' : 'saved');
            const needReload = (wantReload || done.some((m) => m.reload)) && !failed.length && dirty.size === 0;
            emit();
            if (needReload) { wantReload = false; if (typeof opts.reload === 'function') opts.reload(); }
            return { saved: done.map((m) => m.key), failed: failed.slice() };
        }
        const saveAll = () => run(sortedDirty());
        // Botones por bloque que siguen ocultos en el DOM (compatibilidad): guarda solo ese bloque, esté o no marcado.
        const saveKey = (key) => (mods.has(key) ? run([mods.get(key)]) : Promise.resolve({ saved: [], failed: [] }));
        // Si una acción inmediata depende de un bloque pendiente (p. ej. agregar una zona con el módulo recién activado), primero se guarda ese bloque.
        const flush = (key) => (dirty.has(key) ? saveKey(key) : Promise.resolve({ saved: [], failed: [] }));

        return { register, markDirty, markClean, hasDirty, saveAll, saveKey, flush, requestReload, snapshot };
    }

    /* ------------------------------------------------------------ Capa de pantalla (solo en el navegador) */
    function bindDom(doc, win) {
        const rootEl = doc.getElementById('paramsRoot');
        const bar = doc.getElementById('paramsSaveBar');
        if (!rootEl || !bar) return null;
        const btn = doc.getElementById('paramsSaveBtn');
        const statusEl = doc.getElementById('paramsSaveStatus');
        const failEl = doc.getElementById('paramsSaveFail');
        const STORE = rootEl.dataset.tabsKey ? 'gw_tab_' + rootEl.dataset.tabsKey : 'gw_params_tab';          // otras pantallas (Fase 1.5) ponen data-tabs-key para recordar SU pestaña
        const ICONS = bar.dataset.icons || '';

        // ---- Pestañas: una sección visible a la vez; la última vista se recuerda por dispositivo (comodidad; sin almacenamiento todo funciona igual).
        const tabs = Array.from(rootEl.querySelectorAll('[role="tab"][data-tab]'));
        const panelOf = (tab) => doc.getElementById(tab.getAttribute('aria-controls'));
        let saved = null;
        try { saved = JSON.parse(win.localStorage.getItem(STORE) || 'null'); } catch (e) { saved = null; }
        function select(name, focus) {
            const tab = tabs.find((t) => t.dataset.tab === name) || tabs[0];
            if (!tab) return;
            tabs.forEach((t) => {
                const on = t === tab;
                t.setAttribute('aria-selected', on ? 'true' : 'false');
                t.tabIndex = on ? 0 : -1;
                const p = panelOf(t);
                if (p) p.hidden = !on;
            });
            if (focus) tab.focus();
            try { win.localStorage.setItem(STORE, JSON.stringify(tab.dataset.tab)); } catch (e) { /* sin almacenamiento: no pasa nada */ }
            // Aviso «esta pestaña se ve»: las secciones que cargan al abrirse (Estados, Alertas, Catálogo) lo escuchan, también si se llegó con el teclado o al recordar la última pestaña.
            try { tab.dispatchEvent(new win.CustomEvent('gw:tabshow', { bubbles: true })); } catch (e) { /* sin eventos: queda el clic */ }
        }
        tabs.forEach((t, i) => {
            t.addEventListener('click', () => select(t.dataset.tab));
            t.addEventListener('keydown', (e) => {                 // flechas, Inicio y Fin cambian de pestaña (teclado)
                const k = e.key;
                const to = { ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[k];
                if (to === undefined) return;
                e.preventDefault();
                select(tabs[(to + tabs.length) % tabs.length].dataset.tab, true);
            });
        });
        select(typeof saved === 'string' ? saved : (tabs[0] && tabs[0].dataset.tab));
        const tabsOf = (key) => tabs.filter((t) => { const p = panelOf(t); return !!(p && p.querySelector('[data-psave="' + key + '"]')); });

        const iconHtml = (name) => '<svg class="gw-icon" aria-hidden="true"><use href="' + ICONS.replace(/"/g, '') + '#i-' + name + '"></use></svg>';

        function render(s) {
            bar.dataset.state = s.state;
            btn.disabled = s.busy || (s.state !== 'dirty' && s.state !== 'error');
            if (s.busy) btn.setAttribute('aria-busy', 'true'); else btn.removeAttribute('aria-busy');
            const badge = doc.createElement('span');
            badge.className = 'gw-badge' + ({ dirty: ' gw-badge--warn', saved: ' gw-badge--ok', error: ' gw-badge--err', saving: ' gw-badge--info' }[s.state] || '');
            const ico = { dirty: 'alert', saved: 'check', error: 'error' }[s.state];
            if (ico && ICONS) badge.insertAdjacentHTML('afterbegin', iconHtml(ico));
            badge.appendChild(doc.createTextNode({ dirty: 'Cambios sin guardar', saving: 'Guardando…', saved: 'Guardado', error: 'No todo se guardó' }[s.state] || 'Sin cambios pendientes'));
            if (s.state === 'dirty') {                      // alerta clara: barra de color, signo de alerta rojo y texto en negrita
                const alert = doc.createElement('span');
                alert.className = 'gw-savebar__alert';
                if (ICONS) alert.insertAdjacentHTML('afterbegin', iconHtml('alert'));
                alert.appendChild(doc.createTextNode('Cambios sin guardar'));
                statusEl.replaceChildren(alert);
            } else statusEl.replaceChildren(badge);
            if (s.state === 'dirty' && s.labels.length) { const t = doc.createElement('span'); t.className = 'gw-text-sm gw-muted'; t.textContent = 'En: ' + s.labels.join(', '); statusEl.appendChild(t); }
            failEl.replaceChildren();
            if (s.state === 'error') {
                s.failed.forEach((f) => { const li = doc.createElement('li'); li.textContent = f.label + ': ' + f.error; failEl.appendChild(li); });
                const li = doc.createElement('li'); li.textContent = 'Lo demás sí se guardó. Corrige lo anterior y pulsa «Guardar cambios» otra vez.'; failEl.appendChild(li);
                failEl.hidden = false;
                const first = s.failed.map((f) => tabsOf(f.key)[0]).find(Boolean);       // lleva a la primera pestaña con un fallo
                if (first) select(first.dataset.tab);
            } else failEl.hidden = true;
            tabs.forEach((t) => {
                const flag = t.querySelector('[data-group-pending]');
                if (flag) flag.hidden = !s.dirty.some((k) => tabsOf(k).includes(t));
            });
        }

        const ctl = createController({ onChange: (s) => { render(s); syncVisibility(); }, reload: () => win.location.reload() });
        btn.addEventListener('click', async () => {
            const r = await ctl.saveAll();
            if (typeof win.showToast !== 'function') return;
            if (r.failed.length) win.showToast('No se guardó: ' + r.failed.map((f) => f.label).join(', ') + '. Lo demás sí.', 'error');
            else if (r.saved.length) win.showToast('Cambios guardados', 'success');
        });

        // ---- Detección de cambios: cualquier campo dentro de [data-psave] (salvo [data-pnodirty]) deja su bloque pendiente.
        const onEdit = (e) => {
            const t = e.target;
            if (!t || !t.closest || t.closest('[data-pnodirty]')) return;
            const editable = /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName) || t.isContentEditable;
            if (!editable || (t.tagName === 'INPUT' && /^(button|submit|file)$/.test(t.type))) return;
            const holder = t.closest('[data-psave]');
            if (holder) ctl.markDirty(holder.dataset.psave);
        };
        rootEl.addEventListener('input', onEdit);
        rootEl.addEventListener('change', onEdit);

        // Ctrl o Cmd + S guarda (igual que el botón); si no hay nada pendiente, no hace nada pero tampoco abre «Guardar página como…»
        doc.addEventListener('keydown', (e) => {
            if (!(e.ctrlKey || e.metaKey) || e.altKey || String(e.key).toLowerCase() !== 's') return;
            e.preventDefault();
            if (!btn.disabled) btn.click();
        });

        win.addEventListener('beforeunload', (e) => {
            if (!ctl.hasDirty()) return undefined;
            e.preventDefault(); e.returnValue = '';
            return '';
        });
        // La barra solo aparece donde hay algo que guardar: sin ningún bloque editable ([data-psave]) en la pantalla y sin cambios pendientes, se oculta (pantallas de consulta).
        function syncVisibility() {
            const quiet = ctl.snapshot().state === 'idle' && !rootEl.querySelector('[data-psave]');
            bar.classList.toggle('gw-savebar--vacia', quiet);
        }
        try { new win.MutationObserver(syncVisibility).observe(rootEl, { childList: true, subtree: true }); } catch (e) { /* sin observador: se revisa en cada cambio de estado */ }
        render(ctl.snapshot());
        syncVisibility();
        return ctl;
    }

    const api = { createController, bindDom };
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

    // Navegador: un controlador único; los bloques se registran con GWParams.register(...) desde los scripts de la página (se encolan hasta que el DOM esté listo).
    const queue = [];
    let ctl = null;
    const when = (f) => (ctl ? f(ctl) : queue.push(f));
    const ready = () => {
        ctl = bindDom(root.document, root) || createController({ reload: () => root.location.reload() });
        queue.splice(0).forEach((f) => f(ctl));
    };
    root.GWParams = {
        register: (m) => when((c) => c.register(m)),
        markDirty: (k) => when((c) => c.markDirty(k)),
        markClean: (k) => when((c) => c.markClean(k)),
        saveKey: (k) => new Promise((res) => when((c) => res(c.saveKey(k)))),
        flush: (k) => new Promise((res) => when((c) => res(c.flush(k)))),
        requestReload: () => when((c) => c.requestReload()),
        hasDirty: () => (ctl ? ctl.hasDirty() : false),
    };
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', ready); else ready();
})(typeof window !== 'undefined' ? window : globalThis);
