// El letrero de contingencia NO tapa nada (25-nov-2026, pedido de Juan David: en el celular tapaba «Guardar»). Correr: node tests/js/contingency_banner_check.js
// Comprueba: reserva su espacio (--gw-banner-h + hoja de estilos que baja página, ventanas, menú y barras pegadas), lo libera al quitarse, usa texto corto en pantallas pequeñas y se
// reajusta al girar; y que cada chequeo de salud avisa a sus oyentes (la bandeja reintenta sola) y `noteNetFail` adelanta el chequeo. La revisión visual real (5 tamaños de pantalla en
// Chrome) está en tests/lab_contingencia.
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');
const { settle } = require('./settle');

(async () => {
  global.setInterval = () => 1;
  const vars = {}, head = [], listeners = {};
  const win = { innerWidth: 1280, innerHeight: 800, addEventListener: (k, f) => { listeners[k] = f; } };
  const mkEl = () => { const e = { style: {}, dataset: {}, attrs: {}, children: [], textContent: '', setAttribute(k, v) { this.attrs[k] = v; }, appendChild(x) { this.children.push(x); }, addEventListener() {}, remove() { const i = body.children.indexOf(this); if (i >= 0) body.children.splice(i, 1); },
    classList: { toggle() {}, add() {}, remove() {} }, getBoundingClientRect() { return { height: e.textContent.length > 90 ? 58.4 : 33.2 }; } }; return e; };
  const body = { children: [], appendChild(x) { this.children.push(x); }, classList: { toggle() {} } };
  const doc = { body, head: { appendChild: (x) => head.push(x) }, documentElement: { style: { setProperty: (k, v) => { vars[k] = v; } } }, defaultView: win, createElement: mkEl, getElementById: (id) => head.find((x) => x.id === id) || null, addEventListener() {}, visibilityState: 'visible' };
  let net = true, healthCalls = 0;
  const fetchFake = async (url) => { const u = new URL(url, 'http://x'); if (u.pathname === '/health') { healthCalls++; if (!net) throw new TypeError('Failed to fetch'); return { ok: true, status: 200, json: async () => ({}) }; } if (!net) throw new TypeError('Failed to fetch'); return { ok: true, status: 200, headers: { get: () => null }, json: async () => ({}) }; };
  const c = C.create({ idb: fakeIndexedDB(), fetch: fetchFake, now: () => Date.now(), document: doc, subtle: crypto.subtle, eventId: 7, uuid: () => '00000000-0000-4000-8000-000000000001', setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout });
  await c.start(); await settle();
  const banner = () => body.children.find((x) => x.attrs && x.attrs['data-golden-banner'] === '1');
  assert.ok(!banner() && (vars['--gw-banner-h'] === undefined || vars['--gw-banner-h'] === '0px'), 'con red no hay letrero ni espacio reservado');

  const heard = []; c.onHealth((ok) => heard.push(ok));
  net = false; await c.checkHealth(); await c.checkHealth(); await settle();
  assert.deepStrictEqual(heard, [false, false], 'cada chequeo avisa a sus oyentes');
  assert.ok(c.active(), 'dos fallos: contingencia');
  let b = banner(); assert.ok(b && /MODO CONTINGENCIA \(sin conexión\): sigue trabajando; todo se guarda en este dispositivo/.test(b.textContent), b && b.textContent);
  assert.strictEqual(vars['--gw-banner-h'], '59px', 'publica su alto (redondeado hacia arriba)');
  const css = head.find((x) => x.id === 'gw-banner-space'); assert.ok(css, 'hoja de estilos del espacio reservado');
  for (const need of ['html body{padding-top:var(--gw-banner-h', '.gw-modal-backdrop', '.gw-registro__overlay', '.gw-outbox__modal', '.golden-sidebar', '.gw-nav', '.gw-search', '.gw-workarea__bar', 'max-height:calc(100dvh - var(--gw-banner-h'])
    assert.ok(css.textContent.includes(need), 'el espacio reservado cubre: ' + need);
  assert.ok(/position:fixed; top:0/.test(b.style.cssText) && /box-sizing:border-box/.test(b.style.cssText));

  // celular (o al girarlo): texto corto, y el espacio se recalcula
  win.innerWidth = 390; listeners.resize(); b = banner();
  assert.ok(/^Sin conexión: todo se guarda aquí y se envía al volver la red/.test(b.textContent) && b.textContent.length < 90, b.textContent);
  assert.strictEqual(vars['--gw-banner-h'], '34px'); assert.strictEqual(head.filter((x) => x.id === 'gw-banner-space').length, 1, 'la hoja no se duplica');
  win.innerWidth = 780; win.innerHeight = 390; listeners.resize(); assert.ok(/^Sin conexión:/.test(banner().textContent), 'celular horizontal: también corto');

  // la red vuelve: el letrero se quita y el espacio se libera
  const before = healthCalls; c.checking = false; c.noteNetFail(); await settle(); assert.ok(healthCalls > before, 'noteNetFail adelanta el chequeo de salud');
  net = true; await c.checkHealth(); await c.checkHealth(); await c.checkHealth(); await settle();
  assert.ok(!c.active()); assert.ok(heard.includes(true));
  if (!banner()) assert.strictEqual(vars['--gw-banner-h'], '0px', 'sin letrero no queda espacio reservado');
  console.log('contingency_banner_check: OK');
})().catch((e) => { console.error(e); process.exit(1); });
