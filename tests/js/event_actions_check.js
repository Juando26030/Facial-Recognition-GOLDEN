// Permisos de las acciones del cuadrito del calendario (EventActions.actionsFor): los mismos de la fila de Eventos / Clientes.
const assert = require('assert');
const { actionsFor } = require('../../static/js/event-actions.js');
const ids = (ev, role) => actionsFor(ev, role).map((a) => a.id);
const creado = { id: 7, status: 'creado' }, enProceso = { id: 7, status: 'en_proceso' };

assert.deepStrictEqual(ids(creado, 'coordinador'), ['enter', 'edit', 'status']);
assert.deepStrictEqual(ids(enProceso, 'comercial'), ['enter', 'edit', 'status']);          // comercial no devuelve, no exporta, no elimina
assert.deepStrictEqual(ids(creado, 'admin'), ['enter', 'edit', 'status', 'delete']);
assert.deepStrictEqual(ids(enProceso, 'admin'), ['enter', 'edit', 'status', 'revert', 'delete']);
assert.deepStrictEqual(ids(enProceso, 'super_admin'), ['enter', 'edit', 'status', 'revert', 'export', 'delete']);
assert.deepStrictEqual(ids(creado, 'super_admin'), ['enter', 'edit', 'status', 'export', 'delete']);
assert.strictEqual(actionsFor(creado, 'admin')[0].href, '/kiosk/7');          // «Ingresar» va al mismo quiosco que en la lista
assert(actionsFor(creado, 'admin').find((a) => a.id === 'delete').danger);
console.log('event_actions_check OK');
