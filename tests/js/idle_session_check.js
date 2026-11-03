// Prueba del cierre de sesión por inactividad (static/js/idle-session.js, núcleo sin DOM). Correr: node tests/js/idle_session_check.js
// Comprueba: el uso real avisa al servidor (como mucho cada 30 s); sin uso NO se avisa; 1 minuto antes sale el aviso y «Seguir conectado» lo renueva; al vencer se cierra;
// sin conexión (o sin respuesta del servidor) NO se expulsa a nadie; otra pestaña que renovó cancela el aviso; la cuenta exenta (enabled=false) no hace nada.
const assert = require('assert');
const { create } = require('../../static/js/idle-session.js');

function harness(opts = {}) {
  const h = { t: 1_000_000, online: true, calls: [], warns: [], closed: 0, expired: 0, serverRemaining: opts.remaining ?? 600, enabled: opts.enabled !== false, down: false, status: 200 };
  h.deps = {
    now: () => h.t,
    isOnline: () => h.online,
    call: async (method, url) => {
      h.calls.push(method + ' ' + url);
      if (h.down) throw new Error('sin red');
      if (h.status === 401) return { status: 401, json: { detail: 'session_expired' } };
      if (method === 'POST') h.serverRemaining = 600;           // el servidor renueva al recibir el aviso de uso
      return { status: 200, json: h.enabled ? { enabled: true, idle_seconds: 600, remaining: h.serverRemaining, warn_seconds: 60 } : { enabled: false } };
    },
    warn: (secs, onContinue) => { const w = { secs, onContinue, close() { h.closed++; } }; h.warns.push(w); return w; },
    expire: () => { h.expired++; },
  };
  h.ctl = create(h.deps);
  h.advance = async (ms) => { for (let i = 0; i < ms / 5000; i++) { h.t += 5000; h.serverRemaining = Math.max(0, h.serverRemaining - 5); await h.ctl.tick(); } };
  return h;
}
const posts = (h) => h.calls.filter((c) => c.startsWith('POST')).length;

(async () => {
  // 1) sin uso: ni un solo aviso al servidor de uso; a los 9 min sale el aviso; sin responder, a los 10 se cierra
  let h = harness(); await h.ctl.start();
  await h.advance(8 * 60000); assert.strictEqual(posts(h), 0, 'sondear no es uso'); assert.strictEqual(h.warns.length, 0);
  await h.advance(60000 + 5000); assert.strictEqual(h.warns.length, 1, 'aviso 1 minuto antes'); assert.strictEqual(h.expired, 0);
  await h.advance(60000); assert.strictEqual(h.expired, 1, 'al vencer se cierra la sesión'); assert.strictEqual(h.ctl.state().stopped, true);

  // 2) «Seguir conectado» renueva y cierra el aviso; el tiempo vuelve a correr completo
  h = harness(); await h.ctl.start(); await h.advance(9 * 60000 + 5000); assert.strictEqual(h.warns.length, 1);
  assert.strictEqual(await h.warns[0].onContinue(), true); assert.strictEqual(h.closed, 1); assert.strictEqual(posts(h), 1);
  await h.advance(8 * 60000); assert.strictEqual(h.warns.length, 1, 'no vuelve a avisar enseguida'); assert.strictEqual(h.expired, 0);

  // 3) uso real: avisa al servidor, pero como mucho cada 30 s
  h = harness(); await h.ctl.start();
  for (let i = 0; i < 6; i++) { h.ctl.input(); await h.advance(5000); }             // 30 s con uso continuo
  assert.ok(posts(h) <= 1, 'throttle de 30 s: ' + posts(h));
  h.ctl.input(); await h.advance(30000); assert.ok(posts(h) >= 1);
  await h.advance(20 * 60000); // sin uso, 20 min
  assert.strictEqual(h.expired, 1);

  // 4) uso continuo: nunca avisa ni cierra
  h = harness(); await h.ctl.start();
  for (let i = 0; i < 12 * 20; i++) { if (i % 2 === 0) h.ctl.input(); await h.advance(5000); }   // 20 minutos con uso cada 10 s
  assert.strictEqual(h.warns.length, 0); assert.strictEqual(h.expired, 0);

  // 5) sin conexión: no se avisa ni se cierra, aunque pase de largo el tiempo; al volver se resuelve con lo que diga el servidor
  h = harness(); await h.ctl.start(); h.online = false; await h.advance(30 * 60000);
  assert.strictEqual(h.warns.length, 0); assert.strictEqual(h.expired, 0, 'offline no expulsa');
  h.online = true; h.down = true; await h.advance(60000); assert.strictEqual(h.expired, 0, 'servidor sin responder tampoco expulsa'); assert.strictEqual(h.warns.length, 0);
  h.down = false; h.serverRemaining = 30; await h.advance(5000); assert.strictEqual(h.warns.length, 1, 'al volver la red, el servidor manda');
  // uso hecho sin red: queda pendiente y se avisa al volver
  h = harness(); await h.ctl.start(); h.online = false; h.ctl.input(); await h.advance(60000); assert.strictEqual(posts(h), 0);
  h.online = true; await h.advance(5000); assert.strictEqual(posts(h), 1, 'el uso pendiente se envía al volver');

  // 6) otra pestaña renovó: el aviso se cancela / no sale
  h = harness(); await h.ctl.start(); await h.advance(9 * 60000 + 5000); assert.strictEqual(h.warns.length, 1);
  h.serverRemaining = 500; await h.advance(5000); assert.strictEqual(h.closed, 1, 'se cierra el aviso');

  // 7) el servidor dice 401 (vencida en otra pestaña): se cierra una sola vez
  h = harness(); await h.ctl.start(); await h.advance(9 * 60000 + 5000); h.status = 401; await h.advance(10000); assert.strictEqual(h.expired, 1);

  // 8) cuenta exenta (puesto de impresión): no hace nada nunca
  h = harness({ enabled: false }); await h.ctl.start(); await h.advance(30 * 60000); assert.strictEqual(h.warns.length, 0); assert.strictEqual(h.expired, 0); assert.strictEqual(posts(h), 0);

  // 9) con el aviso abierto, los clics en la página NO renuevan (solo el botón)
  h = harness(); await h.ctl.start(); await h.advance(9 * 60000 + 5000); h.ctl.input(); assert.strictEqual(h.ctl.state().dirty, false);

  console.log('idle_session_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
