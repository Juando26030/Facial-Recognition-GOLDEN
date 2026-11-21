// Prueba de la puerta central de inactividad de la pestaña (static/js/toast.js, «GW.idle», docs/22): sin uso 60 s se pausan los sondeos que tocan la base; al volver la actividad se reanudan
// al instante. Reloj y temporizadores falsos, sin DOM real. Además audita que todo setInterval de las pantallas de staff pase por la puerta o esté en la lista de excepciones justificadas.
// Correr: node tests/js/gw_idle_gate_check.js
const fs = require('fs');
const path = require('path');
const assert = require('assert');

global.window = { dispatchEvent() {} };
global.document = { addEventListener() {}, createElement: () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {} }), head: { appendChild() {} }, body: { appendChild() {} } };
global.requestAnimationFrame = (f) => f();
eval(fs.readFileSync('static/js/toast.js', 'utf8'));
const { createIdleGate } = window.GW;
assert.strictEqual(typeof createIdleGate, 'function');
assert.strictEqual(window.GW.idle, false);

function fake() {
  const f = { t: 0, timers: [], events: [] };
  f.gate = createIdleGate({ idleMs: 60000, now: () => f.t, setInterval: (fn, ms) => { f.timers.push({ fn, ms, next: ms }); return f.timers.length; }, emit: (n) => f.events.push(n) });
  f.advance = (ms) => { const end = f.t + ms; while (f.t < end) { f.t += 1000; f.gate.check(); f.timers.forEach((x) => { while (x.next <= f.t) { x.fn(); x.next += x.ms; } }); } };
  return f;
}

// 1) sin actividad 60 s: idle=true y los sondeos dejan de correr
let f = fake(); let polls = 0;
f.gate.poll(() => { polls++; }, 5000);
f.advance(59000); assert.strictEqual(f.gate.idle, false); const before = polls; assert.ok(before >= 10, 'sondea mientras hay uso reciente');
f.advance(2000); assert.strictEqual(f.gate.idle, true); assert.deepStrictEqual(f.events, ['gw:idle']);
const frozen = polls; f.advance(10 * 60000); assert.strictEqual(polls, frozen, 'idle: ningún sondeo');

// 2) vuelve la actividad: idle=false y el refresco corre AL INSTANTE (sin esperar al intervalo)
f.gate.activity(); assert.strictEqual(f.gate.idle, false); assert.strictEqual(polls, frozen + 1, 'refresco inmediato'); assert.ok(f.events.includes('gw:resume'));
f.advance(10000); assert.ok(polls > frozen + 1, 'y el sondeo sigue');

// 3) la actividad mientras no está idle solo reinicia la cuenta (no dispara refrescos extra)
f = fake(); polls = 0; f.gate.poll(() => { polls++; }, 5000);
for (let i = 0; i < 20; i++) { f.advance(10000); f.gate.activity(); } assert.strictEqual(f.gate.idle, false); const n = polls; f.gate.activity(); assert.strictEqual(polls, n);

// 4) onResume(fn, once): corre una sola vez al volver; los registros persistentes, cada vez
f = fake(); let once = 0, every = 0; f.gate.onResume(() => once++, true); f.gate.onResume(() => every++);
f.advance(61000); assert.ok(f.gate.idle); f.gate.activity(); f.advance(61000); f.gate.activity(); assert.strictEqual(once, 1); assert.strictEqual(every, 2);

// 5) un refresco que falla no impide los demás
f = fake(); let ok = 0; f.gate.onResume(() => { throw new Error('x'); }); f.gate.onResume(() => ok++); f.advance(61000); f.gate.activity(); assert.strictEqual(ok, 1);

// 6) auditoría: todo setInterval de staff pasa por GW.poll o es una excepción justificada (no consulta la base, o es pantalla de exhibición / impresión)
const ALLOWED = {
  'static/js/idle-session.js': 'cuenta el tiempo de sesión (/api/session/idle y touch no tocan la base)',
  'static/js/contingency.js': 'chequeo de /health (sin base), poda local; el refresco de la lista sí pasa por GW',
  'static/js/outbox-ui.js': 'vacía la cola sin conexión: solo consulta al servidor si hay altas pendientes',
  'static/js/shared-print.js': 'impresión compartida: anfitrión que atiende a otros equipos; no se pausa',
  'static/js/toast.js': 'puerta de inactividad y ping de sesión (por GW.poll)',
  'templates/digital_badge.html': 'pantalla de exhibición del carné digital',
  'templates/roulette_display.html': 'pantalla de exhibición de la ruleta',
  'templates/kiosk_rostro.html': 'entrada con rostro (pantalla de la puerta, sin toast.js): /health (sin base) y contador, que solo consulta tras un intento reciente (5 min)',
  'static/js/queue-tv.js': 'pantalla de exhibición de turnos (TV): se pausa con la pestaña oculta y el estado sale de la memoria del proceso (queue_svc.snapshot, ≤1 consulta cada 3 s por proceso)',
  'static/js/sistema.js': 'solo la línea del reloj local «Actualizado hace»; el refresco va por GW.poll',
  'static/js/preprint.js': 'solo mira si se cerró la ventana de impresión (win.closed), sin red ni base; se apaga al terminar',
};
const files = [];
for (const dir of ['static/js', 'templates']) for (const n of fs.readdirSync(dir)) if (/\.(js|html)$/.test(n)) files.push(path.join(dir, n));
const bad = [];
for (const file of files) {
  const text = fs.readFileSync(file, 'utf8');
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    if (!/\bsetInterval\s*\(/.test(line) || /^\s*(\/\/|\*|\/\*)/.test(line)) return;
    if (ALLOWED[file]) return;
    if (/GW\.poll|GW\.idle|\bgw\b/.test(lines.slice(Math.max(0, i - 3), i + 4).join('\n'))) return;
    bad.push(`${file}:${i + 1}`);
  });
}
assert.deepStrictEqual(bad, [], 'setInterval sin pasar por la puerta de inactividad: ' + bad.join(', '));
console.log('gw_idle_gate_check OK');
