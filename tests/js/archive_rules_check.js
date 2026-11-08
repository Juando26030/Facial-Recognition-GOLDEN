// Quién ve qué botones de archivar/restaurar/eliminar (static/js/archive-rules.js).
const assert = require('assert');
const { actions, atLeast } = require('../../static/js/archive-rules.js');

// Estados de evento: admin+ archiva y restaura; solo super_admin elimina (y solo lo archivado).
for (const r of ['cliente', 'digitador', 'coordinador', 'comercial']) {
  const a = actions(r, 'event_state', false);
  assert(!a.archive && !a.restore && !a.del && !a.canViewArchived, `${r} no gestiona estados`);
}
assert.deepStrictEqual(actions('admin', 'event_state', false), { canViewArchived: true, archive: true, restore: false, del: false });
assert.deepStrictEqual(actions('admin', 'event_state', true), { canViewArchived: true, archive: false, restore: true, del: false });
assert.deepStrictEqual(actions('super_admin', 'event_state', true), { canViewArchived: true, archive: false, restore: true, del: true });
assert(!actions('super_admin', 'event_state', false).del, 'no se elimina lo que no está archivado');

// Plantillas de formulario: coordinador+ archiva y restaura (decisión 7-nov-2026).
for (const r of ['cliente', 'digitador']) assert(!actions(r, 'form_template', false).archive, `${r} no archiva plantillas`);
for (const r of ['coordinador', 'comercial', 'admin', 'super_admin']) {
  assert(actions(r, 'form_template', false).archive && actions(r, 'form_template', true).restore, `${r} archiva y restaura plantillas`);
  assert.strictEqual(actions(r, 'form_template', true).del, r === 'super_admin', `${r}: eliminar solo super_admin`);
}
// roles desconocidos o vacíos: nada
assert(!atLeast('', 'coordinador') && !atLeast(undefined, 'admin') && !actions('raro', 'form_template', true).restore);
console.log('archive_rules_check OK');
