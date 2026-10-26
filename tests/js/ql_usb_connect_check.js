// «Conectar impresora» (25-oct-2026): idempotente, de un solo vuelo, coordinada entre pestañas, con errores en español y que suelta la impresora al cerrar.
// Se prueba con una impresora SIMULADA que se comporta como Chrome + Windows: el equipo solo deja abrir la impresora a un cliente a la vez («Access denied» si ya la tiene otro programa u otra
// pestaña), abrir de nuevo el mismo objeto no hace nada, y los candados (Web Locks) y el canal entre pestañas son compartidos. Se corre con: node tests/js/ql_usb_connect_check.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.resolve(__dirname, "../../static/js/ql-usb.js"), "utf8");

// ---- el «equipo»: una impresora física y un administrador de candados compartidos por todas las pestañas
const hw = { openedBy: null, sent: [], opens: 0, closes: 0 };
const locks = new Set();
const lockManager = {
  request(name, opts, cb) {
    if (opts && opts.ifAvailable && locks.has(name)) return Promise.resolve(cb(null));
    locks.add(name);
    return Promise.resolve(cb({ name })).finally(() => locks.delete(name));
  },
};
const denied = () => Object.assign(new Error("Failed to execute 'open' on 'USBDevice': Access denied."), { name: "SecurityError" });

function newTab(id) {
  const dev = {
    vendorId: 0x04f9, productName: "QL-800", opened: false, configuration: null,
    async open() { if (hw.openedBy && hw.openedBy !== id) throw denied(); if (!this.opened) { hw.opens++; hw.openedBy = id; this.opened = true; } },     // abrir lo ya abierto no hace nada (como Chrome)
    async selectConfiguration() { this.configuration = { interfaces: [{ interfaceNumber: 0, alternates: [{ interfaceClass: 7, endpoints: [{ type: "bulk", direction: "out", endpointNumber: 1 }, { type: "bulk", direction: "in", endpointNumber: 2 }] }] }] }; },
    async claimInterface() {},
    async releaseInterface() {},
    async close() { if (this.opened) { hw.closes++; this.opened = false; if (hw.openedBy === id) hw.openedBy = null; } },
    async transferOut(ep, data) { hw.sent.push({ tab: id, bytes: data.length }); return { status: "ok" }; },
  };
  dev.configuration = null;
  const nav = { usb: { getDevices: async () => [dev], requestDevice: async () => dev, addEventListener() {} }, locks: lockManager };
  const mod = { exports: {} };
  new Function("navigator", "module", "BroadcastChannel", "window", SRC)(nav, mod, BroadcastChannel, undefined);
  const tab = { Q: mod.exports, dev, nav };
  tabs.push(tab);
  return tab;
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const tabs = [];                                                       // las pestañas de pruebas anteriores se «cierran» (si no, seguirían contestando por el canal)
const reset = () => { tabs.forEach((x) => x.Q.releaseNow()); tabs.length = 0; hw.openedBy = null; hw.sent.length = 0; hw.opens = 0; hw.closes = 0; locks.clear(); };

(async () => {
  // ---- 1) conectar dos veces en la misma pestaña: la segunda dice «ya conectada» y NO vuelve a abrir
  reset();
  let t = newTab("A");
  const d1 = await t.Q.connect(false), d2 = await t.Q.connect(true);
  assert.strictEqual(d1, d2); assert.strictEqual(hw.opens, 1, "se abrió una sola vez"); assert.ok(t.Q.ready());
  // ---- 2) intentos a la vez (arranque de la página + evento de conexión + toque del botón): un solo vuelo, sin falso «en uso» ni cierre de la conexión
  reset(); t = newTab("A");
  const [a, b, c] = await Promise.all([t.Q.connect(false), t.Q.connect(false), t.Q.connect(true)]);
  assert.ok(a && a === b && b === c, "los tres reciben la misma conexión"); assert.strictEqual(hw.opens, 1); assert.strictEqual(hw.closes, 0); assert.ok(t.Q.ready());
  // ---- 3) un fallo al reabrir no cierra la conexión viva
  t.dev.open = async () => { throw denied(); };
  t.dev.opened = true;                                              // (la ya abierta de arriba)
  assert.strictEqual(await t.Q.connect(true), t.dev, "ya abierta: ni siquiera intenta abrir"); assert.strictEqual(hw.closes, 0);
  // ---- 4) dos pestañas: la segunda no puede abrir (candado), lo dice en español y puede preguntar quién la tiene
  reset(); const A = newTab("A"), B = newTab("B");
  await A.Q.connect(false);
  await assert.rejects(B.Q.connect(true), (e) => e.busy === true && e.code === "busy" && /otra pestaña/.test(e.message));
  assert.strictEqual(hw.opens, 1, "la segunda ni intentó abrir el equipo");
  const owner = await B.Q.remoteOwner();
  assert.deepStrictEqual(owner, { name: "QL-800", here: false }, "B sabe que la dueña es otra pestaña");
  assert.deepStrictEqual(await A.Q.remoteOwner(), { name: "QL-800", here: true });
  // ---- 5) imprimir desde la pestaña NO dueña: el trabajo pasa por la dueña
  await B.Q.sendJob(new Uint8Array(40000));
  assert.deepStrictEqual(hw.sent.map((x) => x.tab), ["A", "A", "A"], "lo envió la pestaña dueña, en tres bloques");
  assert.strictEqual(hw.sent.reduce((n, x) => n + x.bytes, 0), 40000);
  // ---- 6) al cerrar/recargar la dueña se suelta la impresora y otra pestaña ya puede conectar
  A.Q.releaseNow(); await wait(30);
  assert.strictEqual(hw.openedBy, null); assert.ok(!A.Q.ready()); assert.ok(!locks.has(A.Q.LOCK_NAME), "el candado quedó libre");
  assert.strictEqual(await B.Q.remoteOwner(), null, "ya nadie la tiene");
  const dB = await B.Q.connect(true); assert.ok(dB && B.Q.ready() && hw.openedBy === "B");
  // ---- 7) «Access denied» del equipo (otro programa, por ejemplo Brother P-touch Editor): mensaje en español con la acción; nada queda a medias
  reset(); const C = newTab("C"); hw.openedBy = "P-touch Editor";
  const err = await C.Q.connect(true).then(() => null, (e) => e);
  assert.ok(err && err.code === "denied" && err.busy === false, "código «denied»");
  assert.ok(/no puede usar la impresora por USB directo/.test(err.message) && /Controlador de Windows/.test(err.message) && /tablet o celular/.test(err.message), err.message);
  assert.ok(!/cuadro de Windows/.test(err.message), "ya no afirma que el computador «imprime con el cuadro de Windows»");
  assert.ok(/Access denied/.test(err.raw), "se conserva el texto original para soporte");
  assert.ok(!C.Q.ready() && !locks.has(C.Q.LOCK_NAME), "no queda ni conexión ni candado");
  hw.openedBy = null;                                               // el otro programa la suelta
  assert.ok(await C.Q.connect(true) && C.Q.ready(), "al soltarla, conecta");
  // ---- 8) otros errores, en español
  const F = newTab("F").Q.friendlyError;
  assert.strictEqual(F(Object.assign(new Error("No device selected."), { name: "NotFoundError" })).code, "cancelled");
  assert.strictEqual(F(Object.assign(new Error("The device was disconnected."), { name: "NetworkError" })).code, "disconnected");
  assert.strictEqual(F(Object.assign(new Error("Must be handling a user gesture"), { name: "SecurityError" })).code, "permission");
  assert.strictEqual(F(new Error("algo raro")).code, "other");
  assert.ok(/No elegiste ninguna impresora/.test(F(Object.assign(new Error("No device selected."), { name: "NotFoundError" })).message));
  // ---- 9) sin impresora autorizada y sin pedir permiso: no es un error
  reset(); const G = newTab("G"); G.nav.usb.getDevices = async () => [];
  assert.strictEqual(await G.Q.connect(false), null);

  console.log("ql_usb_connect_check OK");
})().catch((e) => { console.error(e); process.exit(1); });
