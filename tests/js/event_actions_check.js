// Permisos de las acciones del cuadrito del calendario (EventActions.actionsFor): los mismos de la fila de Eventos / Clientes.
const assert = require('assert');
const { actionsFor } = require('../../static/js/event-actions.js');
const ids = (ev, role) => actionsFor(ev, role).map((a) => a.id);
const creado = { id: 7, status: 'creado' }, enProceso = { id: 7, status: 'en_proceso' }, finalizado = { id: 7, status: 'finalizado' };

assert.deepStrictEqual(ids(creado, 'coordinador'), ['enter', 'edit', 'status']);
assert.deepStrictEqual(ids(enProceso, 'comercial'), ['enter', 'edit', 'status']);          // comercial no devuelve, no exporta, no elimina
assert.deepStrictEqual(ids(creado, 'admin'), ['enter', 'edit', 'status']);
assert.deepStrictEqual(ids(enProceso, 'admin'), ['enter', 'edit', 'status', 'revert']);
assert.deepStrictEqual(ids(enProceso, 'super_admin'), ['enter', 'edit', 'status', 'revert', 'export']);
assert.deepStrictEqual(ids(creado, 'super_admin'), ['enter', 'edit', 'status', 'export']);
assert.strictEqual(actionsFor(creado, 'admin')[0].href, '/kiosk/7');          // «Ingresar» va al mismo quiosco que en la lista
assert.deepStrictEqual(ids(finalizado, 'admin'), ['enter', 'edit', 'status', 'archive']);          // Fase 3: archivar (solo finalizados, admin+); eliminar ya no está en el calendario
assert.deepStrictEqual(ids(finalizado, 'comercial'), ['enter', 'edit', 'status']);
console.log('event_actions_check OK');
