// Prueba de la pantalla de autorización biométrica (static/js/consent-gate.js) con DOM, IndexedDB y red falsos. Correr: node tests/js/consent_gate_check.js
// Comprueba: aceptación vigente → cámara sin pantalla; sin aceptación → pantalla completa y el registro lleva la HUELLA del texto; variante tercero exige la casilla de mayoría de edad;
// rechazo → cédula/QR; sin red → la decisión queda en la cola local (con huella, sin cédula) y se sincroniza una sola vez; `every_scan`; camino 2 (token de un clic).
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');
const G = require('../../static/js/consent-gate.js');

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.attrs = {}; this.disabled = false; this.checked = false; this.textContent = ''; this.parentNode = null; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
  addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); }
  setAttribute(k, v) { this.attrs[k] = v; }
  focus() {}
  click() { (this.listeners.click || []).forEach((f) => f()); }
  change() { (this.listeners.change || []).forEach((f) => f()); }
  find(pred) { for (const c of this.children) { if (pred(c)) return c; const r = c.find(pred); if (r) return r; } return null; }
}
const doc = { body: new El('body'), head: new El('head'), createElement: (t) => new El(t), getElementById: () => null, visibilityState: 'visible', addEventListener() {} };
const screen = () => doc.body.children.find((c) => c.dataset.consentScreen);
const btn = (a) => screen().find((c) => c.dataset.action === a);

const BLOCK = { version: 'v1.1_kiosk_propio', variant: 'golden', hash: 'a'.repeat(64), title: 'AUTORIZACIÓN', body: ['uno', 'dos'], buttons: ['ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL', 'PREFIERO INGRESAR CON DOCUMENTO / QR'], adult_checkbox: null, blocked: [], mode: 'once', click_mode: false,
  every_scan: { question: '¿Deseas ingresar mediante reconocimiento facial voluntario?', yes: 'SÍ, USAR ROSTRO', no: 'NO, PREFIERO DIGITAR CÉDULA' } };
let net = true, accepted = new Set(), posts = [], block = BLOCK, clickOk = true;
const json = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data, headers: { get: () => null } });
const fetchFake = async (url, opts) => {
  if (!net) throw new TypeError('Failed to fetch');
  const u = new URL(url, 'http://x'), m = (opts && opts.method) || 'GET';
  if (u.pathname.endsWith('/consent-text')) return json(200, block);
  if (u.pathname.includes('/consent-status/')) return json(200, { accepted: accepted.has(decodeURIComponent(u.pathname.split('/').pop())), last: null, mode: block.mode });
  if (u.pathname.endsWith('/consents') && m === 'POST') { const b = JSON.parse(opts.body); posts.push(b); b.entries.forEach((e) => { if (e.decision === 'accept' && e.adult) accepted.add(e.user_id || 'h:' + e.h); }); return json(200, { inserted: b.entries.length, duplicated: 0, unknown: 0 }); }
  if (u.pathname.endsWith('/consent-click')) return clickOk ? json(200, { click_token: 'TOKEN', ttl_s: 120 }) : json(409, { detail: 'no' });
  if (u.pathname === '/health') return json(200, {});
  if (u.pathname.endsWith('/local-roster')) return json(200, { v: 'v1', generated_at: 'x', max_age_s: 86400, event: { id: 1, status: 'en_proceso', auto_register: false }, salt: 'd'.repeat(32), count: 1, people: [{ h: await fp('1001'), n: 'Ana', c: [], s: 'No registrado', a: 1 }], consent: block });
  if (u.pathname === '/api/ping-auth') return json(200, {});
  throw new Error('ruta inesperada ' + u.pathname);
};
const hex = (b) => Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, '0')).join('');
const fp = async (c) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${'d'.repeat(32)}:${c}`))).slice(0, 16);
const tick = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 20; i++) await tick(); };
let n = 0; const uuid = () => `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}`;

(async () => {
  global.setInterval = () => 1;
  const GC = C.create({ idb: fakeIndexedDB(), fetch: fetchFake, now: () => Date.now(), document: doc, subtle: crypto.subtle, eventId: 1, uuid, setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout });
  await GC.start(); await settle();
  const mk = () => G.create({ document: doc, fetch: fetchFake, eventId: 1, gc: () => GC, uuid, device: 'tablet-1' });

  // 1) aceptación vigente (en línea): directo a la cámara, sin pantalla
  accepted.add('1001');
  let g = mk(); assert.strictEqual(await g.ensure('1001'), 'camera'); assert.ok(!screen(), 'no se muestra la pantalla si ya aceptó');

  // 2) sin aceptación: pantalla completa; botón 1 → registra (con la huella del texto) y enciende la cámara
  let p = g.ensure('2002'); await settle();
  assert.ok(screen() && screen().attrs['aria-modal'] === 'true', 'pantalla completa modal');
  assert.strictEqual(btn('accept').textContent, BLOCK.buttons[0]); assert.strictEqual(btn('reject').textContent, BLOCK.buttons[1]);
  assert.ok(!screen().find((c) => c.tagName === 'input'), 'variante propia: la declaración de mayoría de edad va DENTRO del texto: sin casilla aparte');
  btn('accept').click(); assert.strictEqual(await p, 'camera'); assert.ok(!screen());
  const e = posts[posts.length - 1].entries[0];
  assert.strictEqual(e.text_hash, BLOCK.hash); assert.strictEqual(e.version, 'v1.1_kiosk_propio'); assert.strictEqual(e.decision, 'accept'); assert.strictEqual(e.adult, true); assert.strictEqual(e.user_id, '2002'); assert.ok(/^[0-9a-f-]{36}$/.test(e.id));

  // 3) rechazo: se registra y sigue por cédula/QR
  p = g.ensure('3003'); await settle(); btn('reject').click();
  assert.strictEqual(await p, 'cedula'); const r = posts[posts.length - 1].entries[0]; assert.strictEqual(r.decision, 'reject'); assert.strictEqual(r.adult, false);

  // 4) variante tercero: la casilla de mayoría de edad es obligatoria para habilitar el botón 1
  block = { ...BLOCK, variant: 'tercero', version: 'v1.1_kiosk_tercero', adult_checkbox: 'Declaro bajo la gravedad de juramento que tengo 18 años o más' };
  g = mk(); await g.loadBlock();
  p = g.ensure('4004'); await settle();
  assert.strictEqual(btn('accept').disabled, true, 'sin casilla el botón 1 está deshabilitado');
  btn('accept').click(); await settle(); assert.ok(screen(), 'un clic en el botón deshabilitado no avanza');
  const chk = screen().find((c) => c.tagName === 'input'); chk.checked = true; chk.change(); assert.strictEqual(btn('accept').disabled, false);
  btn('accept').click(); assert.strictEqual(await p, 'camera'); assert.strictEqual(posts[posts.length - 1].entries[0].adult, true);
  block = BLOCK;

  // 5) every_scan: aun con aceptación previa, botones cortos antes de cada uso
  block = { ...BLOCK, mode: 'every_scan' }; g = mk(); await g.loadBlock(); accepted.add('5005');
  p = g.ensure('5005'); await settle(); assert.strictEqual(screen().dataset.consentScreen, 'every'); assert.strictEqual(btn('accept').textContent, 'SÍ, USAR ROSTRO');
  btn('reject').click(); assert.strictEqual(await p, 'cedula'); block = BLOCK;

  // 6) SIN RED: la decisión queda en la cola local con la HUELLA (nunca la cédula) y se sincroniza una sola vez; sin servidor no hay cámara (cédula/QR)
  g = mk(); await g.loadBlock(); net = true; await GC.refreshRoster(); net = false; posts = [];                  // la copia local trae a 1001 con a=1
  assert.strictEqual(await g.ensure('1001'), 'cedula', 'sin red: ya aceptó según la copia, pero el rostro necesita servidor'); assert.ok(!screen(), 'y no se vuelve a pedir');
  assert.strictEqual(await g.ensure('7007'), 'cedula'); assert.ok(!screen(), 'quien no está en la copia local no se identifica sin red');
  await GC.consentAdd({ id: uuid(), h: await fp('1001'), decision: 'reject', adult: false, text_hash: BLOCK.hash, version: BLOCK.version, device: 'tablet-1', at: new Date(Date.now() - 1000).toISOString() });
  assert.strictEqual((await GC.consentLocal('1001')).accepted, false, 'la última decisión local manda');
  p = g.ensure('1001'); await settle(); assert.ok(screen(), 'tras un rechazo local se vuelve a mostrar'); btn('accept').click(); assert.strictEqual(await p, 'cedula');
  const stored = await GC.consentList(); assert.strictEqual(stored.length, 2); assert.ok(!JSON.stringify(stored).includes('"1001"'), 'la cola local no lleva la cédula en claro'); assert.ok(stored.every((x) => x.h));
  assert.strictEqual(GC.consentSize, 2); assert.strictEqual((await GC.consentLocal('1001')).accepted, true, 'la última (aceptación) manda');
  net = true; posts = [];
  assert.strictEqual(await GC.flushConsents(), 2); assert.strictEqual(posts.length, 1); assert.ok(posts[0].entries.every((x) => x.h && x.user_id === undefined));
  assert.strictEqual((await GC.consentList()).length, 0); assert.strictEqual(await GC.flushConsents(), 0); assert.strictEqual(posts.length, 1, 'no se vuelve a enviar');

  // 7) camino 2: un clic válido da el token; el botón 2 no
  block = { ...BLOCK, click_mode: true }; g = mk(); await g.loadBlock();
  p = g.clickFlow(); await settle(); btn('accept').click(); assert.strictEqual(await p, 'TOKEN');
  p = g.clickFlow(); await settle(); btn('reject').click(); assert.strictEqual(await p, null);
  clickOk = false; p = g.clickFlow(); await settle(); btn('accept').click(); assert.strictEqual(await p, null, 'si el servidor no da el token (evento sin pre-cálculo) no hay cámara'); clickOk = true;
  block = BLOCK; g = mk(); await g.loadBlock(); assert.strictEqual(await g.clickFlow(), null, 'sin click_mode no hay pantalla de un clic');

  // 8) texto con datos de la empresa sin completar (503 en producción): no se muestra nada → cédula/QR
  block = null; const g2 = G.create({ document: doc, fetch: async (u, o) => (/consent-text/.test(u) ? json(503, { detail: 'x' }) : fetchFake(u, o)), eventId: 1, gc: () => ({ supported: false }), uuid });
  assert.strictEqual(await g2.ensure('9009'), 'cedula'); assert.ok(!screen());
  console.log('consent-gate.js: aceptación vigente, pantalla completa, casilla de mayoría de edad, rechazo, every_scan, cola sin red por huella, camino 2 OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
