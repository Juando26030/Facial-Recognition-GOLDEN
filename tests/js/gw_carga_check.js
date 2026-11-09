// Prueba de la carga visible automática (static/js/gw-carga.js): botón ocupado por gesto, contador por botón, mínimo visible, sin doble clic, barra superior con retraso,
// sondeos que no encienden nada, navegación y esqueletos. Node puro: reloj y temporizadores falsos, botones de mentira (sin DOM real). Correr: node tests/js/gw_carga_check.js
const assert = require('assert');
const fs = require('fs');
const { createTracker, skeletonHtml, errorHtml } = require('../../static/js/gw-carga.js');

function clock() {
    const c = { t: 1000, q: [], id: 0 };
    c.now = () => c.t;
    c.setTimeout = (fn, ms) => { const id = ++c.id; c.q.push({ id, at: c.t + ms, fn }); return id; };
    c.clearTimeout = (id) => { c.q = c.q.filter((x) => x.id !== id); };
    c.advance = (ms) => { const end = c.t + ms; for (;;) { c.q.sort((a, b) => a.at - b.at); const n = c.q[0]; if (!n || n.at > end) break; c.q.shift(); c.t = n.at; n.fn(); } c.t = end; };
    return c;
}
function btn(opts) {
    opts = opts || {};
    const a = Object.assign({}, opts.attrs || {});
    const props = {};
    return {
        attrs: a, props, isConnected: opts.connected !== false,
        getAttribute: (k) => (k in a ? a[k] : null), setAttribute: (k, v) => { a[k] = String(v); }, removeAttribute: (k) => { delete a[k]; }, hasAttribute: (k) => k in a,
        style: { setProperty: (k, v) => { props[k] = v; }, removeProperty: (k) => { delete props[k]; } },
        closest: (sel) => (sel === '[data-gw-busy-off]' && 'data-gw-busy-off' in a ? {} : null),
        querySelector: (sel) => (opts.spinner && /golden-btn-spinner/.test(sel) ? {} : null),
    };
}
function make() {
    const c = clock(); const bar = { shows: 0, hides: 0, on: false, show() { this.shows++; this.on = true; }, hide() { this.hides++; this.on = false; } };
    const fails = [];
    const t = createTracker({ now: c.now, setTimeout: c.setTimeout, clearTimeout: c.clearTimeout, bar, styleOf: () => ({ position: 'static', color: 'rgb(1, 2, 3)' }), isGone: (el) => el.isConnected === false, onSettledFail: () => fails.push(c.t) });
    t.loaded();
    return { c, t, bar, fails };
}

// 1) clic + petición dentro de 1 s: el botón queda ocupado (atributos, color), y se limpia al terminar respetando el mínimo de 300 ms
let { c, t, bar } = make();
let b = btn();
t.press(b); c.advance(200);
let k = t.begin({ url: '/api/x' });
assert.strictEqual(b.attrs['aria-busy'], 'true'); assert.strictEqual(b.attrs['data-gw-busy'], 'static'); assert.strictEqual(b.props['--gw-busy-c'], 'rgb(1, 2, 3)');
assert.ok(t.isBusy(b), 'ocupado: el segundo clic se ignora');
c.advance(50); t.end(k);
assert.strictEqual(b.attrs['aria-busy'], 'true', 'rápida: sigue visible hasta 300 ms');
c.advance(260); assert.ok(!('aria-busy' in b.attrs) && !('data-gw-busy' in b.attrs) && !('--gw-busy-c' in b.props), 'limpio después del mínimo');
assert.ok(!t.isBusy(b)); assert.strictEqual(bar.shows, 0, 'con botón no hay barra');

// 2) varias peticiones del mismo gesto: ocupado hasta que terminan TODAS
({ c, t, bar } = make()); b = btn();
t.press(b); const k1 = t.begin({ url: '/a' }); c.advance(300); const k2 = t.begin({ url: '/b' });
c.advance(500); t.end(k1); c.advance(1000); assert.strictEqual(b.attrs['aria-busy'], 'true', 'falta una');
t.end(k2); assert.ok(!('aria-busy' in b.attrs), 'ya pasó el mínimo: se limpia al instante');
t.end(k2); // doble end no rompe

// 3) pasado 1 s del clic, la petición no se pega al botón; sin carga de pantalla, tampoco barra
({ c, t, bar } = make()); b = btn();
t.press(b); c.advance(1200); k = t.begin({ url: '/tarde' }); assert.ok(!('aria-busy' in b.attrs)); c.advance(2000); assert.strictEqual(bar.shows, 0); t.end(k);

// 4) botones que ya manejan su carga: GW.busy (aria-busy ya puesto), setButtonLoading (su rueda), data-gw-busy-off
({ c, t, bar } = make());
for (const other of [btn({ attrs: { 'aria-busy': 'true' } }), btn({ spinner: true }), btn({ attrs: { 'data-gw-busy-off': '' } })]) {
    t.press(other); k = t.begin({ url: '/x' }); assert.ok(!('data-gw-busy' in other.attrs), 'no se duplica'); t.end(k);
}
assert.strictEqual(bar.shows, 0, 'botón con su propia rueda: sin barra extra');

// 5) sondeos: dentro de quiet (setInterval / GW.poll / onResume), con X-Gw-Passive, keepalive o /health → nada
({ c, t, bar } = make()); b = btn(); t.press(b);
t.quiet(() => { k = t.begin({ url: '/api/tv' }); }); assert.ok(!('aria-busy' in b.attrs)); t.end(k);
for (const info of [{ url: '/x', passive: true }, { url: '/x', keepalive: true }, { url: '/health' }, { url: '/ready' }, { url: '/api/session/ping' }]) { k = t.begin(info); assert.ok(!('aria-busy' in b.attrs), JSON.stringify(info)); t.end(k); }
assert.strictEqual(t.quiet((a, b2) => a + b2, null, [2, 3]), 5, 'quiet devuelve y pasa argumentos');
assert.throws(() => t.quiet(() => { throw new Error('x'); })); assert.strictEqual(t.quietDepth, 0, 'quiet se limpia aunque falle');

// 6) barra: gesto sin botón (Enter, filtro), solo si pasa de 400 ms; mínimo visible 300 ms; nunca para las rápidas
({ c, t, bar } = make());
t.press(null); k = t.begin({ url: '/buscar' }); c.advance(300); t.end(k); c.advance(1000); assert.strictEqual(bar.shows, 0, 'rápida: sin parpadeo');
t.press(null); k = t.begin({ url: '/buscar' }); c.advance(450); assert.ok(bar.on, 'lenta: barra'); c.advance(50); t.end(k); assert.ok(bar.on, 'mínimo visible'); c.advance(300); assert.ok(!bar.on);
// dos peticiones solapadas: una sola barra
t.press(null); const a1 = t.begin({ url: '/1' }); const a2 = t.begin({ url: '/2' }); c.advance(500); t.end(a1); c.advance(400); assert.ok(bar.on); t.end(a2); c.advance(400); assert.ok(!bar.on); assert.strictEqual(bar.shows, 2);

// 7) carga de la pantalla: sin gesto, la barra sale mientras la página carga; luego no
({ c, t, bar } = make()); t.pageLoading = true;
k = t.begin({ url: '/api/list' }); c.advance(500); assert.ok(bar.on, 'carga inicial con barra'); t.end(k); c.advance(400); assert.ok(!bar.on);
t.loaded(); k = t.begin({ url: '/api/poll' }); c.advance(800); assert.ok(!bar.on, 'después de cargar, sin gesto: nada'); t.end(k);

// 8) el botón pulsado desapareció (confirmación cerrada): la rueda va al botón que abrió la confirmación
({ c, t, bar } = make()); const opener = btn(); const yes = btn({ connected: false });
t.press(opener); c.advance(3000); t.press(null); t.press(yes); k = t.begin({ url: '/api/archive' });
assert.strictEqual(opener.attrs['aria-busy'], 'true', 'el botón original muestra la carga'); t.end(k); c.advance(400); assert.ok(!('aria-busy' in opener.attrs));
// …y si tampoco está, barra
({ c, t, bar } = make()); const gone1 = btn({ connected: false }); const gone2 = btn({ connected: false }); t.press(gone1); t.press(gone2); k = t.begin({ url: '/x' }); c.advance(500); assert.ok(bar.on); t.end(k);

// 9) navegación (enlace / formulario clásico): botón ocupado + barra; se apaga sola a los 10 s (descarga) y reset() limpia todo (volver con «Atrás»)
({ c, t, bar } = make()); b = btn(); t.navigate(b); assert.strictEqual(b.attrs['aria-busy'], 'true'); c.advance(500); assert.ok(bar.on);
c.advance(10000); assert.ok(!bar.on && !('aria-busy' in b.attrs), 'se apaga sola');
b = btn(); t.navigate(b); c.advance(500); t.reset(); assert.ok(!bar.on && !('aria-busy' in b.attrs) && !t.isBusy(b));

// 10) red de seguridad: si algo falla y ya no queda nada en curso, se avisa (esqueletos → error) una sola vez y tras un respiro
let fails; ({ c, t, bar, fails } = make());
const f1 = t.begin({ url: '/a' }); const f2 = t.begin({ url: '/b' }); t.end(f1, true); c.advance(3000); assert.deepStrictEqual(fails, [], 'aún hay una en curso');
t.end(f2); c.advance(1000); assert.deepStrictEqual(fails, []); const g = t.begin({ url: '/c' }); c.advance(1000); assert.deepStrictEqual(fails, [], 'una nueva petición pospone el aviso'); t.end(g); c.advance(1600); assert.strictEqual(fails.length, 1);
c.advance(5000); assert.strictEqual(fails.length, 1, 'una sola vez');

// 11) esqueletos: forma pedida, texto para lectores, marca data-gw-sk y error con «Reintentar»
const rows = skeletonHtml({ kind: 'table', rows: 3, cols: 5 });
assert.strictEqual((rows.match(/<tr /g) || []).length, 3); assert.strictEqual((rows.match(/<td>/g) || []).length, 15); assert.strictEqual((rows.match(/role="status"/g) || []).length, 1);
assert.ok(/data-gw-sk/.test(rows) && /aria-hidden="true"/.test(rows));
assert.strictEqual((skeletonHtml({ kind: 'cards', rows: 4 }).match(/gw-sk--card/g) || []).length, 4);
assert.strictEqual((skeletonHtml({ kind: 'stats', rows: 3 }).match(/gw-sk__tile/g) || []).length, 3);
assert.strictEqual((skeletonHtml({ kind: 'list', rows: 2 }).match(/gw-sk__item/g) || []).length, 2);
assert.ok(/gw-sk--block/.test(skeletonHtml({ kind: 'block' })) && /gw-sk--text/.test(skeletonHtml({ kind: 'text' })));
assert.ok(/Cargando eventos/.test(skeletonHtml({ label: 'Cargando eventos' })) && !/<b>/.test(skeletonHtml({ label: '<b>x' })), 'etiqueta escapada');
assert.strictEqual((skeletonHtml({ kind: 'table', rows: 999 }).match(/<tr /g) || []).length, 24, 'tope de filas');
const err = errorHtml({ cols: 4 }); assert.ok(/^<tr><td colspan="4">/.test(err) && /gw-state--error/.test(err) && /data-gw-reload/.test(err) && /role="alert"/.test(err));
assert.ok(!/data-gw-reload/.test(errorHtml({ retry: false })));

// 12) el macro de Jinja y el ayudante JS producen las mismas clases
const macro = fs.readFileSync('templates/_gw_skeleton.html', 'utf8');
for (const cls of ['gw-sk--row', 'gw-sk--card', 'gw-sk--stats', 'gw-sk__tile', 'gw-sk--block', 'gw-sk--text', 'gw-sk--list', 'gw-sk__item', 'gw-sk__lines', 'gw-sk__bone--title', 'gw-sk__bone--btn', 'gw-sk__bone--num', 'gw-sk__bone--dot', 'data-gw-sk']) assert.ok(macro.includes(cls), cls);

// 13) el CSS tiene la rueda para cualquier botón, la barra, el movimiento reducido sin giro y los esqueletos
const css = fs.readFileSync('static/css/design-system.css', 'utf8');
for (const needle of [':where(.gw-page) button[data-gw-busy]', '[role="button"][data-gw-busy]', '--gw-busy-c', '.gw-loadbar', '.gw-loadbar__fill', 'gw-busy-fade', '.gw-sk--card', '.gw-sk--stats']) assert.ok(css.includes(needle), needle);
const reduced = css.slice(css.lastIndexOf('@media (prefers-reduced-motion: reduce)'));
assert.ok(/gw-busy-fade[^;]*!important/.test(reduced) && !/gw-spin/.test(reduced.split('}')[0] + reduced.split('}')[1]), 'movimiento reducido: late, no gira');

// 14) se carga de primero y sin defer en la cabeza común, y nunca en las páginas públicas congeladas ni en la impresión
const head = fs.readFileSync('templates/_gw_head.html', 'utf8');
assert.ok(/<script src="\{\{ url_for\('static', path='js\/gw-carga\.js'\) \}\}"><\/script>/.test(head), 'sin defer');
assert.ok(head.indexOf('gw-carga.js') < head.indexOf('gw-busy.js'));
for (const f of ['badge_print.html', 'impresion_usb.html', 'roulette_display.html']) assert.ok(!fs.readFileSync('templates/' + f, 'utf8').includes('gw-carga.js'), f);
console.log('gw-carga.js: botón ocupado, barra, sondeos, navegación, red de seguridad y esqueletos OK');
