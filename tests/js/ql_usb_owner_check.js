// Una sola pestaña dueña de la impresora (orden del 22-oct-2026, «Unable to claim interface»). Se corre con: node tests/js/ql_usb_owner_check.js
// Dos «pestañas» = dos copias de static/js/ql-usb.js que comparten el mismo navigator.locks y el mismo dispositivo USB falso.
const assert = require("assert");
const path = require("path");

const held = new Set();
const locks = {
  request(name, opts, cb) {
    if (held.has(name)) return Promise.resolve(cb(null));
    held.add(name);
    return Promise.resolve(cb({ name })).then(() => { held.delete(name); });
  },
};
const log = [];
let claimedBy = null;
function fakeDevice() {
  return {
    vendorId: 0x04f9, productName: "QL-800", opened: false, configuration: { interfaces: [{ interfaceNumber: 0, alternates: [{ interfaceClass: 7, endpoints: [{ type: "bulk", direction: "out", endpointNumber: 2 }, { type: "bulk", direction: "in", endpointNumber: 1 }] }] }] },
    async open() { this.opened = true; log.push("open"); },
    async claimInterface() { if (claimedBy && claimedBy !== this.tab) throw new Error("Unable to claim interface."); claimedBy = this.tab; log.push("claim"); },
    async releaseInterface() { if (claimedBy === this.tab) claimedBy = null; log.push("release"); },
    async close() { this.opened = false; log.push("close"); },
    async transferOut() { return { status: "ok" }; },
  };
}
const shared = fakeDevice();
function tab(name, withLocks) {              // cada llamada pone el navigator de ESTA pestaña antes de entrar al módulo
  const dev = Object.create(shared); dev.tab = name;
  const nav = { locks: withLocks ? locks : undefined, usb: { getDevices: async () => [dev], requestDevice: async () => dev } };
  const use = () => Object.defineProperty(globalThis, "navigator", { configurable: true, value: nav });
  use();
  delete require.cache[path.resolve(__dirname, "../../static/js/ql-usb.js")];
  const QL = require("../../static/js/ql-usb.js");
  return Object.assign({}, QL, { connect: (a) => { use(); return QL.connect(a); }, close: () => { use(); return QL.close(); } });
}

(async () => {
  // 1) Con Web Locks: la pestaña A es la dueña; B recibe el aviso amable (busy), no el error técnico
  const A = tab("A", true);
  const B = tab("B", true);
  assert.ok(await A.connect(false), "A toma la impresora");
  assert.strictEqual(A.isOwner(), true);
  await assert.rejects(B.connect(false), (e) => e.busy === true && e.message === A.BUSY_MSG && /otra pestaña/.test(e.message));
  // 2) A la suelta (releaseInterface + close + candado) y B la puede tomar sin tocar el cable
  log.length = 0;
  await A.close();
  assert.deepStrictEqual(log, ["release", "close"]);
  assert.strictEqual(A.isOwner(), false);
  assert.ok(await B.connect(false), "B la toma cuando A la suelta");
  await B.close();

  // 3) Sin Web Locks (u otra página vieja que la tiene tomada): claimInterface falla → mismo aviso, y la pestaña no queda con el dispositivo abierto
  const C = tab("C", false);
  const D = tab("D", false);
  assert.ok(await C.connect(false));
  log.length = 0;
  await assert.rejects(D.connect(false), (e) => e.busy === true && e.message === C.BUSY_MSG);
  assert.ok(log.includes("close"), "D cierra lo que abrió");
  assert.strictEqual(D.info(), null);
  await C.close();
  assert.ok(await D.connect(false), "D la toma después");
  await D.close();
  console.log("ql_usb_owner_check OK");
})().catch((e) => { console.error(e); process.exit(1); });
