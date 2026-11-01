// P7: el botón «Usar los valores que ya están en la base» y su diálogo (jsdom, fetch falso). Correr: npm ci && node tests/js/option_tools_dom_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<textarea id="t"></textarea><textarea id="b"></textarea>', { runScripts: 'outside-only' });
const w = dom.window;
let calls = [];
const payload = { key: 'opcional_1', label: 'Ciudad', scope: 'event', total: 2, truncated: false, limit: 200, skipped: 0, groups: [
  { suggested: 'Apartadó', count: 3, values: [{ value: 'Apartadó', count: 3 }] },
  { suggested: 'Bogotá', count: 8, values: [{ value: 'Bogotá', count: 5 }, { value: 'Bogota', count: 3 }] }] };
w.fetch = async (url) => { calls.push(url); return url.includes('key=id') ? { ok: false, json: async () => ({ detail: 'Este campo identifica a las personas' }) } : { ok: true, json: async () => payload }; };
w.eval(fs.readFileSync(path.join(__dirname, '../../static/js/option-tools.js'), 'utf8'));
const doc = w.document, tick = () => new Promise((r) => setTimeout(r, 0));
const buttons = (ta) => Array.from(ta._otWrap.querySelectorAll('button')).map((b) => b.textContent);

const ta = doc.getElementById('t');
w.OptionTools.attach(ta, { eventId: 7, key: 'opcional_1' });
assert.ok(buttons(ta).includes('Usar los valores que ya están en la base de datos'));
const blocked = doc.getElementById('b');
w.OptionTools.attach(blocked, { eventId: 7, key: 'email' });
assert.ok(!buttons(blocked).some((t) => /base de datos/.test(t)), 'campos que identifican: sin botón');

(async () => {
  const dbBtn = Array.from(ta._otWrap.querySelectorAll('button')).find((b) => /base de datos/.test(b.textContent));
  dbBtn.click(); await tick(); await tick();
  assert.ok(calls[0].includes('/api/events/7/field-values?key=opcional_1&scope=event'));
  const text = doc.body.textContent;
  assert.ok(/Estas opciones serán públicas/.test(text) && /Quedarán 2 opciones/.test(text), 'aviso de públicas y cuántas son');
  assert.ok(/variantes juntas/.test(text), 'Bogota/Bogotá juntas para elegir');
  doc.querySelector('select').value = 'Bogota'; doc.querySelector('select').dispatchEvent(new w.Event('change'));
  const ok = Array.from(doc.querySelectorAll('button')).find((b) => b.textContent === 'Usar estas opciones');
  ok.click(); await tick();
  assert.strictEqual(ta.value, 'Apartadó\nBogota', 'queda la foto, A–Z, con la variante elegida');
  assert.ok(buttons(ta).includes('Actualizar desde la base'), 'ahora ofrece actualizar (no lo hace solo)');
  assert.strictEqual(calls.length, 1, 'no vuelve a la base por su cuenta');
  console.log('option_tools_dom_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
