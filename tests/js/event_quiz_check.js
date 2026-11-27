/* «Configurar el evento por cuestionario» (static/js/event-quiz.js): qué preguntas se ven, qué respuesta se reconoce del estado y qué se cambia. Lógica pura, sin DOM. */
const assert = require('assert');
const { visible, detect, plan, lanesText } = require('../../static/js/event-quiz.js');

const qs = [
  { id: 'zonas', when: {}, options: [{ v: 'si', set: [{ k: 'check', id: 'areasEnabled', v: true }] }, { v: 'no', set: [{ k: 'check', id: 'areasEnabled', v: false }] }] },
  { id: 'perm', when: { zonas: ['si'] }, options: [{ v: 'si', set: [{ k: 'check', id: 'dwellEnabled', v: true }] }, { v: 'no', set: [{ k: 'check', id: 'dwellEnabled', v: false }] }] },
  { id: 'min', when: { perm: ['si'] }, options: [{ v: 'si', set: [] }, { v: 'no', set: [] }] },
  { id: 'lista', when: {}, options: [{ v: 'base', set: [{ k: 'check', id: 'selfregOn', v: false }] }, { v: 'sola', set: [{ k: 'check', id: 'selfregOn', v: true }] }, { v: 'ambas', set: [{ k: 'check', id: 'selfregOn', v: true }] }] },
  { id: 'roles', when: {}, options: [{ v: 'si', set: [{ k: 'state', key: 'categories', v: true }] }, { v: 'no', set: [{ k: 'state', key: 'categories', v: false }] }] },
];
const byId = {}; qs.forEach((q) => { byId[q.id] = q; });

// 1) Visibilidad en cadena: «min» solo con zonas Y permanencia
assert.strictEqual(visible(byId.min, { zonas: 'si', perm: 'si' }, byId), true);
assert.strictEqual(visible(byId.min, { zonas: 'no', perm: 'si' }, byId), false);
assert.strictEqual(visible(byId.perm, {}, byId), false);

// 2) Reconocer la respuesta: una sola opción coincide → esa; varias → ninguna
const dom = { areasEnabled: true, dwellEnabled: false, selfregOn: true };
const flags = { categories: true };
const read = (op) => (op.k === 'state' ? flags[op.key] === op.v : (op.id in dom ? dom[op.id] === op.v : null));
assert.strictEqual(detect(byId.zonas, read), 'si');
assert.strictEqual(detect(byId.lista, read), null);          // «sola» y «ambas» encienden lo mismo: no se adivina
assert.strictEqual(detect(byId.roles, read), 'si');          // por el estado del evento
assert.strictEqual(detect(byId.min, read), null);            // opciones sin cambios: nunca se reconocen

// 3) Plan: solo lo que todavía no coincide, nunca lo de «estado»
assert.deepStrictEqual(plan(byId.zonas, 'si', read), []);
assert.deepStrictEqual(plan(byId.zonas, 'no', read).map((o) => o.id), ['areasEnabled']);
assert.deepStrictEqual(plan(byId.roles, 'no', read), []);
assert.deepStrictEqual(plan(byId.zonas, 'otra', read), []);

// 4) Filas de turnos: conserva los nombres que ya había
assert.strictEqual(lanesText('A=Mesa 1, B=Mesa 2', 3), 'A=Mesa 1, B=Mesa 2, C');
assert.strictEqual(lanesText('A=Mesa 1, B=Mesa 2', 1), 'A=Mesa 1');
assert.strictEqual(lanesText('', 2), 'A, B');

console.log('event_quiz_check OK');
