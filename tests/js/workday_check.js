// Jornada (Fase 5): espejo JS de app/workday.py (límites inclusivos, cruce de medianoche, sin horas), campo de la plantilla en el renderizador, la tarjeta del calendario y el cálculo en vivo.
const assert = require('assert');
const W = require('../../static/js/workday.js');
const EF = require('../../static/js/event-field-render.js');
const { renderCalendarCard } = require('../../static/js/calendar-card.js');
const base = require('./event_template_default.json');

// 1) Mismos casos que tests/test_jornada.py (tope superior inclusivo)
[['08:00', '08:01', 'media', 0.02], ['08:00', '13:00', 'media', 5], ['08:00', '14:00', 'media', 6], ['08:00', '14:01', 'intermedia', 6.02], ['08:00', '16:30', 'intermedia', 8.5],
  ['08:00', '17:00', 'intermedia', 9], ['08:00', '17:01', 'completa', 9.02], ['08:00', '18:00', 'completa', 10], ['08:00', '20:00', 'completa', 12], ['08:00', '20:01', 'extendida', 12.02],
  ['06:00', '23:59', 'extendida', 17.98], ['00:00', '23:59', 'extendida', 23.98], ['22:00', '04:00', 'media', 6], ['20:00', '06:00', 'completa', 10], ['18:00', '08:00', 'extendida', 14], ['23:30', '00:30', 'media', 1]
].forEach(([a, b, key, hours]) => {
  const w = W.compute(a, b);
  assert.strictEqual(w.key, key, a + '-' + b); assert.strictEqual(w.hours, hours, a + '-' + b);
});
assert.deepStrictEqual(W.TIERS.map((t) => t.label), ['Media jornada', 'Jornada intermedia (entre media y completa)', 'Jornada completa', 'Jornada extendida']);
// 2) Sin jornada: falta una hora, hora inválida o inicio = fin
[[null, '18:00'], ['08:00', null], ['', ''], ['08:00', '08:00'], ['25:00', '18:00'], ['08:60', '18:00'], ['ocho', '18:00'], ['08:00', '24:00'], [undefined, undefined]].forEach(([a, b]) => assert.strictEqual(W.compute(a, b), null, String(a) + '/' + b));
assert.strictEqual(W.text('08:00', '18:00'), 'Jornada completa · 10 h');
assert.strictEqual(W.text('08:00', '16:15'), 'Jornada intermedia (entre media y completa) · 8,25 h');
assert.strictEqual(W.text('', ''), '');
// 3) Barrido de todas las duraciones: monótono y con los topes de siempre
const order = ['media', 'intermedia', 'completa', 'extendida']; let last = -1;
for (let m = 1; m < 1440; m++) {
  const w = W.compute('00:00', String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0')), h = m / 60;
  assert.strictEqual(w.key, h <= 6 ? 'media' : h <= 9 ? 'intermedia' : h <= 12 ? 'completa' : 'extendida');
  assert.ok(order.indexOf(w.key) >= last); last = order.indexOf(w.key);
}

// 4) Renderizador: campo «workday» de la plantilla de fábrica; valor desde las horas del evento; el servidor como respaldo
const field = base.fields.find((f) => f.key === 'workday');
assert.ok(field && field.type === 'workday' && field.required === false);
assert.strictEqual(EF.displayValue(field, { event_time_start: '08:00', event_time_end: '18:00' }), 'Jornada completa · 10 h');
assert.strictEqual(EF.displayValue(field, { event_time_start: '', event_time_end: '' }), '');
assert.strictEqual(EF.displayValue(field, { workday_label: 'Media jornada', workday_hours: 4.5 }), 'Media jornada · 4,5 h');
assert.strictEqual(EF.validateValue(field, null), null);
assert.strictEqual(EF.workdayText('08:00', '14:00'), 'Media jornada · 6 h'); assert.strictEqual(EF.workdayText('', '14:00'), '—');
const html = EF.renderField(field, { value: null, ctx: {} });
assert.ok(html.includes('readonly') && html.includes('data-evf-workday') && html.includes('value="—"') && html.includes('(calculada)') && !html.includes('(opcional)'));
assert.ok(EF.renderField(field, { value: 'Jornada completa · 10 h', ctx: {} }).includes('value="Jornada completa · 10 h"'));

// 5) Tarjeta del calendario: solo sale si la plantilla la puso en una zona; insignia con el texto; sin horas no se pinta; escapado
const tpl = JSON.parse(JSON.stringify(base));
const ev = { id: 1, name: 'Feria', event_code: 'F-1', status: 'en_proceso', event_time_start: '08:00', event_time_end: '18:00', switches: {}, extra: {} };
assert.ok(!renderCalendarCard(ev, EF.calendarLayout(tpl)).includes('Jornada'), 'de fábrica no sale en el calendario');
tpl.calendar_layout.zones.right.push({ key: 'workday', label: false });
let h = renderCalendarCard(ev, EF.calendarLayout(tpl));
assert.ok(h.includes('cal-card__wd') && h.includes('data-field="workday"') && h.includes('gw-badge gw-badge--info cal-card__wd-b') && h.includes('Jornada completa · 10 h'));
assert.ok(!h.includes('cal-card__k">Jornada'), 'sin nombre del campo cuando label es false');
tpl.calendar_layout.zones.right[tpl.calendar_layout.zones.right.length - 1].label = true;
assert.ok(renderCalendarCard(ev, EF.calendarLayout(tpl)).includes('<span class="cal-card__k">Jornada</span>'));
assert.ok(!renderCalendarCard(Object.assign({}, ev, { event_time_end: '' }), EF.calendarLayout(tpl)).includes('cal-card__wd'), 'sin horas no se pinta');
const evil = JSON.parse(JSON.stringify(tpl)); evil.fields.find((f) => f.key === 'workday').title = '<img src=x>';
assert.ok(!renderCalendarCard(ev, EF.calendarLayout(evil)).includes('<img'));

// 6) En vivo: bindWorkday reescribe los controles al cambiar las horas (host simulado)
const outs = [{ value: '' }], listeners = {}, state = { s: '', e: '' };
const host = { addEventListener: (t, f) => { listeners[t] = f; }, querySelectorAll: () => outs, querySelector: () => null };
const refresh = EF.bindWorkday(host, { read: () => ({ start: state.s, end: state.e }) });
assert.strictEqual(outs[0].value, '—');
state.s = '09:00'; state.e = '15:30'; listeners.change(); assert.strictEqual(outs[0].value, 'Jornada intermedia (entre media y completa) · 6,5 h');
state.e = '22:00'; listeners.input(); assert.strictEqual(outs[0].value, 'Jornada extendida · 13 h');
state.e = ''; refresh(); assert.strictEqual(outs[0].value, '—');
console.log('workday_check OK');
