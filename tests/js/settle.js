// Espera DETERMINISTA para las pruebas JS: en vez de «N vueltas del bucle de eventos» (que se agotan antes de que termine un crypto.subtle real, que corre en hilos del sistema y con la máquina
// cargada tarda lo que tarde), se espera a que NO quede ninguna operación de crypto.subtle en vuelo y pasen `quiet` vueltas seguidas sin que empiece otra. No usa tiempos: el límite de 30 s solo
// evita un cuelgue eterno si algo de verdad no termina (y entonces la prueba falla diciéndolo).
// Se instrumenta crypto.subtle una sola vez (todas las pruebas comparten el mismo objeto).
const subtle = globalThis.crypto && globalThis.crypto.subtle;
let inflight = 0;
if (subtle && !subtle.__counted) {
  for (const m of ['digest', 'encrypt', 'decrypt', 'importKey', 'generateKey', 'exportKey', 'sign', 'verify', 'deriveKey', 'deriveBits']) {
    const orig = subtle[m] && subtle[m].bind(subtle);
    if (!orig) continue;
    subtle[m] = (...a) => { inflight++; let p; try { p = orig(...a); } catch (e) { inflight--; throw e; } return p.then((v) => { inflight--; return v; }, (e) => { inflight--; throw e; }); };
  }
  subtle.__counted = true;
}
const tick = () => new Promise((r) => setImmediate(r));
async function settle(quiet = 20) {
  const t0 = Date.now(); let idle = 0;
  while (idle < quiet) {
    await tick();
    idle = inflight === 0 ? idle + 1 : 0;
    if (Date.now() - t0 > 30000) throw new Error(`settle: sigue habiendo ${inflight} operaciones de crypto.subtle sin terminar tras 30 s`);
  }
}
// Espera a que se cumpla una condición REAL (p. ej. «apareció la pantalla»); falla diciendo cuál si no ocurre.
async function until(pred, what, ms = 30000) {
  const t0 = Date.now();
  while (!pred()) { await tick(); if (Date.now() - t0 > ms) throw new Error(`until: nunca ocurrió: ${what}`); }
}
module.exports = { settle, until, tick };
