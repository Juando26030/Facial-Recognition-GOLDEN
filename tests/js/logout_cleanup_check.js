// Prueba del cierre de sesión con la copia local de contingencia (static/js/toast.js, «Cierre de sesión y copia local»), con IndexedDB y DOM falsos.
// Correr: node tests/js/logout_cleanup_check.js
// Comprueba: al enviar un formulario /logout se borran el roster y los metadatos de TODOS los golden-contingency-*, se avisa cuántos ingresos quedan sin sincronizar (y se puede cancelar),
// la cola se conserva, no se toca ninguna otra base, y sin soporte de IndexedDB el cierre sigue normal.
const fs = require('fs');
const assert = require('assert');
const { fakeIndexedDB } = require('./fake_idb');

const idb = fakeIndexedDB();
let submitHandler = null;
global.window = { indexedDB: idb, GoldenContingency: { instance: null } };
global.indexedDB = idb;
global.document = { addEventListener: (k, f) => { if (k === 'submit') submitHandler = f; }, createElement: () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {} }), head: { appendChild() {} }, body: { appendChild() {} } };
global.requestAnimationFrame = (f) => f();
let confirms = [], answer = true;
eval(fs.readFileSync('static/js/toast.js', 'utf8'));
window.showConfirm = async (msg) => { confirms.push(msg); return answer; };

const seed = async (name, { roster = 2, queue = 0 } = {}) => new Promise((resolve) => {
  const r = idb.open(name, 2);
  r.onupgradeneeded = () => { ['roster', 'queue', 'meta', 'review'].forEach((s) => r.result.createObjectStore(s, { keyPath: s === 'roster' ? 'h' : s === 'meta' ? 'k' : 'client_id' })); };
  r.onsuccess = () => {
    const t = r.result.transaction(['roster', 'queue', 'meta', 'review'], 'readwrite');
    for (let i = 0; i < roster; i++) t.objectStore('roster').put({ h: 'h' + i });
    for (let i = 0; i < queue; i++) t.objectStore('queue').put({ client_id: 'c' + i, h: 'h0' });
    t.objectStore('meta').put({ k: 'roster', v: 'v1' }); t.objectStore('review').put({ client_id: 'r1' });
    t.oncomplete = resolve;
  };
});
const size = (name, store) => idb.dbs.get(name).stores.get(store).data.size;
const form = (action = '/logout') => ({ submitted: false, prevented: false, getAttribute: () => action, submit() { this.submitted = true; } });
const fire = async (f) => { const ev = { target: f, preventDefault() { f.prevented = true; } }; submitHandler(ev); for (let i = 0; i < 40; i++) await new Promise((r) => setImmediate(r)); };

(async () => {
  assert.ok(submitHandler, 'toast.js registra el manejador de cierre de sesión');
  await seed('golden-contingency-7', { queue: 2 }); await seed('golden-contingency-9', { queue: 0 }); await seed('otra-base', { queue: 3 });

  // otro formulario: no se toca
  let f = form('/otra-cosa'); await fire(f); assert.strictEqual(f.prevented, false); assert.strictEqual(confirms.length, 0);

  // cancelar el cierre con ingresos pendientes: nada se borra y no se envía
  answer = false; f = form(); await fire(f);
  assert.strictEqual(f.prevented, true); assert.strictEqual(f.submitted, false, 'cancelado: no cierra sesión');
  assert.ok(/<strong>2<\/strong> ingreso\(s\) sin sincronizar/.test(confirms[0]), 'avisa cuántos quedan sin sincronizar');
  assert.strictEqual(size('golden-contingency-7', 'roster'), 2);

  // aceptar: roster y metadatos borrados en TODOS los golden-contingency-*, cola conservada, otras bases intactas
  answer = true; f = form(); await fire(f);
  assert.strictEqual(f.submitted, true);
  for (const n of ['golden-contingency-7', 'golden-contingency-9']) { assert.strictEqual(size(n, 'roster'), 0); assert.strictEqual(size(n, 'meta'), 0); }
  assert.strictEqual(size('golden-contingency-7', 'queue'), 2, 'la cola se conserva hasta sincronizar'); assert.strictEqual(size('golden-contingency-7', 'review'), 1);
  assert.strictEqual(size('otra-base', 'roster'), 2, 'no se toca ninguna otra base'); assert.strictEqual(size('otra-base', 'queue'), 3);

  // sin pendientes: no pregunta, borra y sale
  confirms = []; idb.dbs.get('golden-contingency-7').stores.get('queue').data.clear(); await seed('golden-contingency-9', { queue: 0 });
  f = form(); await fire(f); assert.strictEqual(confirms.length, 0); assert.strictEqual(f.submitted, true); assert.strictEqual(size('golden-contingency-9', 'roster'), 0);

  // si el cliente de la página puede sincronizar, lo intenta antes
  let synced = 0; window.GoldenContingency.instance = { beforeLogout: async () => { synced++; } };
  f = form(); await fire(f); assert.strictEqual(synced, 1); assert.strictEqual(f.submitted, true);
  window.GoldenContingency.instance = { beforeLogout: async () => { throw new Error('boom'); } };
  f = form(); await fire(f); assert.strictEqual(f.submitted, true, 'un fallo al sincronizar no impide salir');

  // sin soporte de IndexedDB.databases: el cierre sigue normal (el navegador envía el formulario)
  window.GoldenContingency.instance = null; global.indexedDB = {}; window.indexedDB = {};
  f = form(); await fire(f); assert.strictEqual(f.prevented, false);
  console.log('toast.js: cierre de sesión con copia local OK (borra el roster, avisa de los pendientes, conserva la cola)');
})().catch((e) => { console.error(e); process.exit(1); });
