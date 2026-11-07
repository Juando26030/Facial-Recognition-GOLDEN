// Humo del cuadrito (EventActions.create) con un DOM mínimo falso: abre, cierra con Escape y devuelve el foco; abre/cierra en el segundo clic del mismo evento.
const assert = require('assert');
const { create } = require('../../static/js/event-actions.js');

function el() {
  const l = {}, a = {};
  const o = { hidden: false, className: '', innerHTML: '', style: {}, offsetWidth: 100, offsetHeight: 100, focused: 0,
    appendChild() {}, addEventListener(t, f) { (l[t] = l[t] || []).push(f); }, setAttribute(k, v) { a[k] = v; }, getAttribute(k) { return a[k]; },
    contains(x) { return x === o; }, focus() { o.focused++; doc.activeElement = o; }, getBoundingClientRect() { return { left: 10, top: 10, bottom: 30 }; },
    querySelectorAll() { return []; }, closest() { return null; }, fire(t, e) { (l[t] || []).forEach((f) => f(e)); } };
  return o;
}
const dl = {};
const doc = { activeElement: null, body: { appendChild() {} }, createElement: () => el(), querySelector: () => null, contains: () => true,
  addEventListener(t, f) { (dl[t] = dl[t] || []).push(f); } };
const root = { document: doc, innerWidth: 1200, innerHeight: 800, matchMedia: () => ({ matches: false }), addEventListener() {}, setTimeout };
const pop = create({ env: root, role: 'admin', icon: () => '', onChanged() {} });
const opener = el();
const ev = { id: 3, name: 'Feria', status: 'creado', tenant_name: 'Acme', event_code: 'F1' };
pop.open(opener, ev);
assert(pop.isOpen() && opener.getAttribute('aria-expanded') === 'true');
dl.keydown.forEach((f) => f({ key: 'Escape', preventDefault() {} }));
assert(!pop.isOpen() && opener.getAttribute('aria-expanded') === 'false' && opener.focused === 1, 'Escape cierra y devuelve el foco');
pop.open(opener, ev);
dl.mousedown.forEach((f) => f({ target: {} }));
assert(!pop.isOpen(), 'clic fuera cierra');
console.log('event_actions_dom_check OK');
