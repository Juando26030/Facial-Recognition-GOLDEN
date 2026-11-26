// Rediseño de Estadísticas (26-nov-2026): lo principal de inventario y zonas (static/js/stats-control.js) sin navegador.
const fs = require('fs'); const path = require('path'); const assert = require('assert');
global.window = {};
eval(fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', 'stats-control.js'), 'utf8'));
const C = window.GWStatsControl;
assert.strictEqual(C._pctText(0.4), '0,4%');
assert.strictEqual(C._pctText(20), '20%');
assert.strictEqual(C._pctText(null), '');
const inv = { units: 2, people: 2, initial: 3807, remaining: 3805,
  groups: [{ name: 'Alimentación', units: 1, people: 1, initial: 250, remaining: 249, pct: 0.4, items: [{ name: 'Mazorcada Corferias', delivered: 1, initial: 250, remaining: 249, pct: 0.4 }] }],
  items: [{ name: 'Postre Muffin', delivered: 1, initial: 3557, remaining: 3556, pct: 0, people: 1 }] };
const h = C._inventoryHtml(inv);
assert(h.includes('Unidades entregadas') && h.includes('Personas atendidas') && h.includes('Quedan en el inventario'));
assert(h.includes('Mazorcada Corferias') && h.includes('<b>1</b> de 250 entregada(s) · quedan <b>249</b>'), h);
assert(h.includes('0,4%') && h.includes('Otros productos') && h.includes('3.556'));
const z = C._zonesHtml({ people: 2, inside: 1, entries: 2, exits: 1, pct: 50, registered: 4, zones: [{ name: 'VIP', people: 2, inside: 1, entries: 2, exits: 1, pct: 50, children: [{ name: 'Puerta', people: 1, inside: 0, entries: 1, exits: 0, pct: 25 }] }] });
assert(z.includes('Personas que entraron') && z.includes('de 4 registrada(s)') && z.includes('gw-sc-row--sub') && z.includes('50%'));
assert(!C._inventoryHtml({ units: 0, people: 0, initial: 0, remaining: 0, groups: [], items: [{ name: 'X<script>', delivered: 0, initial: 0, remaining: 0, pct: null }] }).includes('<script>'));
console.log('stats_control_check OK');
