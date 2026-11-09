/* Autorregistro sin base de datos (Fase 8, pieza 3). Pantalla de autoservicio: la persona escribe sus datos; la pantalla se reinicia sola tras cada registro y tras un rato sin tocarla.
   No capta rostro ni foto. Los datos van a POST /api/events/{id}/selfreg (app/routers/selfreg.py). */
(function () {
    'use strict';
    var CFG = window.SELFREG || {};
    var API = '/api/events/' + CFG.eventId + '/selfreg';
    var IDLE_MS = 90 * 1000;          // sin tocar: se borran los datos escritos (privacidad en un equipo compartido)
    var DONE_MS = 6 * 1000;           // tras registrar, vuelve sola al formulario vacío
    var $ = function (id) { return document.getElementById(id); };
    var fields = [], busy = false, idleTimer = null, doneTimer = null;

    function notice(text) { var n = $('notice'); n.hidden = !text; n.textContent = text || ''; }

    function build(list) {
        var box = $('fields');
        box.textContent = '';
        fields = list;
        list.forEach(function (f) {
            var wrap = document.createElement('div');
            var id = 'f_' + f.key;
            if (f.type === 'boolean' || f.type === 'consent') {
                wrap.className = 'gw-autoreg__check';
                var cb = document.createElement('input');
                cb.type = 'checkbox'; cb.id = id; cb.dataset.key = f.key;
                var lb = document.createElement('label');
                lb.htmlFor = id; lb.textContent = f.label + (f.required ? ' *' : '');
                wrap.appendChild(cb); wrap.appendChild(lb);
            } else {
                wrap.className = 'gw-field';
                var l = document.createElement('label');
                l.className = 'gw-label'; l.htmlFor = id; l.textContent = f.label + (f.required ? ' *' : '');
                var el;
                if (f.type === 'select' && f.options && f.options.length) {
                    el = document.createElement('select'); el.className = 'gw-select';
                    var blank = document.createElement('option'); blank.value = ''; blank.textContent = 'Elige una opción'; el.appendChild(blank);
                    f.options.forEach(function (o) { var op = document.createElement('option'); op.value = o; op.textContent = o; el.appendChild(op); });
                } else if (f.type === 'text_long') {
                    el = document.createElement('textarea'); el.className = 'gw-textarea'; el.rows = 3;
                } else {
                    el = document.createElement('input'); el.className = 'gw-input';
                    el.type = f.type === 'email' ? 'email' : (f.type === 'date' ? 'date' : 'text');
                    if (f.key === 'id') { el.inputMode = 'numeric'; el.maxLength = 20; }
                    if (f.key === 'phone') el.inputMode = 'tel';
                }
                el.id = id; el.dataset.key = f.key; el.autocomplete = 'off';
                wrap.appendChild(l); wrap.appendChild(el);
                if (f.help) { var h = document.createElement('p'); h.className = 'gw-hint'; h.textContent = f.help; wrap.appendChild(h); }
            }
            box.appendChild(wrap);
        });
    }

    function readValues() {
        var out = { id: '', first_name: '', last_name: '', values: {} };
        fields.forEach(function (f) {
            var el = $('f_' + f.key);
            var v = el.type === 'checkbox' ? (el.checked ? 'Sí' : '') : el.value.trim();
            if (f.key === 'id' || f.key === 'first_name' || f.key === 'last_name') out[f.key] = v;
            else out.values[f.key] = v;
        });
        return out;
    }

    function missing() {
        for (var i = 0; i < fields.length; i++) {
            var f = fields[i], el = $('f_' + f.key);
            var v = el.type === 'checkbox' ? el.checked : el.value.trim();
            if (f.required && !v) return f.label;
        }
        return null;
    }

    function resetForm() {
        clearTimeout(doneTimer);
        $('done').hidden = true; notice('');
        build(fields);
        $('form').hidden = false; busy = false; $('send').disabled = false;
        armIdle();
    }

    function armIdle() {
        clearTimeout(idleTimer);
        idleTimer = setTimeout(function () { if (!busy && !$('form').hidden) resetForm(); }, IDLE_MS);
    }

    function finish(text) {
        $('form').hidden = true; $('doneText').textContent = text; $('done').hidden = false;
        doneTimer = setTimeout(resetForm, DONE_MS);
    }

    async function submit(ev) {
        ev.preventDefault();
        if (busy) return;
        var m = missing();
        if (m) { window.showToast && window.showToast('Falta: ' + m, 'warn'); return; }
        busy = true; $('send').disabled = true;
        try {
            var r = await fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(readValues()) });
            var d = await r.json().catch(function () { return {}; });
            if (r.ok) { finish(d.message || '¡Listo! Quedaste registrado.'); return; }
            window.showToast && window.showToast(d.detail || 'No pudimos registrarte. Acércate al punto de ayuda.', 'warn');
            if (r.status === 403 || r.status === 429) { $('form').hidden = true; notice(d.detail || ''); }
        } catch (e) {
            window.showToast && window.showToast('Sin conexión. Intenta de nuevo en un momento.', 'warn');
        }
        busy = false; $('send').disabled = false; armIdle();
    }

    async function init() {
        try {
            var r = await fetch(API.replace(/selfreg$/, 'selfreg/form'), { cache: 'no-store' });
            var d = await r.json();
            if (!r.ok) { notice(d.detail || 'No se pudo abrir el autorregistro.'); return; }
            if (!d.available) {
                notice(d.reason === 'closed' ? 'El registro de este evento no está abierto en este momento.' : (d.reason === 'unsupported' ? 'El autorregistro no está listo. Acércate al punto de ayuda.' : 'El autorregistro no está activo en este evento.'));
                return;
            }
            build(d.fields);
            $('form').hidden = false;
            $('form').addEventListener('submit', submit);
            ['input', 'change', 'pointerdown', 'keydown'].forEach(function (t) { document.addEventListener(t, armIdle, true); });
            armIdle();
        } catch (e) { notice('No se pudo abrir el autorregistro. Revisa la conexión.'); }
    }
    init();
})();
