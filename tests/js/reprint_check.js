// Reimpresión con permisos (Fase 1B): static/js/reprint.js (digitador) y static/js/reprint-inbox.js (coordinador), con DOM, red y reloj falsos.
// Correr: node tests/js/reprint_check.js
//  Digitador: habilitada = nada que mostrar · deshabilitada sin permiso = «No se puede reimprimir» + «¿Es una emergencia autorizada?» + «Solicitar permiso» · pendiente / aprobada («Reimprimir ahora») /
//             negada / vencida por el sondeo · sin conexión lo dice y no pide · con permiso aprobado no vuelve a preguntar · `use` gasta el permiso en el servidor (403 = no imprime).
//  Coordinador: el sondeo (X-Gw-Passive) muestra la tarjeta con quién pide, a quién y la hora; Aprobar / Negar envían la decisión; sin sesión deja de preguntar.
//  Estándares: sin alert/confirm/prompt ni onclick en línea ni emojis.
const fs = require('fs');
const assert = require('assert');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.className = ''; this._text = ''; this.listeners = {}; this.parentNode = null; this.id = ''; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; return c; }
  replaceChildren(...cs) { this.children = []; this._text = ''; cs.forEach((c) => this.appendChild(c)); }
  addEventListener(k, f) { this.listeners[k] = f; }
  focus() { this.focused = true; }
  matches(sel) {
    if (sel.startsWith('[') ) { const k = sel.slice(1, -1); return k in this.attrs; }
    if (sel.startsWith('.')) return (' ' + this.className + ' ').includes(' ' + sel.slice(1) + ' ');
    return this.tagName === sel;
  }
  closest(sel) { let n = this; while (n) { if (n.matches && n.matches(sel)) return n; n = n.parentNode; } return null; }
  all() { return this.children.reduce((a, c) => a.concat([c], c.all()), []); }
  querySelector(sel) { return this.all().find((n) => n.matches(sel)) || null; }
  click() { let n = this; while (n) { if (n.listeners.click) { n.listeners.click({ target: this }); break; } n = n.parentNode; } }
}
function newWindow(extra) {
  const body = new El('body');
  const calls = []; const toasts = []; const polls = [];
  const w = {
    document: { body, createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t), visibilityState: 'visible' },
    navigator: { onLine: true }, EVENT_ID: 7, EVENT_REPRINT_DISABLED: true,
    showToast: (m, t) => toasts.push([m, t]),
    GW: { poll: (fn, ms) => { polls.push({ fn, ms }); return polls.length; } },
    clearInterval: () => {}, setInterval: () => 1, addEventListener: () => {},
    fetch: async (url, opts) => { calls.push({ url, opts: opts || {} }); return w.respond(url, opts || {}); },
    respond: () => ({ ok: true, status: 200, json: async () => ({}) }),
    _calls: calls, _toasts: toasts, _polls: polls,
  };
  Object.assign(w, extra || {});
  return w;
}
function load(file, w) {
  const src = fs.readFileSync(file, 'utf8');
  new Function('window', 'module', src.replace(/\(typeof window !== 'undefined' \? window : globalThis\)\)/, '(window))'))(w, undefined);
  return w;
}
const tick = () => new Promise((r) => setImmediate(r));
const texts = (w) => w.document.body.textContent;
const button = (w, act) => w.document.body.all().find((n) => n.getAttribute && n.getAttribute('data-act') === act);
const json = (obj, status) => ({ ok: (status || 200) < 400, status: status || 200, json: async () => obj });

(async () => {
  // --- reglas de estándares
  for (const f of ['static/js/reprint.js', 'static/js/reprint-inbox.js']) {
    const src = fs.readFileSync(f, 'utf8');
    assert(!/\balert\(|\bconfirm\(|\bprompt\(|onclick=/.test(src.replace(/showConfirm|showPrompt/g, '')), f + ': sin alert/confirm/prompt ni onclick');
    assert(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(src), f + ': sin emojis (íconos del sprite)');
  }

  // --- los puntos de la impresión que consultan el permiso (no se tocan los parámetros de impresión)
  const sp = fs.readFileSync('static/js/shared-print.js', 'utf8'); const br = fs.readFileSync('static/js/badge-render.js', 'utf8');
  assert((sp.match(/GWReprint\.check\(/g) || []).length === 3, 'shared-print.js: ruta compartida, USB y Cola piden permiso');
  assert(/GWReprint\.use\(userId, c\.reprint_locked\)/.test(sp), 'USB gasta el permiso antes de imprimir');
  assert(/res\.status === 403 && window\.GWReprint/.test(sp), 'el 403 de la puerta del servidor abre el cuadro');
  assert(/GWReprint\.check\(userId, countData\)/.test(br) && /GWReprint\.use\(userId\)/.test(br), 'badge-render.js: botón manual pide y gasta el permiso');
  assert(fs.readFileSync('tests/test_impresion_parametros_fijos.py', 'utf8').length > 0);

  // --- 1. habilitada: no hay nada que mostrar
  let w = load('static/js/reprint.js', newWindow());
  let g = await w.GWReprint.check('1001', { times_printed: 1, reprint_locked: false, permit: false, request: null });
  assert.deepStrictEqual(g, { ok: true, approved: false }); assert.strictEqual(w.document.body.children.length, 0);
  g = await w.GWReprint.check('1001', { times_printed: 0, reprint_locked: true });
  assert.strictEqual(g.ok, true, 'primera impresión: sin permiso');
  g = await w.GWReprint.check('1001', { times_printed: 1 });
  assert.strictEqual(g.ok, true, 'respuesta vieja del servidor (sin la bandera): como siempre');

  // --- 2. deshabilitada sin permiso: el cuadro, y Cancelar no sigue
  w = load('static/js/reprint.js', newWindow());
  let pending = w.GWReprint.check('1001', { times_printed: 1, reprint_locked: true, permit: false, request: null });
  await tick();
  assert(texts(w).includes('No se puede reimprimir'), 'título');
  assert(texts(w).includes('¿Es una emergencia autorizada?'), 'pregunta');
  assert(button(w, 'ask') && button(w, 'ask').textContent === 'Solicitar permiso');
  assert(w.document.body.children[0].attrs['data-open'] === 'true' && w.document.body.children[0].className === 'gw-modal-backdrop');
  assert(w.document.body.all().some((n) => n.className.includes('gw-modal')), 'usa .gw-modal');
  button(w, 'close').click();
  g = await pending; assert.strictEqual(g.ok, false); assert.strictEqual(w.document.body.children.length, 0);
  assert.strictEqual(w._calls.length, 0, 'cerrar no pide nada');

  // --- 3. pedir → pendiente → aprobada → «Reimprimir ahora»
  w = load('static/js/reprint.js', newWindow());
  w.respond = (url, opts) => {
    if (opts.method === 'POST') return json({ id: 5, status: 'pending', expires_at: '2026-11-05T15:00:00Z', created: true });
    return json({ reprint_locked: true, permit: true, request: { id: 5, status: 'approved', expires_at: '2026-11-05T15:15:00Z' } });
  };
  pending = w.GWReprint.check('1001', { times_printed: 1, reprint_locked: true, permit: false, request: null });
  await tick();
  button(w, 'ask').click(); await tick(); await tick();
  const post = w._calls.find((c) => c.opts.method === 'POST');
  assert.strictEqual(post.url, '/api/events/7/reprint-requests'); assert.deepStrictEqual(JSON.parse(post.opts.body), { user_id: '1001' });
  assert(texts(w).includes('Esperando respuesta del coordinador'), 'pendiente');
  assert.strictEqual(w._polls.length, 1, 'sondea con GW.poll');
  await w._polls[0].fn(); await tick();
  assert(texts(w).includes('Permiso aprobado') && texts(w).includes('una sola reimpresión'), 'aprobada');
  const poll = w._calls.find((c) => c.url.includes('/mine'));
  assert(poll.url.includes('user_id=1001') && poll.opts.headers['X-Gw-Passive'] === '1', 'el sondeo no renueva la sesión');
  assert(button(w, 'go').textContent === 'Reimprimir ahora');
  button(w, 'go').click();
  g = await pending; assert.deepStrictEqual(g, { ok: true, approved: true });

  // --- 4. negada y vencida
  for (const [status, text, canAsk] of [['denied', 'El coordinador negó el permiso', false], ['expired', 'El permiso venció', true]]) {
    w = load('static/js/reprint.js', newWindow());
    pending = w.GWReprint.check('1001', { times_printed: 1, reprint_locked: true, permit: false, request: { id: 5, status } });
    await tick();
    assert(texts(w).includes(text), status);
    assert.strictEqual(!!button(w, 'ask'), canAsk, status + ': puede volver a pedir = ' + canAsk);
    button(w, 'close').click(); assert.strictEqual((await pending).ok, false);
  }

  // --- 5. sin conexión: lo dice y no pide
  w = load('static/js/reprint.js', newWindow());
  w.navigator.onLine = false;
  pending = w.GWReprint.check('1001', { times_printed: 1, reprint_locked: true, permit: false, request: null });
  await tick(); button(w, 'ask').click(); await tick();
  assert(w._toasts.some(([m]) => m === 'Para pedir permiso necesitas conexión.'), 'toast sin conexión');
  assert(texts(w).includes('Para pedir permiso necesitas conexión.'), 'el cuadro lo dice');
  assert.strictEqual(w._calls.length, 0, 'sin red no se pide');
  button(w, 'close').click(); await pending;
  // red que falla al pedir
  w = load('static/js/reprint.js', newWindow()); w.fetch = async () => { throw new Error('net'); };
  pending = w.GWReprint.check('1001', { times_printed: 1, reprint_locked: true, request: null });
  await tick(); button(w, 'ask').click(); await tick(); await tick();
  assert(w._toasts.some(([m]) => m.includes('necesitas conexión')), 'fallo de red = mismo aviso');
  button(w, 'close').click(); await pending;

  // --- 6. con permiso aprobado no vuelve a preguntar
  w = load('static/js/reprint.js', newWindow());
  g = await w.GWReprint.check('1001', { times_printed: 1, reprint_locked: true, permit: true, request: { status: 'approved' } });
  assert.deepStrictEqual(g, { ok: true, approved: true }); assert.strictEqual(w.document.body.children.length, 0);

  // --- 7. use(): gasta el permiso en el servidor
  w = load('static/js/reprint.js', newWindow({ EVENT_REPRINT_DISABLED: false }));
  assert.strictEqual(await w.GWReprint.use('1001'), true); assert.strictEqual(w._calls.length, 0, 'habilitada: no llama');
  w = load('static/js/reprint.js', newWindow());
  w.respond = () => json({ ok: true });
  assert.strictEqual(await w.GWReprint.use('1001'), true);
  assert.strictEqual(w._calls[0].url, '/api/events/7/reprint-requests/use');
  assert.strictEqual(await w.GWReprint.use('1001'), true); assert.strictEqual(w._calls.length, 1, 'las dos llamadas de UNA impresión gastan una sola vez');
  w = load('static/js/reprint.js', newWindow());
  w.respond = () => json({ detail: 'No se puede reimprimir: pide permiso.' }, 403);
  assert.strictEqual(await w.GWReprint.use('1002'), false);
  assert(w._toasts.some(([m, t]) => m.startsWith('No se puede reimprimir') && t === 'error'));

  // --- 8. coordinador: tarjeta con Aprobar / Negar
  w = newWindow(); load('static/js/reprint-inbox.js', w);
  assert.strictEqual(w._polls.length, 1); assert.strictEqual(w._polls[0].ms, 10000, 'cada 10 s con GW.poll');
  const req = { id: 9, event_name: 'Evento Uno', requested_by: 'Digitador Uno', person: 'Ana Prueba', requested_hhmm: '14:32', status: 'pending' };
  w.respond = (url, opts) => (opts.method === 'POST' ? json({ status: 'approved' }) : json({ requests: [req] }));
  await w.GWReprintInbox.poll(); await tick();
  let shown = texts(w);
  for (const t of ['Permiso para reimprimir', 'Evento Uno', 'Digitador Uno', 'Ana Prueba', '14:32', 'Aprobar', 'Negar']) assert(shown.includes(t), 'tarjeta: ' + t);
  assert.strictEqual(w._calls[0].url, '/api/reprint-requests/inbox'); assert.strictEqual(w._calls[0].opts.headers['X-Gw-Passive'], '1');
  await w.GWReprintInbox.poll(); assert.strictEqual(w.document.body.children.length, 1, 'la misma solicitud no abre dos tarjetas');
  const approve = w.document.body.all().find((n) => n.getAttribute('data-decision') === 'approve');
  approve.click(); await tick(); await tick();
  const dec = w._calls.find((c) => c.opts.method === 'POST');
  assert.strictEqual(dec.url, '/api/reprint-requests/9/decision'); assert.deepStrictEqual(JSON.parse(dec.opts.body), { decision: 'approve' });
  assert(w._toasts.some(([m]) => m.startsWith('Permiso aprobado')));
  // negar
  w = newWindow(); load('static/js/reprint-inbox.js', w);
  w.respond = (url, opts) => (opts.method === 'POST' ? json({ status: 'denied' }) : json({ requests: [req] }));
  await w.GWReprintInbox.poll(); await tick();
  w.document.body.all().find((n) => n.getAttribute('data-decision') === 'deny').click(); await tick(); await tick();
  assert.deepStrictEqual(JSON.parse(w._calls.find((c) => c.opts.method === 'POST').opts.body), { decision: 'deny' });
  // sin solicitudes: nada en pantalla; pestaña oculta: no consulta; 401: deja de preguntar
  w = newWindow(); load('static/js/reprint-inbox.js', w);
  w.respond = () => json({ requests: [] }); await w.GWReprintInbox.poll(); assert.strictEqual(w.document.body.children.length, 0);
  w.document.visibilityState = 'hidden'; const n = w._calls.length; await w.GWReprintInbox.poll(); assert.strictEqual(w._calls.length, n, 'oculta: no consulta');
  w.document.visibilityState = 'visible'; w.respond = () => json({}, 401); await w.GWReprintInbox.poll();
  const m = w._calls.length; await w.GWReprintInbox.poll(); assert.strictEqual(w._calls.length, m, 'sin sesión: no vuelve a preguntar');

  console.log('reprint_check: OK');
})().catch((e) => { console.error(e); process.exit(1); });
