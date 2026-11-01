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

  // Resumen de una línea (P10): «Ciudad = Bogotá y Tipo = Empleado»; los subgrupos van entre paréntesis y un grupo con nombre empieza por «Nombre: ».
  const OPS = { equals: '=', not_equals: '≠', contains: 'contiene', in: 'es', filled: 'tiene respuesta' };
  function summary(n, labelOf) {
    if (!n) return '';
    if (!isGroup(n)) {
      const v = Array.isArray(n.value) ? n.value.join(' / ') : n.value;
      return `${labelOf(n.field)} ${OPS[n.op] || n.op}${n.op === 'filled' ? '' : ' ' + (v === '' || v == null ? '…' : v)}`;
    }
    const parts = n.rules.map((r) => (isGroup(r) && r.rules.length > 1 && !r.name ? '(' + summary(r, labelOf) + ')' : summary(r, labelOf))).filter(Boolean);
    const joined = parts.join(n.match === 'any' ? ' o ' : ' y ');
    return n.name ? `${n.name}: ${joined}` : joined;
  }
  // Tandas de 2 o más filas seguidas con la MISMA condición (para plegarlas en el lienzo): [{start, end, key, cond}] con `end` exclusivo. Una fila solo cuenta si todos sus elementos tienen la misma condición.
  function bands(rows, fields) {
    const keyOf = (row) => {
      const ks = row.items.map((id) => { const c = fields[id] && fields[id].show_if; return c ? JSON.stringify(c) : ''; });
      return ks.length && ks[0] && ks.every((k) => k === ks[0]) ? ks[0] : '';
    };
    const out = [];
    let i = 0;
    while (i < rows.length) {
      const k = keyOf(rows[i]);
      let j = i + 1;
      while (k && j < rows.length && keyOf(rows[j]) === k && (rows[j].sheet || '') === (rows[i].sheet || '')) j++;
      if (k && j - i >= 2) out.push({ start: i, end: j, key: k, cond: JSON.parse(k) });
      i = j;
    }
    return out;
  }

  const api = { summary, bands, MAX_DEPTH, MAX_GROUP_RULES, MAX_LEAVES, isGroup, group, leaves, depth, at, update, remove, canAddLeaf, canAddGroup, addLeaf, addGroup, compact, prune };
  if (typeof window !== 'undefined') window.CondTree = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
