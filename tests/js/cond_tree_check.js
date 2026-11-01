// P9: operaciones del árbol de condiciones del diseñador (static/js/cond-tree.js). Correr: node tests/js/cond_tree_check.js
const assert = require('assert');
const T = require('../../static/js/cond-tree.js');

const L = (field, value) => ({ field, op: 'equals', value: value || 'x' });
assert.deepStrictEqual(T.group(null), { match: 'all', rules: [] });
assert.deepStrictEqual(T.group(L('a')), { match: 'all', rules: [L('a')] }, 'una regla suelta se edita como grupo');

let root = T.group(null);
root = T.addLeaf(root, [], L('a')); root = T.addLeaf(root, [], L('b'));
assert.strictEqual(T.leaves(root).length, 2);
root = T.addGroup(root, [], L('c'));                                   // grupo dentro del raíz: nivel 2
root = T.addGroup(root, [2], L('d'));                                  // nivel 3
assert.strictEqual(T.depth(root), 3);
assert.strictEqual(T.canAddGroup(root, [2, 1]), false, 'no hay un cuarto nivel');
const same = T.addGroup(root, [2, 1], L('z'));
assert.deepStrictEqual(same, root, 'agregar donde no se puede no cambia nada');
assert.strictEqual(T.canAddLeaf(root, [2, 1]), true, 'pero sí una regla dentro del nivel 3');

// editar una hoja sin tocar el resto (inmutable)
const before = JSON.stringify(root);
const edited = T.update(root, [0], (n) => ({ ...n, value: 'otro' }));
assert.strictEqual(T.at(edited, [0]).value, 'otro'); assert.strictEqual(JSON.stringify(root), before);
assert.deepStrictEqual(T.at(root, [2, 1, 0]), L('d'));

// límites: 12 hijos y 30 hojas
let big = T.group(null);
for (let i = 0; i < 20; i++) big = T.addLeaf(big, [], L('f' + i));
assert.strictEqual(big.rules.length, T.MAX_GROUP_RULES);
let many = T.group(null);
for (let g = 0; g < 4; g++) { many = T.addGroup(many, []); for (let i = 0; i < 10; i++) many = T.addLeaf(many, [g], L('g' + g + i)); }
assert.strictEqual(T.leaves(many).length, T.MAX_LEAVES, 'tope de 30 hojas');
assert.strictEqual(T.canAddLeaf(many, [0]), false);

// quitar y compactar como el servidor
assert.deepStrictEqual(T.compact({ match: 'all', rules: [L('a')] }), L('a'), 'grupo de un solo hijo → el hijo');
assert.deepStrictEqual(T.compact({ match: 'all', name: 'Costa', rules: [L('a')] }), { match: 'all', name: 'Costa', rules: [L('a')] }, 'con nombre se conserva');
assert.strictEqual(T.compact({ match: 'all', rules: [{ match: 'any', rules: [] }] }), null);
assert.strictEqual(T.compact(null), null);
assert.deepStrictEqual(T.compact(T.remove(T.group(L('a')), [0])), null);
const two = { match: 'any', rules: [L('a'), { match: 'all', rules: [L('b'), L('c')] }] };
assert.deepStrictEqual(T.compact(T.remove(two, [1, 0])), { match: 'any', rules: [L('a'), L('c')] }, 'el subgrupo que queda con un hijo se aplana');

// borrar un campo limpia sus hojas en cualquier nivel
assert.deepStrictEqual(T.prune(two, 'b'), { match: 'any', rules: [L('a'), L('c')] });
assert.strictEqual(T.prune(L('a'), 'a'), null);
assert.strictEqual(T.prune({ match: 'all', rules: [L('a'), L('a')] }, 'a'), null);
assert.deepStrictEqual(T.prune(L('a'), 'zzz'), L('a'));
console.log('cond_tree_check OK');

// P10: resumen de una línea y tandas de filas con la misma condición
const label = (id) => ({ c: 'Ciudad', t: 'Tipo', e: 'Entidad' }[id] || id);
assert.strictEqual(T.summary(null, label), '');
assert.strictEqual(T.summary({ field: 'c', op: 'equals', value: 'Bogotá' }, label), 'Ciudad = Bogotá');
assert.strictEqual(T.summary({ field: 'c', op: 'in', value: ['Bogotá', 'Cali'] }, label), 'Ciudad es Bogotá / Cali');
assert.strictEqual(T.summary({ field: 'e', op: 'filled', value: '' }, label), 'Entidad tiene respuesta');
assert.strictEqual(T.summary({ field: 'c', op: 'equals', value: '' }, label), 'Ciudad = …');
assert.strictEqual(T.summary({ match: 'all', rules: [{ field: 'c', op: 'equals', value: 'Bogotá' }, { field: 't', op: 'equals', value: 'Empleado' }] }, label), 'Ciudad = Bogotá y Tipo = Empleado');
assert.strictEqual(T.summary({ match: 'all', rules: [{ field: 't', op: 'equals', value: 'Empleado' }, { match: 'any', rules: [{ field: 'c', op: 'equals', value: 'Bogotá' }, { field: 'c', op: 'equals', value: 'Cali' }] }] }, label), 'Tipo = Empleado y (Ciudad = Bogotá o Ciudad = Cali)');
assert.strictEqual(T.summary({ match: 'any', name: 'Costa', rules: [{ field: 'c', op: 'equals', value: 'Santa Marta' }, { field: 'c', op: 'equals', value: 'Cartagena' }] }, label), 'Costa: Ciudad = Santa Marta o Ciudad = Cartagena');
const cnd = { field: 'c', op: 'equals', value: 'Bogotá' }, other = { field: 'c', op: 'equals', value: 'Cali' };
const fields = { a: { show_if: cnd }, b: { show_if: cnd }, d: { show_if: cnd }, e: { show_if: other }, f: {}, g: { show_if: other }, h: { show_if: other } };
const rows = [{ items: ['a'] }, { items: ['b', 'd'] }, { items: ['f'] }, { items: ['e'] }, { items: ['g'] }, { items: ['h'] }, { items: ['a', 'e'] }];
const bs = T.bands(rows, fields).map((b) => [b.start, b.end]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(bs)), [[0, 2], [3, 6]], 'a+b/d comparten condición; la fila mixta y la sin condición no cuentan');
assert.deepStrictEqual(JSON.parse(JSON.stringify(T.bands([{ items: ['a'] }, { items: ['f'] }, { items: ['a'] }], fields))), [], 'una fila sola no forma tanda');
assert.deepStrictEqual(JSON.parse(JSON.stringify(T.bands([{ items: ['a'], sheet: 's1' }, { items: ['b'], sheet: 's2' }], fields))), [], 'una tanda no cruza hojas');
console.log('cond_tree_check (P10) OK');

// P10 (ajuste): qué valores de un campo ya están cubiertos por una condición
const eq = (f, v) => ({ field: f, op: 'equals', value: v });
const cov = (n, f) => [...T.coveredBy(n, f)].sort();
assert.deepStrictEqual(cov(eq('c', 'Bogotá'), 'c'), ['bogota']);
assert.deepStrictEqual(cov(eq('c', 'Bogotá'), 't'), [], 'otro campo no cubre nada');
assert.deepStrictEqual(cov({ field: 'c', op: 'in', value: ['Cali', 'Pasto'] }, 'c'), ['cali', 'pasto']);
assert.deepStrictEqual(cov({ match: 'any', rules: [eq('c', 'A'), eq('c', 'B'), eq('t', 'X')] }, 'c'), ['a', 'b'], 'un grupo O une lo que cubre cada regla');
assert.deepStrictEqual(cov({ match: 'any', rules: [eq('c', 'A'), { match: 'all', rules: [eq('c', 'B'), eq('t', 'X')] }] }, 'c'), ['a'], 'un grupo Y con otra condición no basta por sí solo');
assert.deepStrictEqual(cov({ match: 'all', rules: [eq('c', 'A'), { field: 'c', op: 'in', value: ['A', 'B'] }] }, 'c'), ['a'], 'un grupo Y de lo mismo cubre la intersección');
assert.deepStrictEqual(cov({ field: 'c', op: 'not_equals', value: 'A' }, 'c'), []); assert.deepStrictEqual(cov(null, 'c'), []);
console.log('cond_tree_check (cubiertas) OK');
