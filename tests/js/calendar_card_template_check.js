// Tarjeta del calendario con el contrato ÚNICO (plantilla de evento): renderCalendarCard(event, EventFields.calendarLayout(tpl)).
// Campos base y personalizados, dinero COP, fechas, comercial/coordinador, interruptores como insignias, inventario resumido, retirados/vacíos omitidos, XSS y respaldo.
const assert = require('assert');
const EF = require('../../static/js/event-field-render.js');
const { renderCalendarCard } = require('../../static/js/calendar-card.js');
const base = require('./event_template_default.json');

const F = (type, extra) => Object.assign({ key: 'c_x', type, title: 'Campo', required: false, retired: false, options: [], config: {}, help: '' }, extra || {});
const tpl = JSON.parse(JSON.stringify(base));
tpl.people = { commercial: [{ id: 9, name: 'Luz Mar' }], coordinator: [{ id: 4, name: 'Pedro' }] };
tpl.fields.push(
  F('money', { key: 'c_valor', title: 'Valor del contrato', config: { currency: 'COP' } }),
  F('text_short', { key: 'c_xss', title: 'Nota <b>x</b>' }),
  F('text_long', { key: 'c_largo', title: 'Detalle' }),
  F('commercial', { key: 'c_comer', title: 'Segunda comercial' }),
  F('contact', { key: 'c_cont', title: 'Contacto' }),
  F('country', { key: 'c_pais', title: 'País sede' }),
  F('inventory', { key: 'c_inv', title: 'Equipos', config: { inventory_types: [{ key: 'pc', label: 'Computadores', refs: ['Portátil'] }, { key: 'pa', label: 'Pañoletas', refs: [] }] } }),
  F('bandana_colors', { key: 'c_pan', title: 'Pañoletas', config: { max: 2 } }),
  F('text_short', { key: 'c_viejo', title: 'Viejo', retired: true }),
  F('datetime', { key: 'c_dt', title: 'Cierre' }));
tpl.calendar_layout = { zones: {
  top: [{ key: 'name', label: false }, { key: 'event_code', label: false }],
  left: [{ key: 'start_date', label: true }, { key: 'c_valor', label: true }, { key: 'c_xss', label: true }, { key: 'c_pais', label: true }, { key: 'c_cont', label: true }],
  right: [{ key: 'sw_facial_enabled', label: true }, { key: 'sw_inventory_enabled', label: true }, { key: 'c_comer', label: true }, { key: 'coordinator_staff_id', label: true }, { key: 'c_dt', label: true }],
  bottom: [{ key: 'c_inv', label: true }, { key: 'c_pan', label: true }, { key: 'c_largo', label: true }, { key: 'c_viejo', label: true }, { key: 'sin_campo', label: true }, { key: 'notes', label: true }] } };
const layout = EF.calendarLayout(tpl);
const ev = { id: 1, name: 'Feria <img src=x onerror=1>', event_code: 'FER-26', status: 'en_proceso', start_date: '2026-11-11', coordinator_name: 'Pedro', commercial_name: 'Luz Mar', switches: { facial_enabled: true, inventory_enabled: false },
  extra: { c_valor: 2500000, c_xss: '<script>alert(1)</script>', c_pais: 'México', c_cont: { name: 'Ana', phone: '3001234567' }, c_comer: 9, c_dt: '2026-11-20T18:30',
    c_inv: [{ type: 'pc', qty: 2, ref: 'Portátil' }, { type: 'pa', qty: 40, ref: null }], c_pan: [{ name: 'Rojo', hex: '#c0392b' }, { name: '', hex: '#111111' }], c_viejo: 'dato antiguo', c_largo: 'línea 1\nlínea 2' } };

const h = renderCalendarCard(ev, layout);
// estructura: encabezado, dos columnas, franja inferior
assert(h.includes('cal-card__top') && h.includes('cal-card__col--left') && h.includes('cal-card__col--right') && h.includes('cal-card__bottom'));
// nombre grande (primero del encabezado) y escapado
assert(h.includes('cal-card__f--strong') && h.includes('Feria &lt;img src=x onerror=1&gt;') && !h.includes('<img'));
assert(!/<script/i.test(h) && h.includes('&lt;script&gt;alert(1)&lt;/script&gt;'));
assert(h.includes('Nota &lt;b&gt;x&lt;/b&gt;'), 'el título del admin también se escapa');
// valores
assert(h.includes('11/11/2026') && h.includes('$ 2.500.000') && h.includes('México') && h.includes('Ana · 3001234567'));
assert(h.includes('Luz Mar') && h.includes('Pedro') && h.includes('20/11/2026 18:30'));
assert(h.includes('Computadores ×2 (Portátil), Pañoletas ×40'), 'inventario resumido');
assert(h.includes('Rojo, #111111'));
// interruptores: insignias Sí/No
assert(/gw-badge gw-badge--ok cal-card__badge">Sí</.test(h) && />No<\/span>/.test(h));
// retirados, inexistentes y vacíos (notes sin valor) no se pintan
assert(!h.includes('dato antiguo') && !h.includes('Viejo') && !h.includes('Observaciones') && !h.includes('sin_campo'));
// texto largo conserva saltos
assert(h.includes('cal-card__f--long') && h.includes('línea 1\nlínea 2'));
// estado siempre visible
assert(h.includes('En Proceso'));
// un evento viejo (sin extra ni switches) no rompe y solo pinta lo que tiene
const old = renderCalendarCard({ id: 2, name: 'Viejo', event_code: 'V1', status: 'creado' }, layout);
assert(old.includes('Viejo') && !old.includes('$ ') && !old.includes('Computadores') && !old.includes('cal-card__bottom'));
// título del campo se oculta con label:false
const lay2 = EF.calendarLayout(Object.assign({}, tpl, { calendar_layout: { zones: { top: [], left: [{ key: 'c_pais', label: false }], right: [], bottom: [] } } }));
const h2 = renderCalendarCard(ev, lay2);
assert(!h2.includes('País sede') && h2.includes('México'));
// respaldo: sin layout (la plantilla no cargó) se usa la tarjeta de siempre; layout inválido tampoco rompe
assert(renderCalendarCard(ev, null).includes('cal-card__col--left'));
assert.doesNotThrow(() => renderCalendarCard(ev, { zones: {}, fields: {} }));
assert.doesNotThrow(() => renderCalendarCard(null, layout));
// la plantilla de fábrica pinta nombre, código, ciudad, fechas, horas, coordinador, lugar y comercial
const fab = renderCalendarCard({ id: 3, name: 'Gala', event_code: 'G1', city: 'Bogotá', start_date: '2026-12-01', end_date: '2026-12-02', event_time_start: '08:00', coordinator_name: 'Pedro', location: 'Corferias', commercial_name: 'Luz' }, EF.calendarLayout(base));
['Gala', 'G1', 'Bogotá', '01/12/2026', '02/12/2026', '08:00', 'Pedro', 'Corferias', 'Luz'].forEach((t) => assert(fab.includes(t), 'fábrica sin ' + t));
console.log('calendar_card_template_check OK');
