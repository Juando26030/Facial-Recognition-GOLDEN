/* Quién puede qué con lo archivable (Fase 3). Lógica pura, sin DOM (se prueba con Node: tests/js/archive_rules_check.js). El servidor decide siempre; esto solo muestra u oculta botones.
   Estados de evento: archivar/restaurar admin+. Plantillas de formulario: archivar/restaurar coordinador+ (decisión 7-nov-2026). Borrado definitivo: solo super_admin. */
(function (root) {
  'use strict';
  const RANK = { cliente: 0, digitador: 1, coordinador: 2, comercial: 3, admin: 4, super_admin: 5 };
  const MIN = { event_state: 'admin', form_template: 'coordinador' };
  const atLeast = (role, min) => Object.prototype.hasOwnProperty.call(RANK, role) && RANK[role] >= RANK[min];

  /* kind: 'event_state' | 'form_template'. Devuelve qué acciones se ofrecen para un ítem (archived = ya archivado). */
  function actions(role, kind, archived) {
    const manage = atLeast(role, MIN[kind] || 'super_admin');
    return {
      canViewArchived: manage,
      archive: manage && !archived,
      restore: manage && !!archived,
      del: role === 'super_admin' && !!archived,
    };
  }

  const api = { RANK, MIN, atLeast, actions };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GWArchiveRules = api;
})(typeof window !== 'undefined' ? window : globalThis);
