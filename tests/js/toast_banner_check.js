// Prueba de que los avisos (toasts) nunca quedan tapados por la franja de contingencia (static/js/toast.js + contingency.js). Correr: node tests/js/toast_banner_check.js
const fs = require('fs');
const assert = require('assert');
const C = require('../../static/js/contingency.js');

class El {
  constructor(tag) { this.tag = tag; this.style = {}; this.dataset = {}; this.attrs = {}; this.children = []; this.parentNode = null; this.textContent = ''; this._h = 0; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() {}
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this); }
  getBoundingClientRect() { return { bottom: this._h }; }
}
const body = new El('body');
global.window = {};
global.document = { head: new El('head'), body, createElement: (t) => new El(t),
  querySelector: (sel) => (sel === '[data-golden-banner]' ? body.children.find((c) => c.attrs['data-golden-banner']) || null : null), addEventListener() {} };
global.requestAnimationFrame = (f) => f();
global.setTimeout = () => 0;
eval(fs.readFileSync('static/js/toast.js', 'utf8'));
const container = () => body.children.find((c) => c.style.cssText && /z-index/.test(c.style.cssText));

(async () => {
  window.showToast('sin franja', 'success');
  assert.strictEqual(container().style.top, '20px', 'sin franja: arriba, como siempre');
  const z = (el) => Number(/z-index:\s*(\d+)/.exec(el.style.cssText)[1]);
  // la franja REAL de contingencia (contingency.js) lleva la marca y los avisos quedan por encima y debajo de ella
  const c = C.create({ idb: undefined, fetch: async () => ({}), subtle: {}, document: global.document, eventId: 1, setInterval() {}, clearInterval() {}, setTimeout() {}, clearTimeout() {} });
  c.lastError = 'unsupported'; c.render();
  const banner = body.children.find((x) => x.attrs['data-golden-banner']);
  assert.ok(banner, 'la franja lleva data-golden-banner'); assert.ok(z(container()) > z(banner), 'los avisos van por encima de la franja (z-index)');
  banner._h = 44;
  window.showToast('Error de red', 'error');
  assert.strictEqual(container().style.top, '56px', 'y desplazados bajo la franja (altura 44 + 12)');
  banner._h = 90;                                   // franja de dos líneas (iPad vertical)
  window.showToast('otro', 'error'); assert.strictEqual(container().style.top, '102px');
  banner.remove(); window.showToast('sin franja otra vez', 'success'); assert.strictEqual(container().style.top, '20px', 'al quitarse la franja vuelven arriba');
  console.log('toast.js: los avisos quedan por encima y bajo la franja OK');
})().catch((e) => { console.error(e); process.exit(1); });
