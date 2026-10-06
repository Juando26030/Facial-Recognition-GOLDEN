// Prueba de la pantalla de la bandeja (static/js/outbox-ui.js) con un DOM mínimo y una bandeja falsa. Correr: node tests/js/outbox_ui_check.js
// Comprueba: franja de aviso (color por nivel, texto), botón con el número, lista con textContent (un nombre con HTML no se interpreta), «Descartar» SIEMPRE pide confirmación, «Enviar de todos modos»,
// envío automático solo con conexión y avisos al terminar.
const assert = require('assert');
const UI = require('../../static/js/outbox-ui.js');
global.window = global;                                    // outbox-ui.js lee root.GoldenOutbox.statusLabel
global.GoldenOutbox = require('../../static/js/outbox.js');

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.listeners = {}; this._text = ''; this.attrs = {}; }
  set textContent(v) { this._text = String(v); this.children = []; } get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...c) { this.children = c; this._text = ''; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(k, f) { this.listeners[k] = f; }
  click() { return this.listeners.click({ target: this }); }
  find(pred, acc = []) { if (pred(this)) acc.push(this); this.children.forEach((c) => c.find(pred, acc)); return acc; }
}
const doc = { body: new El('body'), createElement: (t) => new El(t) };
const flush = () => new Promise((r) => setImmediate(r));

(async () => {
  let items = [], unsent = 0, syncCalls = [], discarded = [], listeners = [];
  const stats = () => {
    const un = items.filter((i) => ['pendiente', 'error', 'revision', 'duplicado'].includes(i.status)), ex = items.filter((i) => i.status === 'caducada');
    const s = { total: items.length, unsent: un.length, expired: ex.length, oldest_days: Math.max(0, ...items.map((i) => i.days_old)), min_days_left: un.length ? Math.min(...un.map((i) => i.days_left)) : 0, level: 'ok' };
    s.level = ex.length ? 'expired' : (s.oldest_days >= 6 ? 'urgent' : (s.oldest_days >= 3 ? 'warn' : 'ok')); s.banner = GoldenOutbox.bannerText(s); return s;
  };
  const outbox = { dismissPruned: async () => {}, stats: async () => stats(), list: async () => items, countUnsent: async () => unsent, onChange: (f) => listeners.push(f),
    sync: async (opts) => { syncCalls.push(opts || {}); return { sent: 1, ok: 2, revision: 1, error: 0, stopped: null }; }, retry: async () => {}, discard: async (id) => { discarded.push(id); items = items.filter((i) => i.op_id !== id); } };
  const toasts = []; let answer = false, asked = [], reloads = 0, online = true;
  global.directorySearch = { reload: () => { reloads++; } };
  const ui = UI.mount({ outbox, document: doc, toast: (m, k) => toasts.push([m, k]), confirm: async (m) => { asked.push(m); return answer; }, online: () => online });
  await flush();
  const banner = doc.body.children[0], btn = doc.body.children[1], modal = doc.body.children[2];
  assert.strictEqual(banner.style.display, 'none'); assert.strictEqual(btn.style.display, 'none', 'sin nada en la bandeja no se muestra nada');

  // aviso por nivel
  items = [{ op_id: 'a', status: 'pendiente', label: 'Nora <b>x</b>', detail: null, days_old: 1, days_left: 6, level: 'ok' }]; unsent = 1; await ui.refresh();
  assert.strictEqual(btn.style.display, 'block'); assert.strictEqual(btn.textContent, '📤 Bandeja (1)'); assert.ok(/1 persona nueva sin enviar/.test(banner.textContent));
  items[0].days_old = 3.2; items[0].days_left = 3.8; await ui.refresh(); assert.ok(/hace 3 días; caduca en 4 días/.test(banner.textContent)); assert.strictEqual(banner.style.background, '#fff3cd', 'amarillo desde el día 3');
  items[0].days_old = 6.5; items[0].days_left = 0.5; await ui.refresh(); assert.strictEqual(banner.style.background, '#f8d7da', 'rojo desde el día 6');
  items[0].status = 'caducada'; items[0].level = 'expired'; await ui.refresh(); assert.ok(/CADUCÓ/.test(banner.textContent));

  // la lista: el nombre entra como TEXTO (nunca como HTML) y cada estado ofrece lo que corresponde
  await ui.open(); assert.strictEqual(modal.style.display, 'block');
  const all = modal.find(() => true); assert.ok(all.some((e) => e.textContent === 'Nora <b>x</b>' && e.tag === 'td'), 'el nombre se muestra literal'); assert.ok(!all.some((e) => e.tag === 'b' || e.tag === 'x'));
  const labels = () => modal.find((e) => e.tag === 'button').map((b) => b.textContent);
  assert.ok(labels().includes('Enviar de todos modos') && labels().includes('Descartar') && labels().includes('Enviar ahora'));
  const click = (label) => modal.find((e) => e.tag === 'button' && e.textContent === label)[0].click();
  await click('Enviar de todos modos'); // sync force
  // Descartar: SIEMPRE pregunta; sin «sí» no se borra nada
  answer = false; await click('Descartar'); await flush(); assert.strictEqual(asked.length, 1); assert.ok(/Descartar a <strong>Nora &lt;b&gt;x&lt;\/b&gt;<\/strong>/.test(asked[0]), 'el nombre va escapado en el aviso: ' + asked[0]); assert.deepStrictEqual(discarded, []);
  answer = true; await click('Descartar'); await flush(); assert.deepStrictEqual(discarded, ['a'], 'solo con confirmación se descarta');

  // lo ya enviado se quita sin preguntar (no lleva datos); un pendiente no ofrece descartar
  items = [{ op_id: 'b', status: 'ok', label: 'Beatriz', days_old: 0, days_left: 1, level: 'ok' }, { op_id: 'c', status: 'pendiente', label: 'Carla', days_old: 0, days_left: 7, level: 'ok' }]; await ui.refresh();
  asked = []; await click('Quitar'); assert.strictEqual(asked.length, 0); assert.ok(discarded.includes('b'));
  assert.strictEqual(modal.find((e) => e.tag === 'button' && e.textContent === 'Descartar').length, 0, 'un pendiente no se descarta (se envía)');

  // envío: manual y automático solo con conexión; avisos al terminar
  syncCalls = []; toasts.length = 0; await ui.sync(true);
  assert.strictEqual(syncCalls.length, 1); assert.ok(toasts.some(([m, k]) => /2 persona\(s\) nueva\(s\) enviada\(s\)/.test(m) && k === 'success')); assert.ok(toasts.some(([m, k]) => /requieren revisión/.test(m) && k === 'error')); assert.strictEqual(reloads, 1, 'recarga la lista tras enviar');
  syncCalls = []; unsent = 1; online = false; await ui.tick(); assert.strictEqual(syncCalls.length, 0, 'sin conexión no intenta enviar');
  online = true; await ui.tick(); assert.strictEqual(syncCalls.length, 1); unsent = 0; await ui.tick(); assert.strictEqual(syncCalls.length, 1, 'sin pendientes no envía');
  clearInterval(ui.timer);
  console.log('outbox-ui.js: aviso por nivel, lista segura, descartar con confirmación y envío solo con conexión OK');
})().catch((e) => { console.error(e); process.exit(1); });
