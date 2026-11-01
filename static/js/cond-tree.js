/* Operaciones puras sobre el árbol de condiciones del diseñador (P9). Sin DOM: se prueba en Node (tests/js/cond_tree_check.js).
   Condición = hoja {field, op, value} o grupo {match: 'all'|'any', rules: [...], name?}; mismos límites que app/formlib.py (3 niveles de grupos, 12 hijos, 30 hojas).
   Un «camino» es la lista de posiciones desde la raíz: [] = la raíz, [1, 0] = el primer hijo del segundo hijo.        */
(function () {
  const MAX_DEPTH = 3, MAX_GROUP_RULES = 12, MAX_LEAVES = 30;
  const isGroup = (n) => !!(n && n.rules);
  const clone = (n) => JSON.parse(JSON.stringify(n));

  const group = (node) => (!node ? { match: 'all', rules: [] } : isGroup(node) ? clone(node) : { match: 'all', rules: [clone(node)] });   // raíz siempre como grupo para editarla
  const leaves = (n) => (!n ? [] : isGroup(n) ? n.rules.flatMap(leaves) : [n]);
  const depth = (n) => (isGroup(n) ? 1 + Math.max(0, ...n.rules.map(depth)) : 0);
  const at = (root, path) => path.reduce((n, i) => n && n.rules && n.rules[i], root);

  function update(root, path, fn) {
    const out = clone(root);
    if (!path.length) return fn(out);
    const parent = at(out, path.slice(0, -1));
    parent.rules[path[path.length - 1]] = fn(parent.rules[path[path.length - 1]]);
    return out;
  }
  function remove(root, path) {
    if (!path.length) return group(null);
    const out = clone(root), parent = at(out, path.slice(0, -1));
    parent.rules.splice(path[path.length - 1], 1);
    return out;
  }
  // ¿se puede agregar una hoja / un grupo dentro del grupo en `path`? (mismos topes que el servidor)
  const canAddLeaf = (root, path) => { const g = at(root, path); return isGroup(g) && g.rules.length < MAX_GROUP_RULES && leaves(root).length < MAX_LEAVES; };
  const canAddGroup = (root, path) => canAddLeaf(root, path) && path.length + 2 <= MAX_DEPTH;
  const addLeaf = (root, path, leaf) => (canAddLeaf(root, path) ? update(root, path, (g) => ({ ...g, rules: g.rules.concat([clone(leaf)]) })) : root);
  const addGroup = (root, path, leaf) => (canAddGroup(root, path) ? update(root, path, (g) => ({ ...g, rules: g.rules.concat([{ match: 'all', rules: leaf ? [clone(leaf)] : [] }]) })) : root);

  // Igual que el servidor al guardar: grupos vacíos fuera; un grupo con un solo hijo y sin nombre se reemplaza por ese hijo.
  function compact(n) {
    if (!n) return null;
    if (!isGroup(n)) return n;
    const kids = n.rules.map(compact).filter(Boolean);
    if (!kids.length) return null;
    if (kids.length === 1 && !n.name) return kids[0];
    return { ...n, rules: kids };
  }
  function prune(n, fieldId) {   // al borrar un campo: se quitan las hojas que lo usaban
    if (!n) return null;
    if (!isGroup(n)) return n.field === fieldId ? null : n;
    return compact({ ...n, rules: n.rules.map((r) => prune(r, fieldId)).filter(Boolean) });
  }

  const api = { MAX_DEPTH, MAX_GROUP_RULES, MAX_LEAVES, isGroup, group, leaves, depth, at, update, remove, canAddLeaf, canAddGroup, addLeaf, addGroup, compact, prune };
  if (typeof window !== 'undefined') window.CondTree = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
