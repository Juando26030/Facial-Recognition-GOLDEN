// Contrato de renderCalendarCard (static/js/calendar-card.js): distribución por zonas, escape, campos vacíos, claves desconocidas y layout por defecto.
const assert = require('assert');
const { renderCalendarCard, renderCalendarMini, DEFAULT_LAYOUT, FIELD_CATALOG } = require('../../static/js/calendar-card.js');

const ev = { id: 1, event_code: 'FER-26', name: 'Feria <b>Verde</b>', tenant_name: 'Acme', location: 'Corferias', city: 'Bogotá', status: 'en_proceso',
  start_date: '2026-11-11', end_date: '2026-11-13', event_time_start: '08:00', event_time_end: '18:00', commercial_name: 'Ana', coordinator_name: '', bandana_color_name: 'Rojo' };

// 1) Por defecto: tres zonas, nombre sin título, fechas dd/mm/aaaa, estado con su etiqueta, nada sin escapar
let h = renderCalendarCard(ev, null);
assert(h.includes('cal-card__col--left') && h.includes('cal-card__col--right') && h.includes('cal-card__bottom'));
assert(h.includes('Feria &lt;b&gt;Verde&lt;/b&gt;') && !h.includes('<b>Verde'));
assert(h.includes('11/11/2026 – 13/11/2026') && h.includes('08:00 – 18:00') && h.includes('En Proceso'));
assert(h.includes('Corferias · Bogotá'));
assert(!h.includes('>Evento<'), 'el nombre va sin título');
// 2) Campo sin valor: ni valor ni título (coordinador vacío)
assert(!h.includes('Coordinador'));
assert(h.includes('Comercial') && h.includes('Pañoleta'));
// 3) Layout propio: orden, zona, título propio, sin título; clave desconocida ignorada; zona inválida cae en izquierda
h = renderCalendarCard(ev, { fields: [
  { key: 'status', zone: 'bottom', label: 'Situación' }, { key: 'event_code', zone: 'bottom', label: false },
  { key: 'no_existe', zone: 'right' }, { key: 'tenant_name', zone: 'arriba' } ] });
assert(h.indexOf('Situación') < h.indexOf('FER-26'));
assert(!h.includes('cal-card__col--right') && h.includes('cal-card__col--left') && h.includes('Acme'));
assert(!h.includes('>Código<'));
// 4) Layout inválido o evento vacío no rompen
assert.strictEqual(renderCalendarCard(ev, { fields: 'x' }), renderCalendarCard(ev, DEFAULT_LAYOUT));
assert.doesNotThrow(() => renderCalendarCard(null, undefined));
assert.strictEqual(renderCalendarCard({}, { fields: [] }), '<span class="cal-card"></span>');
// 5) Un solo día: sin rango repetido
assert(renderCalendarCard({ start_date: '2026-11-11', end_date: '2026-11-11' }, { fields: [{ key: 'dates', zone: 'left' }] }).includes('<span class="cal-card__v">11/11/2026</span>'));
// 6) Todo lo del catálogo tiene título y el layout por defecto solo usa claves del catálogo
Object.values(FIELD_CATALOG).forEach((d) => assert(d.label && typeof d.value === 'function'));
DEFAULT_LAYOUT.fields.forEach((f) => assert(f.key in FIELD_CATALOG));
// 7) Calendario plegado: color de pañoleta + nombre + código, todo escapado; sin color queda el recuadro punteado
const mini = renderCalendarMini({ name: 'Feria <b>Verde</b>', event_code: 'FER-26', bandana_colors: [{ hex: '#c0392b', name: 'Rojo' }] });
assert(mini.includes('cal-mini__name') && mini.includes('Feria &lt;b&gt;Verde&lt;/b&gt;') && mini.includes('FER-26') && mini.includes('data-bandana="#c0392b"') && !mini.includes('<b>Verde'));
assert(renderCalendarMini({ name: 'X' }).includes('cal-card__sw--empty') && !renderCalendarMini({ name: 'X' }).includes('cal-mini__code'));
assert.doesNotThrow(() => renderCalendarMini(null));
console.log('calendar_card_check OK');
