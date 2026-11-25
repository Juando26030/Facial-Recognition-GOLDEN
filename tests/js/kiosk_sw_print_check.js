// Imprimir SIN red (static/js/kiosk-sw.js, docs/28). Correr: node tests/js/kiosk_sw_print_check.js
// Comprueba: la plantilla y sus imágenes se guardan (red primero) y salen de la copia sin red; la ventana de impresión guardada se sirve con la cédula pedida; los datos de la persona
// NUNCA se guardan en el caché: sin red se arman desde la copia completa cifrada, solo para quien está Registrado; el conteo responde 0 sin red; el resto de la API sigue sin pasar por el worker.
const fs = require('fs');
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');
const C = require('../../static/js/contingency.js');
const { settle } = require('./settle');

const O = 'https://app.test';
const R = (body, status = 200, type = 'text/html') => { const r = new Response(body, { status, headers: { 'Content-Type': type } }); Object.defineProperty(r, 'type', { value: 'basic' }); return r; };
const store = new Map();
const cacheOf = (name) => { if (!store.has(name)) store.set(name, new Map()); const m = store.get(name); const k = (q) => (typeof q === 'string' ? q : q.url);
  return { match: async (q) => { const h = m.get(k(q)); return h ? h.clone() : undefined; }, put: async (q, res) => { m.set(k(q), res); }, keys: async () => [...m.keys()].map((url) => ({ url })), delete: async (q) => m.delete(k(q)) }; };
const caches = { open: async (n) => cacheOf(n), keys: async () => [...store.keys()], delete: async (n) => store.delete(n) };
const idb = fakeIndexedDB();
const listeners = {};
const scope = { location: { origin: O, href: O + '/kiosk/sw.js' }, addEventListener: (k, f) => { listeners[k] = f; }, skipWaiting() {}, clients: { claim: async () => {} }, indexedDB: idb, crypto };
let net = async () => { throw new TypeError('Failed to fetch'); };
new Function('self', 'caches', 'fetch', 'Response', 'URL', 'AbortController', 'setTimeout', 'clearTimeout', fs.readFileSync('static/js/kiosk-sw.js', 'utf8').split('__BUILD__').join('t1'))(scope, caches, (q, i) => net(q, i), Response, URL, AbortController, setTimeout, clearTimeout);
const dispatch = async (url, mode = 'cors') => { let handled = null; const waits = []; listeners.fetch({ request: { url, method: 'GET', mode, headers: {} }, respondWith: (p) => { handled = p; }, waitUntil: (p) => waits.push(p) }); const out = handled ? { handled: true, res: await handled } : { handled: false }; await Promise.all(waits); return out; };
const allKeys = () => [...store.values()].flatMap((m) => [...m.keys()]);

(async () => {
  global.setInterval = () => 1;
  const TPL = { width_mm: 60, height_mm: 90, background_type: 'image', background_value: 'acme/fondo.png', elements: [{ type: 'image_static', storage_path: 'acme/logo.png' }] };
  const PAGE = '<script src="/static/js/badge-render.js?v=1"></script>\n    const USER_ID = "PRUEBA";\n    const USER_IDS = ["PRUEBA"];                 // una o varias\n';
  const online = async (q) => { const u = new URL(typeof q === 'string' ? q : q.url);
    if (u.pathname === '/api/events/7/badge-template') return R(JSON.stringify(TPL), 200, 'application/json');
    if (u.pathname.startsWith('/api/badge-assets/')) return R('PNG:' + u.pathname, 200, 'image/png');
    if (u.pathname === '/kiosk/7/escarapela/imprimir/PRUEBA') return R(PAGE);
    if (u.pathname.startsWith('/static/')) return R('// estático');
    if (u.pathname.endsWith('/badge-print-data')) return R(JSON.stringify({ id: 'servidor' }), 200, 'application/json');
    if (u.pathname.endsWith('/print-count')) return R(JSON.stringify({ times_printed: 2 }), 200, 'application/json');
    return R('otra');
  };
  // con red: la página manda la configuración y el worker guarda plantillas, imágenes, la ventana de impresión y sus archivos
  net = online;
  await new Promise((resolve) => listeners.message({ data: { type: 'print-cfg', eventId: 7, cfg: { per_category: true, categories: ['VIP'], labels: { opcional_1: 'Mesa' }, code: true } }, waitUntil: (p) => p.then(resolve) }));
  const keys = allKeys();
  assert.ok(keys.includes(`${O}/api/events/7/badge-template`) && keys.includes(`${O}/api/events/7/badge-template?category=VIP`), 'plantillas guardadas');
  assert.ok(keys.includes(`${O}/api/badge-assets/acme/fondo.png`) && keys.includes(`${O}/api/badge-assets/acme/logo.png`), 'imágenes de la plantilla guardadas');
  assert.ok(keys.includes(`${O}/kiosk/7/escarapela/imprimir`) && keys.some((k) => k.includes('/static/js/badge-render.js')), 'ventana de impresión y sus archivos');
  // con red todo sale de la red (y los datos de la persona nunca se guardan)
  assert.strictEqual((await (await dispatch(`${O}/api/users/1001/badge-print-data?event_id=7`)).res.json()).id, 'servidor');
  assert.strictEqual((await (await dispatch(`${O}/api/users/1001/print-count?event_id=7`)).res.json()).times_printed, 2);
  assert.ok(!allKeys().some((k) => k.includes('badge-print-data') || k.includes('print-count')), 'los datos de la persona no se guardan en el caché');
  for (const u of [`${O}/api/events/7/local-roster`, `${O}/api/users?event_id=7`, `${O}/api/events/7/print-jobs`]) assert.strictEqual((await dispatch(u)).handled, false, 'el resto de la API no pasa por el worker: ' + u);

  // la copia completa cifrada del dispositivo (la arma contingency.js)
  const SALT = 'e'.repeat(32);
  const hex = (b) => Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, '0')).join('');
  const fp = async (c) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${SALT}:${c}`))).slice(0, 16);
  const people = [{ h: await fp('1001'), n: 'Ana Pérez', c: ['VIP'], s: 'Registrado' }, { h: await fp('1002'), n: 'Luis Rey', c: [], s: 'No registrado' }];
  const json = (data) => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => data });
  const doc = { body: { children: [], appendChild() {}, classList: { toggle() {} } }, head: { appendChild() {} }, createElement: () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {}, addEventListener() {}, remove() {}, children: [], textContent: '', classList: { toggle() {}, add() {}, remove() {} } }), getElementById: () => null, addEventListener() {}, visibilityState: 'visible' };
  const gc = C.create({ idb, fetch: async (url) => { const u = new URL(url, O); if (u.pathname.endsWith('/local-roster')) return json({ v: 'v1', generated_at: new Date().toISOString(), max_age_s: 3600, event: { id: 7, status: 'en_proceso', auto_register: false }, salt: SALT, count: 2, people }); return json({}); },
    now: () => Date.now(), document: doc, subtle: crypto.subtle, eventId: 7, uuid: () => '00000000-0000-4000-8000-000000000001', setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout });
  await gc.start(); await settle();
  assert.strictEqual(await gc.refreshRoster(), 'ok');
  await gc.peopleSave([{ id: '1001', first_name: 'Ana', last_name: 'Pérez', entity: 'Acme', phone: '300', email: 'a@x.test', status: 'Registrado', categories: ['VIP', 'Prensa'], extra_fields: { opcional_1: '12' }, code: 'C-77' },
    { id: '1002', first_name: 'Luis', last_name: 'Rey', status: 'No registrado', categories: [] }]);

  // SIN red
  net = async () => { throw new TypeError('Failed to fetch'); };
  const tpl = await dispatch(`${O}/api/events/7/badge-template?category=VIP&_=${Date.now()}`);
  assert.strictEqual((await tpl.res.json()).width_mm, 60, 'la plantilla sale de la copia (sin importar el parámetro único)');
  assert.strictEqual(await (await dispatch(`${O}/api/badge-assets/acme/logo.png`)).res.text(), 'PNG:/api/badge-assets/acme/logo.png');
  const page = await (await dispatch(`${O}/kiosk/7/escarapela/imprimir/1001`, 'navigate')).res.text();
  assert.ok(page.includes('const USER_ID = "1001";') && page.includes('const USER_IDS = ["1001"];') && !page.includes('PRUEBA'), 'la ventana de impresión con la cédula pedida');
  const many = await (await dispatch(`${O}/kiosk/7/escarapela/imprimir/1001?users=1001,1002`, 'navigate')).res.text();
  assert.ok(many.includes('const USER_IDS = ["1001","1002"];'));
  const evil = await (await dispatch(`${O}/kiosk/7/escarapela/imprimir/${encodeURIComponent('</script><b>')}`, 'navigate')).res.text();
  assert.ok(!evil.includes('</script><b>'), 'la cédula se escribe escapada');
  const d = await dispatch(`${O}/api/users/1001/badge-print-data?event_id=7`);
  assert.strictEqual(d.res.status, 200);
  const data = await d.res.json();
  assert.deepStrictEqual({ id: data.id, first_name: data.first_name, entity: data.entity, categories: data.categories, code: data.code, template_category: data.template_category, has_photo: data.has_photo, labels: data.optional_field_labels, extra: data.extra_fields, card_url: data.card_url },
    { id: '1001', first_name: 'Ana', entity: 'Acme', categories: 'VIP, Prensa', code: 'C-77', template_category: 'VIP', has_photo: false, labels: { opcional_1: 'Mesa' }, extra: { opcional_1: '12' }, card_url: '' });
  assert.strictEqual((await dispatch(`${O}/api/users/1002/badge-print-data?event_id=7`)).res.status, 403, 'solo se imprime a quien está Registrado');
  assert.strictEqual((await dispatch(`${O}/api/users/9999/badge-print-data?event_id=7`)).res.status, 503, 'persona que no está en el dispositivo');
  assert.strictEqual((await (await dispatch(`${O}/api/users/1001/print-count?event_id=7`)).res.json()).times_printed, 0);
  assert.ok(!allKeys().some((k) => k.includes('badge-print-data')), 'ni sin red se guardan los datos de la persona');
  console.log('kiosk_sw_print_check: OK');
})().catch((e) => { console.error(e); process.exit(1); });
